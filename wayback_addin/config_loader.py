"""Esri Wayback Configuration JSON Loader and Parser.

Fetches and parses the official Esri Wayback release catalog from
https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json
providing authoritative release numbers, ArcGIS Online Item IDs, item URLs,
and direct MapServer metadata service URLs.
"""

from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request

from .models import CapabilitiesMetadata, WaybackRelease

logger = logging.getLogger(__name__)

# Authoritative Esri Wayback configuration JSON endpoint hosted on S3
WAYBACK_CONFIG_URL: str = (
    "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
)

# Standard User-Agent header for HTTP requests
DEFAULT_USER_AGENT: str = "ArcGISPro-WaybackImageryAddin/1.0"

# Default network timeout in seconds
DEFAULT_NETWORK_TIMEOUT_SECONDS: int = 15

# Date regex pattern (YYYY-MM-DD)
_DATE_REGEX: re.Pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Standard tile URL template base
_TILE_URL_TEMPLATE: str = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery/MapServer/tile/{rel_num}/{{TileMatrix}}/{{TileRow}}/{{TileCol}}"
)


def fetch_wayback_config_json(
    config_url: str = WAYBACK_CONFIG_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: int = DEFAULT_NETWORK_TIMEOUT_SECONDS,
) -> str:
    """Fetches the raw JSON string from the Wayback configuration endpoint.

    Args:
        config_url: The URL to fetch waybackconfig.json from.
        user_agent: HTTP User-Agent header string.
        timeout_seconds: Request timeout in seconds.

    Returns:
        The raw JSON text string.

    Raises:
        urllib.error.URLError: If the network request fails or times out.
        urllib.error.HTTPError: If the remote server returns an HTTP error.
    """
    logger.info("Fetching Wayback configuration JSON from %s", config_url)
    request = urllib.request.Request(
        config_url,
        headers={"User-Agent": user_agent},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        raw_bytes = response.read()
        return raw_bytes.decode(encoding, errors="replace")


def parse_wayback_config(
    config_data: Any,
    source_url: Optional[str] = None,
) -> CapabilitiesMetadata:
    """Parses waybackconfig.json content into a structured CapabilitiesMetadata object.

    Args:
        config_data: Either a parsed dict or a raw JSON string/bytes.
        source_url: Optional source URL of the configuration.

    Returns:
        A CapabilitiesMetadata instance containing chronologically sorted releases.
    """
    if isinstance(config_data, (str, bytes)):
        config_dict = json.loads(config_data)
    elif isinstance(config_data, dict):
        config_dict = config_data
    else:
        raise ValueError(f"Unsupported config data type: {type(config_data)}")

    raw_releases: List[dict] = []

    for key, entry in config_dict.items():
        if not isinstance(entry, dict):
            continue

        try:
            numeric_rel_num = int(key)
        except ValueError:
            numeric_rel_num = None

        layer_identifier = entry.get("layerIdentifier") or f"WB_{key}"
        item_title = entry.get("itemTitle") or f"World Imagery ({layer_identifier})"
        item_id = entry.get("itemID")
        item_url = entry.get("itemURL")
        metadata_layer_url = entry.get("metadataLayerUrl")

        # Extract ISO date from releaseDate, itemTitle, or releaseDatetime
        release_date = ""
        date_cand = entry.get("releaseDate") or entry.get("releaseDatetime") or ""
        date_match = _DATE_REGEX.search(str(date_cand))
        if date_match:
            release_date = date_match.group(1)
        else:
            title_match = _DATE_REGEX.search(item_title)
            if title_match:
                release_date = title_match.group(1)

        tile_url = _TILE_URL_TEMPLATE.format(rel_num=key)

        raw_releases.append(
            {
                "release_id": layer_identifier,
                "title": item_title,
                "release_date": release_date,
                "tile_url_template": tile_url,
                "item_id": item_id,
                "item_url": item_url,
                "metadata_layer_url": metadata_layer_url,
                "numeric_release_number": numeric_rel_num,
            }
        )

    # Sort releases chronologically descending (newest release first at index 0)
    def sort_key(item: dict) -> tuple:
        date_str = item["release_date"]
        rel_num = item["numeric_release_number"] or 0
        return (date_str, rel_num)

    sorted_raw = sorted(raw_releases, key=sort_key, reverse=True)

    sorted_releases: List[WaybackRelease] = []
    for idx, item in enumerate(sorted_raw):
        release = WaybackRelease(
            release_id=item["release_id"],
            title=item["title"],
            release_date=item["release_date"],
            tile_url_template=item["tile_url_template"],
            release_index=idx,
            item_id=item["item_id"],
            item_url=item["item_url"],
            metadata_layer_url=item["metadata_layer_url"],
            numeric_release_number=item["numeric_release_number"],
        )
        sorted_releases.append(release)

    logger.info("Parsed %d Wayback releases from configuration JSON", len(sorted_releases))

    return CapabilitiesMetadata(
        service_title="Esri Wayback World Imagery Catalog",
        capabilities_url=source_url or WAYBACK_CONFIG_URL,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        releases=sorted_releases,
    )


def fetch_and_parse_wayback_config(
    config_url: str = WAYBACK_CONFIG_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: int = DEFAULT_NETWORK_TIMEOUT_SECONDS,
) -> CapabilitiesMetadata:
    """Fetches and parses the Wayback configuration JSON in a single call.

    Args:
        config_url: Configuration URL endpoint.
        user_agent: HTTP User-Agent header string.
        timeout_seconds: Timeout in seconds.

    Returns:
        CapabilitiesMetadata containing all parsed releases.
    """
    raw_json = fetch_wayback_config_json(
        config_url=config_url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
    )
    return parse_wayback_config(raw_json, source_url=config_url)
