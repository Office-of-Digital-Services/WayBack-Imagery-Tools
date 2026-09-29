"""Local change detection and imagery capture date resolution engine.

Implements Esri Wayback tilemap query protocol (/tilemap/{releaseNum}/{level}/{row}/{col})
and metadata resolution to identify historical releases with distinct tile content
at specific map coordinates and resolve true imagery acquisition dates.
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import urllib.request

from .cache import CacheManager
from .map_manager import MapManager
from .models import LocalChangeImageryRelease, WaybackRelease

logger = logging.getLogger(__name__)

# Standard Web Mercator ground scale at zoom level 0 (at 96 DPI screen resolution)
# Scale = 559,082,264.0287178 / 2^zoom
WEB_MERCATOR_ZOOM_0_SCALE: float = 559082264.0287178

# Base URL for the Wayback tilemap service
WAYBACK_TILEMAP_BASE_URL: str = (
    "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap"
)


def lon_to_tile_x(lon: float, zoom: int) -> int:
    """Converts a WGS 84 longitude in degrees to a Web Mercator tile X coordinate (column).

    Args:
        lon: Longitude in degrees (-180.0 to 180.0).
        zoom: Zoom level (0 to 23).

    Returns:
        Tile column index (0 to 2^zoom - 1).
    """
    n = 2 ** zoom
    # Clamp longitude to valid range
    clamped_lon = max(min(lon, 180.0), -180.0)
    tile_x = int(math.floor((clamped_lon + 180.0) / 360.0 * n))
    return max(0, min(tile_x, n - 1))


def lat_to_tile_y(lat: float, zoom: int) -> int:
    """Converts a WGS 84 latitude in degrees to a Web Mercator tile Y coordinate (row).

    Args:
        lat: Latitude in degrees (-85.05112878 to 85.05112878).
        zoom: Zoom level (0 to 23).

    Returns:
        Tile row index (0 to 2^zoom - 1).
    """
    n = 2 ** zoom
    # Clamp latitude to Web Mercator limits (~85.051129 degrees)
    clamped_lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(clamped_lat)
    # Using asinh(tan(lat)) which equals ln(tan(lat) + sec(lat))
    tile_y = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))
    return max(0, min(tile_y, n - 1))


def scale_to_zoom_level(scale: float) -> int:
    """Calculates the standard Web Mercator zoom level corresponding to a given map scale.

    Args:
        scale: Map scale representative denominator (e.g., 24000.0 for 1:24,000).

    Returns:
        Web Mercator zoom level (clamped between 0 and 23).
    """
    if scale <= 0:
        return 15  # Default local quad scale
    zoom = int(round(math.log2(WEB_MERCATOR_ZOOM_0_SCALE / scale)))
    return max(0, min(zoom, 23))


def fetch_tilemap(
    release_number: int,
    zoom: int,
    row: int,
    col: int,
    timeout: float = 8.0,
) -> Optional[Dict[str, Any]]:
    """Queries the Esri Wayback tilemap REST endpoint for a single tile.

    Endpoint pattern:
        `https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap/{releaseNum}/{level}/{row}/{col}?f=json`

    Args:
        release_number: Numeric release identifier (e.g. 56102).
        zoom: Web Mercator zoom level.
        row: Tile row index (Y).
        col: Tile column index (X).
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed JSON response dictionary, or None if the request failed.
    """
    url = f"{WAYBACK_TILEMAP_BASE_URL}/{release_number}/{zoom}/{row}/{col}?f=json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ArcGIS-Pro-Wayback-Imagery-Addin/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug("Tilemap query failed for release %s at (%s/%s/%s): %s", release_number, zoom, row, col, exc)
        return None


def get_releases_with_local_changes(
    lon: float,
    lat: float,
    zoom: int,
    releases: Optional[List[WaybackRelease]] = None,
    cache_manager: Optional[CacheManager] = None,
) -> List[WaybackRelease]:
    """Identifies historical Wayback releases that have actual imagery changes at the given location.

    Iterates backwards through Wayback releases and queries the tilemap endpoint
    to detect changes in tile size/presence, filtering out releases that share
    identical tiles with adjacent releases.

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees.
        zoom: Zoom level.
        releases: Optional pre-loaded list of WaybackRelease objects.
        cache_manager: Optional CacheManager instance.

    Returns:
        Ordered list of WaybackRelease instances (newest to oldest) that contain local changes.
    """
    mgr = cache_manager or CacheManager()

    # Check in-memory cache first
    cached = mgr.get_cached_tilemap_changes(lon, lat, zoom)
    if cached is not None:
        return cached

    if releases is None:
        releases = mgr.get_releases()

    if not releases:
        return []

    # Calculate tile coordinates
    tile_x = lon_to_tile_x(lon, zoom)
    tile_y = lat_to_tile_y(lat, zoom)

    changed_releases: List[WaybackRelease] = []
    last_tile_signature: Optional[Any] = None

    for release in releases:
        rel_num = release.release_number
        if rel_num is None:
            continue

        tilemap_data = fetch_tilemap(rel_num, zoom, tile_y, tile_x)
        if tilemap_data is None:
            continue

        data_list = tilemap_data.get("data", [])
        # If no data or tile does not exist (0 value), skip
        if not data_list:
            continue

        tile_sig = data_list[0]
        if tile_sig == 0:
            # 0 typically indicates no tile at this level/location for this release
            continue

        # Check if tile signature differs from the subsequent (newer) release
        if last_tile_signature is None or tile_sig != last_tile_signature:
            changed_releases.append(release)
            last_tile_signature = tile_sig

    # If tilemap scanning yielded no results (e.g. offline or tilemap unavailable),
    # fall back to returning the latest release to ensure the UI remains functional.
    if not changed_releases and releases:
        changed_releases = [releases[0]]

    # Store in memory cache
    mgr.set_cached_tilemap_changes(lon, lat, zoom, changed_releases)

    return changed_releases


def get_local_changes_with_metadata(
    lon: float,
    lat: float,
    scale: float = 24000.0,
    max_scale: float = 24000.0,
    releases: Optional[List[WaybackRelease]] = None,
    cache_manager: Optional[CacheManager] = None,
) -> List[LocalChangeImageryRelease]:
    """Discovers releases with local changes and resolves capture metadata for each.

    Args:
        lon: Center longitude in degrees (WGS 84).
        lat: Center latitude in degrees (WGS 84).
        scale: Current map scale denominator (e.g. 24000.0).
        max_scale: Maximum allowable scale threshold for change detection.
        releases: Optional pre-loaded list of WaybackRelease objects.
        cache_manager: Optional CacheManager instance.

    Returns:
        List of LocalChangeImageryRelease objects sorted newest to oldest.
    """
    mgr = cache_manager or CacheManager()
    zoom = scale_to_zoom_level(scale)

    # Detect releases with local changes
    changed_releases = get_releases_with_local_changes(
        lon=lon,
        lat=lat,
        zoom=zoom,
        releases=releases,
        cache_manager=mgr,
    )

    results: List[LocalChangeImageryRelease] = []
    for rel in changed_releases:
        try:
            meta = MapManager.query_metadata(
                rel, longitude=lon, latitude=lat, map_scale=scale, zoom=zoom
            )
            capture_date = meta.get("date") or rel.release_date
            provider = meta.get("provider")
            accuracy = str(meta.get("accuracy")) if meta.get("accuracy") is not None else None
            resolution = str(meta.get("resolution")) if meta.get("resolution") is not None else None
            source = meta.get("source")
        except Exception as exc:
            logger.debug(
                "Metadata identify failed for release %s: %s", rel.release_id, exc
            )
            capture_date = rel.release_date
            provider = None
            accuracy = None
            resolution = None
            source = None

        results.append(
            LocalChangeImageryRelease(
                release=rel,
                capture_date=capture_date,
                provider=provider,
                accuracy=accuracy,
                resolution=resolution,
                source=source,
            )
        )

    return results
