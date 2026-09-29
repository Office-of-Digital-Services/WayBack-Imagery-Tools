"""Esri Wayback WMTS Capabilities XML Parser.

Downloads and parses the Esri Wayback World Imagery WMTSCapabilities XML document,
extracting layer release identifiers, human-readable titles, ISO dates, and raster tile
URL templates into structured CapabilitiesMetadata objects.
"""

from datetime import datetime
import re
from typing import List, Optional, Union
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .models import CapabilitiesMetadata, WaybackRelease

# Official default endpoint for Esri Wayback WMTS Capabilities
DEFAULT_WMTS_URL: str = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
)

# Standard user agent header for HTTP requests
DEFAULT_USER_AGENT: str = "ArcGISPro-WaybackImageryAddin/1.0"

# Default network timeout in seconds
DEFAULT_NETWORK_TIMEOUT_SECONDS: int = 15

# Regular expression pattern to capture ISO release dates (YYYY-MM-DD)
DATE_REGEX_PATTERN: re.Pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Regular expression pattern to match Wayback release IDs (e.g. WB_2026_R07)
RELEASE_ID_REGEX_PATTERN: re.Pattern = re.compile(r"^WB_(\d{4})_R(\d{2})$", re.IGNORECASE)


class WMTSParser:
    """Parser class for fetching and analyzing Esri Wayback WMTS Capabilities."""

    def __init__(
        self,
        capabilities_url: str = DEFAULT_WMTS_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: int = DEFAULT_NETWORK_TIMEOUT_SECONDS,
    ) -> None:
        """Initializes the WMTSParser with configurable connection settings.

        Args:
            capabilities_url: The URL endpoint for the WMTS capabilities XML.
            user_agent: HTTP User-Agent string to pass in network requests.
            timeout_seconds: Request timeout in seconds.
        """
        self.capabilities_url = capabilities_url
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    def fetch_xml(self) -> str:
        """Fetches the raw XML text from the configured capabilities endpoint.

        Returns:
            The raw XML string content retrieved from the service.

        Raises:
            urllib.error.URLError: If the network request fails or times out.
            urllib.error.HTTPError: If the remote server returns an HTTP error status.
        """
        request = urllib.request.Request(
            self.capabilities_url,
            headers={"User-Agent": self.user_agent},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            encoding = response.headers.get_content_charset() or "utf-8"
            raw_bytes = response.read()
            return raw_bytes.decode(encoding, errors="replace")

    def parse_xml_content(
        self, xml_content: Union[str, bytes], source_url: Optional[str] = None
    ) -> CapabilitiesMetadata:
        """Parses WMTS capabilities XML content and returns structured CapabilitiesMetadata.

        Args:
            xml_content: Raw XML string or bytes.
            source_url: Optional URL representing the metadata source.

        Returns:
            A CapabilitiesMetadata instance containing all parsed and chronologically sorted releases.

        Raises:
            xml.etree.ElementTree.ParseError: If the XML content is malformed.
        """
        if isinstance(xml_content, str):
            xml_bytes = xml_content.encode("utf-8")
        else:
            xml_bytes = xml_content

        root = ET.fromstring(xml_bytes)

        # Extract service title if present
        service_title = "Esri Wayback World Imagery WMTS"
        for elem in root.iter():
            if elem.tag.endswith("ServiceIdentification"):
                title_elem = elem.find("{*}Title")
                if title_elem is not None and title_elem.text:
                    service_title = title_elem.text.strip()
                break

        # Discover all historical imagery releases
        raw_releases: List[dict] = []

        for elem in root.iter():
            if not elem.tag.endswith("Layer"):
                continue

            id_elem = elem.find("{*}Identifier")
            title_elem = elem.find("{*}Title")

            if id_elem is None or not id_elem.text:
                continue

            release_id = id_elem.text.strip()
            layer_title = title_elem.text.strip() if title_elem is not None and title_elem.text else release_id

            # Locate the ResourceURL tile template
            tile_url_template = ""
            for res_elem in elem.findall("{*}ResourceURL"):
                res_type = res_elem.attrib.get("resourceType", "")
                if res_type == "tile" or "template" in res_elem.attrib:
                    tile_url_template = res_elem.attrib.get("template", "").strip()
                    break

            # Attempt to extract release date from Title (e.g. 'World Imagery (Wayback 2026-08-05)')
            release_date = ""
            date_match = DATE_REGEX_PATTERN.search(layer_title)
            if date_match:
                release_date = date_match.group(1)
            else:
                # Secondary check on ID (e.g. WB_2026_R07)
                id_match = RELEASE_ID_REGEX_PATTERN.search(release_id)
                if id_match:
                    year = id_match.group(1)
                    release_date = f"{year}-01-01"

            # Validate that this is indeed a Wayback release layer
            is_wayback_layer = (
                release_id.upper().startswith("WB_")
                or "Wayback" in layer_title
                or bool(release_date)
            )

            if is_wayback_layer:
                raw_releases.append(
                    {
                        "release_id": release_id,
                        "title": layer_title,
                        "release_date": release_date,
                        "tile_url_template": tile_url_template,
                    }
                )

        # Sort releases chronologically descending: newest release first (index 0)
        def sorting_key(item: dict) -> tuple:
            # Primary sort: release_date descending
            # Secondary sort: release_id descending
            return (item["release_date"], item["release_id"])

        raw_releases.sort(key=sorting_key, reverse=True)

        # Construct immutable WaybackRelease instances with assigned chronological index
        sorted_releases: List[WaybackRelease] = []
        for index, item in enumerate(raw_releases):
            sorted_releases.append(
                WaybackRelease(
                    release_id=item["release_id"],
                    title=item["title"],
                    release_date=item["release_date"],
                    tile_url_template=item["tile_url_template"],
                    release_index=index,
                )
            )

        current_timestamp = datetime.utcnow().isoformat() + "Z"
        resolved_url = source_url or self.capabilities_url

        return CapabilitiesMetadata(
            service_title=service_title,
            capabilities_url=resolved_url,
            fetched_at=current_timestamp,
            releases=sorted_releases,
        )

    def fetch_and_parse(self) -> CapabilitiesMetadata:
        """Fetches the XML from the remote endpoint and parses it into metadata.

        Returns:
            CapabilitiesMetadata containing all historical releases.
        """
        xml_content = self.fetch_xml()
        return self.parse_xml_content(xml_content, self.capabilities_url)


def fetch_capabilities(
    url: str = DEFAULT_WMTS_URL,
    timeout_seconds: int = DEFAULT_NETWORK_TIMEOUT_SECONDS,
) -> CapabilitiesMetadata:
    """Convenience helper function to fetch and parse Wayback WMTS capabilities in one step.

    Args:
        url: The WMTS Capabilities XML endpoint URL.
        timeout_seconds: Request timeout in seconds.

    Returns:
        A fully populated CapabilitiesMetadata object.
    """
    parser = WMTSParser(capabilities_url=url, timeout_seconds=timeout_seconds)
    return parser.fetch_and_parse()


def parse_capabilities_xml(
    xml_content: Union[str, bytes],
    source_url: str = DEFAULT_WMTS_URL,
) -> CapabilitiesMetadata:
    """Convenience helper function to parse raw WMTS Capabilities XML text or bytes.

    Args:
        xml_content: XML string or bytes representation of the capabilities document.
        source_url: Source URL identifier for the metadata.

    Returns:
        A fully populated CapabilitiesMetadata object.
    """
    parser = WMTSParser(capabilities_url=source_url)
    return parser.parse_xml_content(xml_content, source_url=source_url)
