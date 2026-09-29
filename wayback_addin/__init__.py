"""ArcGIS Pro Wayback Imagery Add-In Package.

Provides interactive time-stepping, historical date selection, and in-place
CIM map layer manipulation for Esri Wayback World Imagery WMTS services.
"""

from .models import WaybackRelease, CapabilitiesMetadata
from .wmts_parser import WMTSParser, fetch_capabilities, parse_capabilities_xml
from .config_loader import (
    WAYBACK_CONFIG_URL,
    parse_wayback_config,
    fetch_and_parse_wayback_config,
    fetch_wayback_config_json,
)
from .cache import CacheManager
from .map_manager import MapManager, build_wayback_lyrx_json, zoom_to_metadata_layer_id
from .logger import setup_file_logger, get_logger, get_default_log_path

# Initialize centralized file logger for the package
setup_file_logger()

__all__ = [
    "WaybackRelease",
    "CapabilitiesMetadata",
    "WMTSParser",
    "fetch_capabilities",
    "parse_capabilities_xml",
    "WAYBACK_CONFIG_URL",
    "parse_wayback_config",
    "fetch_and_parse_wayback_config",
    "fetch_wayback_config_json",
    "CacheManager",
    "MapManager",
    "build_wayback_lyrx_json",
    "zoom_to_metadata_layer_id",
    "setup_file_logger",
    "get_logger",
    "get_default_log_path",
]
