"""Data models representing Wayback imagery releases and service metadata.

These dataclasses represent immutable records for individual historical releases
and the aggregate metadata retrieved from the Esri Wayback WMTS Capabilities service.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Base URL pattern for the Wayback metadata feature service.
# Each Wayback release has an associated metadata MapServer at this URL.
# The path segment uses the release_id converted to the metadata naming convention:
#   WB_2023_R11 → World_Imagery_Metadata_2023_r11
METADATA_SERVICE_BASE_URL: str = (
    "https://metadata.maptiles.arcgis.com/arcgis/rest/services/"
    "World_Imagery_Metadata_{year}_r{seq}/MapServer"
)

# Regex to extract the numeric release number from the tile URL template.
# The tile URL looks like: .../MapServer/tile/{releaseNum}/{level}/{row}/{col}
_RELEASE_NUM_REGEX: re.Pattern = re.compile(r"/tile/(\d+)/?")

# Regex to extract year and release sequence from the release_id.
# e.g., WB_2023_R11 → year=2023, seq=11
_RELEASE_ID_REGEX: re.Pattern = re.compile(r"WB_(\d{4})_R(\d+)")


@dataclass(frozen=True)
class WaybackRelease:
    """Represents a single historical imagery release within the Esri Wayback catalog.

    Attributes:
        release_id: The unique identifier for the release (e.g., 'WB_2026_R07', 'WB_2014_R01').
        title: The human-readable title from the WMTS layer (e.g., 'World Imagery (Wayback 2026-08-05)').
        release_date: The ISO formatted release date string 'YYYY-MM-DD' (e.g., '2026-08-05').
        tile_url_template: The URL template for fetching raster map tiles with placeholder variables
            such as {TileMatrixSet}, {TileMatrix}, {TileRow}, and {TileCol}.
        release_index: The chronological sequence index (0 represents the most recent/latest release).
        item_id: Optional ArcGIS Online Item ID (e.g., '85050f00f4f849f8bb352eb91b5e3db7').
        item_url: Optional ArcGIS Online Item URL.
        metadata_layer_url: Optional authoritative MapServer URL for metadata queries.
        numeric_release_number: Optional integer release number (e.g., 26334).
    """

    release_id: str
    title: str
    release_date: str
    tile_url_template: str
    release_index: int = 0
    item_id: Optional[str] = None
    item_url: Optional[str] = None
    metadata_layer_url: Optional[str] = None
    numeric_release_number: Optional[int] = None

    @property
    def parsed_date(self) -> Optional[datetime]:
        """Parses the release_date string into a datetime object for date calculations.

        Returns:
            A datetime object corresponding to the release date, or None if date is empty/invalid.
        """
        if not self.release_date:
            return None
        try:
            return datetime.strptime(self.release_date, "%Y-%m-%d")
        except ValueError:
            return None

    @property
    def formatted_display_name(self) -> str:
        """Returns a formatted user-facing display label for dropdowns and lists.

        Example:
            '2026-08-05 (WB_2026_R07)'
        """
        if self.release_date:
            return f"{self.release_date} ({self.release_id})"
        return f"{self.title} ({self.release_id})"

    @property
    def release_number(self) -> Optional[int]:
        """Extracts or returns the numeric release number.

        If numeric_release_number is explicitly set, it is returned.
        Otherwise extracts from the tile URL template:
        ```.../MapServer/tile/{releaseNum}/{level}/{row}/{col}```

        Returns:
            The integer release number, or None if not available.
        """
        if self.numeric_release_number is not None:
            return self.numeric_release_number
        match = _RELEASE_NUM_REGEX.search(self.tile_url_template)
        if match:
            return int(match.group(1))
        return None

    @property
    def metadata_service_url(self) -> Optional[str]:
        """Constructs or returns the metadata feature service URL for this Wayback release.

        Each Wayback release has an associated metadata MapServer that provides
        imagery acquisition date, provider, resolution, and accuracy information
        for any point location via Identify/Query operations.

        If metadata_layer_url is explicitly configured, it is returned.
        Otherwise, the URL is derived from the release_id (e.g., WB_2026_R07)
        using the two-digit zero-padded sequence convention (e.g., World_Imagery_Metadata_2026_r07).

        Returns:
            The metadata service URL string, or None if the release_id
            doesn't match the expected WB_{year}_R{seq} format.
        """
        if self.metadata_layer_url:
            return self.metadata_layer_url

        match = _RELEASE_ID_REGEX.search(self.release_id)
        if match is None:
            return None
        year = match.group(1)
        # Maintain two-digit zero-padded sequence matching Esri's MapServer naming convention:
        # e.g., WB_2026_R07 -> r07, WB_2014_R01 -> r01, WB_2023_R11 -> r11
        seq_num = int(match.group(2))
        seq = f"{seq_num:02d}"
        return METADATA_SERVICE_BASE_URL.format(year=year, seq=seq)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the release object into a standard dictionary.

        Returns:
            A dictionary containing all release attributes suitable for JSON serialization.
        """
        result: Dict[str, Any] = {
            "release_id": self.release_id,
            "title": self.title,
            "release_date": self.release_date,
            "tile_url_template": self.tile_url_template,
            "release_index": self.release_index,
        }
        if self.item_id is not None:
            result["item_id"] = self.item_id
        if self.item_url is not None:
            result["item_url"] = self.item_url
        if self.metadata_layer_url is not None:
            result["metadata_layer_url"] = self.metadata_layer_url
        if self.numeric_release_number is not None:
            result["numeric_release_number"] = self.numeric_release_number
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WaybackRelease":
        """Instantiates a WaybackRelease object from a dictionary representation.

        Args:
            data: Dictionary containing release attributes.

        Returns:
            A new immutable WaybackRelease instance.
        """
        numeric_rel = data.get("numeric_release_number")
        return cls(
            release_id=str(data.get("release_id", "")),
            title=str(data.get("title", "")),
            release_date=str(data.get("release_date", "")),
            tile_url_template=str(data.get("tile_url_template", "")),
            release_index=int(data.get("release_index", 0)),
            item_id=data.get("item_id"),
            item_url=data.get("item_url"),
            metadata_layer_url=data.get("metadata_layer_url"),
            numeric_release_number=int(numeric_rel) if numeric_rel is not None else None,
        )


@dataclass(frozen=True)
class LocalChangeImageryRelease:
    """Represents a Wayback release with detected local changes and capture metadata.

    Attributes:
        release: The underlying WaybackRelease instance.
        capture_date: The resolved imagery acquisition date ('YYYY-MM-DD' or formatted string).
        provider: Imagery provider/vendor (e.g. 'Maxar', 'Airbus', 'USDA').
        accuracy: Ground horizontal accuracy description or distance (e.g. '1m', '3m').
        resolution: Ground sample distance / pixel resolution (e.g. '0.3m', 0.3).
        source: Additional source description or metadata.
    """

    release: WaybackRelease
    capture_date: Optional[str] = None
    provider: Optional[str] = None
    accuracy: Optional[str] = None
    resolution: Optional[str] = None
    source: Optional[str] = None

    @property
    def formatted_display_name(self) -> str:
        """Returns dropdown and layer display string formatted as:
        YYYY-MM-DD (Wayback YYYY-MM-DD - Provider)
        e.g. '2022-04-12 (Wayback 2022-05-18 - Maxar)'
        """
        cap_date = self.capture_date or "Unknown Date"
        rel_date = self.release.release_date or self.release.release_id
        prov = f" - {self.provider}" if self.provider else ""
        return f"{cap_date} (Wayback {rel_date}{prov})"

    def to_dict(self) -> Dict[str, Any]:
        """Serializes to dictionary."""
        return {
            "release": self.release.to_dict(),
            "capture_date": self.capture_date,
            "provider": self.provider,
            "accuracy": self.accuracy,
            "resolution": self.resolution,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalChangeImageryRelease":
        """Deserializes from dictionary."""
        rel_data = data.get("release", {})
        release = WaybackRelease.from_dict(rel_data) if isinstance(rel_data, dict) else rel_data
        return cls(
            release=release,
            capture_date=data.get("capture_date"),
            provider=data.get("provider"),
            accuracy=data.get("accuracy"),
            resolution=str(data.get("resolution")) if data.get("resolution") is not None else None,
            source=data.get("source"),
        )


@dataclass(frozen=True)
class CapabilitiesMetadata:
    """Represents the complete cached metadata set for the Wayback WMTS service.

    Attributes:
        service_title: Human-readable name of the WMTS service.
        capabilities_url: The endpoint URL from which the capabilities were retrieved.
        fetched_at: ISO timestamp recording when this metadata was retrieved or generated.
        releases: An ordered list of WaybackRelease objects (sorted newest to oldest).
    """

    service_title: str
    capabilities_url: str
    fetched_at: str
    releases: List[WaybackRelease] = field(default_factory=list)

    @property
    def release_count(self) -> int:
        """Returns the total number of historical releases available in this metadata."""
        return len(self.releases)

    @property
    def latest_release(self) -> Optional[WaybackRelease]:
        """Returns the most recent historical release (release_index 0), if any exist."""
        return self.releases[0] if self.releases else None

    @property
    def oldest_release(self) -> Optional[WaybackRelease]:
        """Returns the oldest baseline historical release, if any exist."""
        return self.releases[-1] if self.releases else None

    def get_by_id(self, release_id: str) -> Optional[WaybackRelease]:
        """Looks up a release by its unique identifier (e.g. 'WB_2026_R07').

        Args:
            release_id: The release identifier string.

        Returns:
            The matching WaybackRelease, or None if not found.
        """
        target_id = release_id.strip().upper()
        for release in self.releases:
            if release.release_id.upper() == target_id:
                return release
        return None

    def get_by_date(self, date_str: str) -> Optional[WaybackRelease]:
        """Looks up a release by its ISO date string 'YYYY-MM-DD'.

        Args:
            date_str: Target date string in 'YYYY-MM-DD' format.

        Returns:
            The matching WaybackRelease, or None if not found.
        """
        target_date = date_str.strip()
        for release in self.releases:
            if release.release_date == target_date:
                return release
        return None

    def get_by_index(self, index: int) -> Optional[WaybackRelease]:
        """Looks up a release by its zero-based chronological index.

        Args:
            index: Zero-based index (0 = newest release).

        Returns:
            The matching WaybackRelease, or None if index is out of bounds.
        """
        if 0 <= index < len(self.releases):
            return self.releases[index]
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the capabilities metadata into a dictionary.

        Returns:
            Dictionary suitable for JSON serialization.
        """
        return {
            "service_title": self.service_title,
            "capabilities_url": self.capabilities_url,
            "fetched_at": self.fetched_at,
            "releases": [r.to_dict() for r in self.releases],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilitiesMetadata":
        """Instantiates CapabilitiesMetadata from a serialized dictionary representation.

        Args:
            data: Dictionary representation containing service metadata and releases.

        Returns:
            A new immutable CapabilitiesMetadata instance.
        """
        raw_releases = data.get("releases", [])
        parsed_releases = [WaybackRelease.from_dict(r) for r in raw_releases]
        return cls(
            service_title=str(data.get("service_title", "Esri Wayback World Imagery WMTS")),
            capabilities_url=str(data.get("capabilities_url", "")),
            fetched_at=str(data.get("fetched_at", "")),
            releases=parsed_releases,
        )
