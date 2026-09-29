"""Hybrid Two-Tier Metadata Caching Engine for Wayback Imagery.

Provides fast in-memory caching and persistent local JSON disk caching with TTL
and bundled offline snapshot fallback to enable instantaneous ribbon button navigation
and tool execution without network delay.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import tempfile
import time
from typing import List, Optional, Union

from .config_loader import WAYBACK_CONFIG_URL, fetch_and_parse_wayback_config
from .models import CapabilitiesMetadata, WaybackRelease
from .wmts_parser import DEFAULT_WMTS_URL, WMTSParser, fetch_capabilities

logger = logging.getLogger(__name__)

# Default cache Time-To-Live: 7 days in seconds (7 * 24 * 3600 = 604,800s)
DEFAULT_CACHE_TTL_SECONDS: int = 604800

# Default subfolder name under local app data
CACHE_SUBFOLDER_NAME: str = "ArcGISPro_WaybackAddin"
CACHE_FILE_NAME: str = "wayback_capabilities_cache.json"


def get_default_cache_path() -> str:
    """Determines the standard persistent disk cache path on the user's machine.

    Prefers %LOCALAPPDATA%/ArcGISPro_WaybackAddin/wayback_capabilities_cache.json,
    falling back to ~/.arcgis_wayback_cache.json or temporary directory.

    Returns:
        Absolute filesystem path string for the cache JSON file.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        cache_dir = os.path.join(local_app_data, CACHE_SUBFOLDER_NAME)
    else:
        user_home = os.path.expanduser("~")
        cache_dir = os.path.join(user_home, f".{CACHE_SUBFOLDER_NAME}")

    try:
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, CACHE_FILE_NAME)
    except Exception:
        # Fallback to temp directory if standard user directory is read-only
        return os.path.join(tempfile.gettempdir(), CACHE_FILE_NAME)


def get_bundled_fallback_path() -> str:
    """Locates the bundled static fallback JSON metadata distributed with the package.

    Returns:
        Absolute filesystem path string to the bundled fallback capabilities JSON file.
    """
    package_dir = Path(__file__).resolve().parent
    return str(package_dir / "data" / "fallback_capabilities.json")


class CacheManager:
    """Manages hybrid in-memory, disk, and offline fallback metadata caching."""

    def __init__(
        self,
        cache_file_path: Optional[str] = None,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        capabilities_url: str = DEFAULT_WMTS_URL,
        wayback_config_url: str = WAYBACK_CONFIG_URL,
        bundled_fallback_path: Optional[str] = None,
    ) -> None:
        """Initializes the CacheManager.

        Args:
            cache_file_path: Custom filesystem path for disk cache. If None, uses default path.
            ttl_seconds: Cache validity duration in seconds (defaults to 7 days).
            capabilities_url: WMTS service endpoint URL to query when refreshing cache.
            wayback_config_url: Authoritative Wayback configuration JSON URL.
            bundled_fallback_path: Path to bundled static fallback JSON file.
        """
        self.cache_file_path: str = cache_file_path or get_default_cache_path()
        self.ttl_seconds: int = ttl_seconds
        self.capabilities_url: str = capabilities_url
        self.wayback_config_url: str = wayback_config_url
        self.bundled_fallback_path: str = bundled_fallback_path or get_bundled_fallback_path()

        # In-memory cached metadata object for instantaneous active-session retrieval
        self._in_memory_metadata: Optional[CapabilitiesMetadata] = None

        # In-memory cached tilemap change detection results keyed by (round(lon, 4), round(lat, 4), zoom)
        self._tilemap_changes_cache: dict = {}

    def is_disk_cache_valid(self) -> bool:
        """Checks whether the on-disk cache file exists and is within its TTL window.

        Returns:
            True if the disk cache exists and is not expired, False otherwise.
        """
        if not os.path.isfile(self.cache_file_path):
            return False

        try:
            mtime = os.path.getmtime(self.cache_file_path)
            age_seconds = time.time() - mtime
            return age_seconds < self.ttl_seconds
        except Exception as err:
            logger.debug("Failed checking disk cache file mtime: %s", err)
            return False

    def load_from_disk(self) -> Optional[CapabilitiesMetadata]:
        """Loads and parses metadata from the local disk cache file.

        Returns:
            CapabilitiesMetadata if valid disk cache exists, None otherwise.
        """
        if not os.path.isfile(self.cache_file_path):
            return None

        try:
            with open(self.cache_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            metadata = CapabilitiesMetadata.from_dict(data)
            if metadata.releases:
                return metadata
        except Exception as err:
            logger.warning("Error reading disk cache at '%s': %s", self.cache_file_path, err)
        return None

    def save_to_disk(self, metadata: CapabilitiesMetadata) -> bool:
        """Serializes and writes the metadata to the local disk cache file.

        Args:
            metadata: The CapabilitiesMetadata instance to persist.

        Returns:
            True if successfully written, False otherwise.
        """
        try:
            cache_dir = os.path.dirname(self.cache_file_path)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)

            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(metadata.to_dict(), f, indent=2)
            return True
        except Exception as err:
            logger.warning("Failed writing disk cache to '%s': %s", self.cache_file_path, err)
            return False

    def load_from_bundled_fallback(self) -> Optional[CapabilitiesMetadata]:
        """Loads static fallback metadata bundled with the package.

        Returns:
            CapabilitiesMetadata from bundled JSON snapshot, or None if missing/invalid.
        """
        if not os.path.isfile(self.bundled_fallback_path):
            return None

        try:
            with open(self.bundled_fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            metadata = CapabilitiesMetadata.from_dict(data)
            if metadata.releases:
                return metadata
        except Exception as err:
            logger.warning("Error reading bundled fallback JSON at '%s': %s", self.bundled_fallback_path, err)
        return None

    def get_metadata(self, force_refresh: bool = False) -> CapabilitiesMetadata:
        """Retrieves capabilities metadata using the hybrid tiered caching strategy.

        Strategy hierarchy:
        1. In-memory cache (if present and not force_refresh)
        2. Valid unexpired disk cache (if present and not force_refresh)
        3. Live network query to waybackconfig.json catalog (persists to disk & memory)
        4. Live network query fallback to WMTS capabilities XML
        5. Expired disk cache (if live queries fail)
        6. Bundled static fallback JSON (if network fails and no disk cache exists)

        Args:
            force_refresh: When True, bypasses memory and valid disk caches to query live services.

        Returns:
            CapabilitiesMetadata containing the ordered release catalog.

        Raises:
            RuntimeError: If live fetch fails and no disk cache or bundled fallback is available.
        """
        # Tier 1: In-memory cache
        if self._in_memory_metadata is not None and not force_refresh:
            return self._in_memory_metadata

        # Tier 2: Valid unexpired disk cache
        if not force_refresh and self.is_disk_cache_valid():
            disk_meta = self.load_from_disk()
            if disk_meta is not None:
                self._in_memory_metadata = disk_meta
                return disk_meta

        # Tier 3: Live network request via waybackconfig.json (Primary Catalog)
        try:
            live_meta = fetch_and_parse_wayback_config(config_url=self.wayback_config_url)
            if live_meta.releases:
                self.save_to_disk(live_meta)
                self._in_memory_metadata = live_meta
                return live_meta
        except Exception as config_err:
            logger.warning(
                "Primary Wayback configuration fetch failed (%s). Trying WMTS Capabilities fallback.",
                config_err,
            )

        # Tier 4: Live network request via WMTS Capabilities XML
        try:
            parser = WMTSParser(capabilities_url=self.capabilities_url)
            live_meta = parser.fetch_and_parse()
            if live_meta.releases:
                self.save_to_disk(live_meta)
                self._in_memory_metadata = live_meta
                return live_meta
        except Exception as network_err:
            logger.warning(
                "Live WMTS capabilities retrieval failed (%s). Attempting offline fallbacks.",
                network_err,
            )

        # Tier 5: Expired disk cache fallback
        disk_meta = self.load_from_disk()
        if disk_meta is not None:
            logger.info("Using expired local disk cache as offline fallback.")
            self._in_memory_metadata = disk_meta
            return disk_meta

        # Tier 6: Bundled fallback snapshot
        fallback_meta = self.load_from_bundled_fallback()
        if fallback_meta is not None:
            logger.info("Using bundled static snapshot as offline fallback.")
            self._in_memory_metadata = fallback_meta
            return fallback_meta

        raise RuntimeError(
            "Unable to retrieve Wayback metadata from live config, WMTS endpoint, disk cache, or bundled fallback."
        )

    def get_releases(self, force_refresh: bool = False) -> List[WaybackRelease]:
        """Returns the sorted list of all Wayback releases (newest to oldest).

        Args:
            force_refresh: When True, re-queries the remote service.

        Returns:
            List of WaybackRelease instances.
        """
        metadata = self.get_metadata(force_refresh=force_refresh)
        return metadata.releases

    def get_release_by_id(self, release_id: str) -> Optional[WaybackRelease]:
        """Finds a release matching the given release ID (e.g., 'WB_2026_R07').

        Args:
            release_id: Release identifier string.

        Returns:
            Matching WaybackRelease instance, or None if not found.
        """
        metadata = self.get_metadata()
        return metadata.get_by_id(release_id)

    def get_release_by_date(self, date_str: str) -> Optional[WaybackRelease]:
        """Finds a release matching the given ISO date string ('YYYY-MM-DD').

        Args:
            date_str: Date string in 'YYYY-MM-DD' format.

        Returns:
            Matching WaybackRelease instance, or None if not found.
        """
        metadata = self.get_metadata()
        return metadata.get_by_date(date_str)

    def get_release_by_index(self, index: int) -> Optional[WaybackRelease]:
        """Finds a release by its chronological zero-based index (0 = newest).

        Args:
            index: Zero-based integer index.

        Returns:
            Matching WaybackRelease instance, or None if out of bounds.
        """
        metadata = self.get_metadata()
        return metadata.get_by_index(index)

    def get_latest_release(self) -> Optional[WaybackRelease]:
        """Returns the newest historical release available."""
        metadata = self.get_metadata()
        return metadata.latest_release

    def get_oldest_release(self) -> Optional[WaybackRelease]:
        """Returns the oldest historical release available."""
        metadata = self.get_metadata()
        return metadata.oldest_release

    def get_adjacent_release(
        self, current_identifier: str, direction: int
    ) -> Optional[WaybackRelease]:
        """Calculates the adjacent release stepping forward (newer) or backward (older).

        Args:
            current_identifier: The current release ID (e.g., 'WB_2026_R07') or release date ('2026-08-05').
            direction: +1 to step forward (newer release, lower index),
                       -1 to step backward (older release, higher index).

        Returns:
            The adjacent WaybackRelease instance, or None if already at the boundary or current release not found.
        """
        metadata = self.get_metadata()
        current_release = metadata.get_by_id(current_identifier) or metadata.get_by_date(current_identifier)

        if current_release is None:
            return None

        current_idx = current_release.release_index

        if direction > 0:
            # Step forward towards newer imagery (smaller index)
            target_idx = current_idx - 1
        elif direction < 0:
            # Step backward towards older imagery (larger index)
            target_idx = current_idx + 1
        else:
            return current_release

        return metadata.get_by_index(target_idx)

    def get_cached_tilemap_changes(
        self, lon: float, lat: float, zoom: int
    ) -> Optional[list]:
        """Retrieves cached local change releases for a spatial tile if present.

        Args:
            lon: Longitude in degrees.
            lat: Latitude in degrees.
            zoom: Web Mercator zoom level.

        Returns:
            List of releases if cached, or None if not found in cache.
        """
        key = (round(lon, 4), round(lat, 4), zoom)
        return self._tilemap_changes_cache.get(key)

    def set_cached_tilemap_changes(
        self, lon: float, lat: float, zoom: int, releases: list
    ) -> None:
        """Caches local change releases for a spatial tile.

        Args:
            lon: Longitude in degrees.
            lat: Latitude in degrees.
            zoom: Web Mercator zoom level.
            releases: List of release objects to cache.
        """
        key = (round(lon, 4), round(lat, 4), zoom)
        self._tilemap_changes_cache[key] = releases

    def clear_cache(self) -> None:
        """Clears both in-memory cache and local disk cache file."""
        self._in_memory_metadata = None
        self._tilemap_changes_cache.clear()
        if os.path.isfile(self.cache_file_path):
            try:
                os.remove(self.cache_file_path)
            except Exception as err:
                logger.warning("Failed to delete disk cache file: %s", err)
