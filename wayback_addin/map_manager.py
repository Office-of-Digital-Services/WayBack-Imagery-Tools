"""ArcGIS Pro Map and CIM Layer Management Engine.

Interacts with the active ArcGIS Pro map via `arcpy.mp` and `arcpy.cim` to discover,
inspect, create, and dynamically update in-place the Esri Wayback historical imagery layer.
"""

from datetime import datetime
import json
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import arcpy
    HAS_ARCPY = True
except ImportError:
    HAS_ARCPY = False
    arcpy = None

from .cache import CacheManager
from .models import CapabilitiesMetadata, LocalChangeImageryRelease, WaybackRelease
from .wmts_parser import DEFAULT_WMTS_URL

logger = logging.getLogger(__name__)

# Concrete CIM type for internet server connections — ArcGIS Pro requires the
# non-abstract "CIMInternetServerConnection" rather than the base class name.
CIM_SERVER_CONNECTION_TYPE: str = "CIMInternetServerConnection"


def zoom_to_metadata_layer_id(zoom: int) -> int:
    """Maps Web Mercator zoom level (0-23) to metadata sublayer ID (0-13).

    Esri Wayback metadata MapServer services host 14 distinct sublayers (0 to 13),
    where Layer 0 corresponds to the highest resolution (zoom 23) and Layer 13
    corresponds to regional resolution (zoom 10 and lower).

    Formula: layer_id = max(0, min(13, 23 - zoom))

    Args:
        zoom: Web Mercator zoom level (0 to 23).

    Returns:
        Integer metadata layer ID between 0 and 13.
    """
    return max(0, min(13, 23 - int(zoom)))


def derive_wmts_base_url(capabilities_url: str) -> str:
    """Derives the base WMTS service URL from a full WMTSCapabilities.xml URL.

    ArcGIS Pro WMTS connections expect the base service endpoint URL
    (e.g. `https://…/MapServer/WMTS`) rather than the full capabilities
    document URL that includes the version and XML filename.

    Args:
        capabilities_url: Full capabilities URL, typically ending with
            `.../1.0.0/WMTSCapabilities.xml`.

    Returns:
        The base WMTS service URL with the trailing version path and
        capabilities filename stripped.

    Examples:
        >>> derive_wmts_base_url(
        ...     "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
        ...     "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
        ... )
        'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/WMTS'
    """
    url = capabilities_url.rstrip("/")
    # Find the "/WMTS" path segment (must be followed by "/" or be at the end of the URL).
    # We search from left to right for the *first* "/WMTS" that is a complete path segment,
    # to avoid matching "/WMTS" as part of a filename like "WMTSCapabilities.xml".
    upper_url = url.upper()
    search_start = 0
    while True:
        idx = upper_url.find("/WMTS", search_start)
        if idx == -1:
            break
        end_pos = idx + len("/WMTS")
        # Check that /WMTS is a complete path segment (followed by "/" or end-of-string)
        if end_pos >= len(url) or url[end_pos] == "/":
            return url[:end_pos]
        search_start = end_pos
    # Fallback: strip the last path component if it looks like a filename
    if url.lower().endswith(".xml"):
        return url.rsplit("/", 1)[0]
    return url


# Standard name prefix and regex for managed Wayback layers in the map
WAYBACK_LAYER_NAME_PREFIX: str = "World Imagery (Wayback"
WAYBACK_LAYER_REGEX: re.Pattern = re.compile(
    r"(?:World Imagery\s*\(\s*Wayback\s*(\d{4}-\d{2}-\d{2})\s*\)|Wayback\s+Imagery|WB_\d{4}_R\d{2})",
    re.IGNORECASE,
)
# Broader regex that also matches standalone/saved Wayback layers created by the
# "Save Current Layer" feature (e.g., "Saved: Imagery 2026-08-05") and local change layers.
# Used by list_wayback_layers() to enumerate all Wayback-related layers in a map.
WAYBACK_ANY_LAYER_REGEX: re.Pattern = re.compile(
    r"(?:World Imagery\s*\(\s*Wayback|Wayback\s+Imagery|WB_\d{4}_R\d{2}|Saved:\s*Imagery\s+\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}\s*\(\s*Wayback)",
    re.IGNORECASE,
)
DATE_EXTRACTOR_REGEX: re.Pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")
RELEASE_ID_REGEX: re.Pattern = re.compile(r"(WB_\d{4}_R\d{2})", re.IGNORECASE)


def _build_layer_description(release: WaybackRelease) -> str:
    """Builds a descriptive text for the Wayback layer including metadata service info.

    Args:
        release: The WaybackRelease to describe.

    Returns:
        A multi-line description string with release details and metadata URL.
    """
    lines = [
        f"Esri World Imagery Wayback Archive",
        f"Release: {release.release_id}",
        f"Date: {release.release_date}",
    ]
    # Include the metadata service URL if available
    metadata_url = release.metadata_service_url
    if metadata_url:
        lines.append(f"Metadata Service: {metadata_url}")
        lines.append(
            "Use ArcGIS Pro's Identify tool with the metadata feature service "
            "to query acquisition date, provider, resolution, and accuracy."
        )
    return "\n".join(lines)


def build_wayback_lyrx_json(release: WaybackRelease, capabilities_url: str = DEFAULT_WMTS_URL) -> Dict[str, Any]:
    """Constructs a valid ArcGIS Pro CIM layer JSON definition (.lyrx) for a Wayback release.

    This template allows programmatic creation of a new CIMTiledServiceLayer in maps
    where no Wayback imagery layer currently exists.

    Args:
        release: The target WaybackRelease instance.
        capabilities_url: The WMTS service capabilities endpoint URL.

    Returns:
        Dictionary representation conforming to ArcGIS Pro .lyrx JSON specification.
    """
    return {
        "type": "CIMLayerDocument",
        "version": "3.5.0",
        "build": 39506,
        "layers": [
            "CIMPATH=map/" + release.release_id.lower() + ".json"
        ],
        "layerDefinitions": [
            {
                "type": "CIMTiledServiceLayer",
                "name": release.title,
                "uRI": "CIMPATH=map/" + release.release_id.lower() + ".json",
                "sourceModifiedTime": {
                    "type": "CIMInstant"
                },
                "useSourceMetadata": True,
                "description": _build_layer_description(release),
                "expanded": True,
                "layerType": "Operational",
                "showLegends": False,
                "visibility": True,
                "displayCacheType": "Permanent",
                "maxLOD": 23,
                "minLOD": 0,
                "refreshRate": -1,
                "refreshRateUnits": "esriTimeUnitsSeconds",
                "serviceConnection": {
                    "type": "CIMWMTSServiceConnection",
                    "version": "1.0.0",
                    "description": release.title,
                    "layerName": release.release_id,
                    "style": "default",
                    "tileMatrixSet": "default028mm",
                    "imageFormat": "image/jpeg",
                    "templateUrl": release.tile_url_template,
                    "serverConnection": {
                        "type": CIM_SERVER_CONNECTION_TYPE,
                        "anonymous": True,
                        "hideUserProperty": True,
                        "url": derive_wmts_base_url(capabilities_url),
                    },
                },
            }
        ],
    }


class MapManager:
    """Manages active ArcGIS Pro map discovery, layer detection, and dynamic CIM updates."""

    def __init__(
        self,
        cache_manager: Optional[CacheManager] = None,
        project_or_path: str = "CURRENT",
    ) -> None:
        """Initializes the MapManager.

        Args:
            cache_manager: Optional CacheManager instance. If None, instantiates a default manager.
            project_or_path: ArcGIS project identifier ('CURRENT' or file path to .aprx).
        """
        self.cache_manager: CacheManager = cache_manager or CacheManager()
        self.project_or_path: str = project_or_path
        self._aprx_instance: Optional[Any] = None

    def get_project(self) -> Any:
        """Retrieves the ArcGISProject reference.

        Returns:
            arcpy.mp.ArcGISProject instance.

        Raises:
            RuntimeError: If ArcPy is not available or the project cannot be referenced.
        """
        # Return pre-set instance first (allows testing without ArcPy)
        if self._aprx_instance is not None:
            return self._aprx_instance

        if not HAS_ARCPY:
            raise RuntimeError("ArcPy is not available in the current Python environment.")

        try:
            return arcpy.mp.ArcGISProject(self.project_or_path)
        except Exception as err:
            raise RuntimeError(
                f"Failed to reference ArcGISProject ('{self.project_or_path}'): {err}"
            ) from err

    def get_target_map(self, map_name: Optional[str] = None) -> Any:
        """Resolves the target Map object from the ArcGISProject.

        Resolution order:
        1. Explicit map_name if provided and found in project.
        2. Active map view in the project (`aprx.activeMap`).
        3. First map returned by `aprx.listMaps()` if an active map view is not focused.

        Args:
            map_name: Optional name of the specific map to target.

        Returns:
            The resolved arcpy.mp.Map object.

        Raises:
            ValueError: If no map can be found or resolved in the project.
        """
        aprx = self.get_project()

        if map_name and map_name.strip() and map_name.strip().upper() != "CURRENT":
            matching_maps = aprx.listMaps(map_name.strip())
            if matching_maps:
                return matching_maps[0]
            raise ValueError(
                f"Map '{map_name}' not found in project '{self.project_or_path}'."
            )

        # Attempt to use active map view
        active_map = getattr(aprx, "activeMap", None)
        if active_map is not None:
            return active_map

        # Fallback to first map in project
        all_maps = aprx.listMaps()
        if all_maps:
            return all_maps[0]

        raise ValueError(
            "No maps found in the current ArcGIS Pro project. Please open or create a map first."
        )

    def is_wayback_layer(self, layer: Any) -> bool:
        """Determines whether an arcpy.mp.Layer object is a managed Wayback imagery layer.

        Inspects layer name patterns and underlying CIM service connection properties.

        Args:
            layer: An arcpy.mp.Layer instance.

        Returns:
            True if the layer is identified as a Wayback imagery layer, False otherwise.
        """
        layer_name = getattr(layer, "name", "")
        if WAYBACK_LAYER_REGEX.search(layer_name):
            return True

        # Check CIM definition if available
        if hasattr(layer, "getDefinition"):
            try:
                cim_def = layer.getDefinition("V3")
                service_conn = getattr(cim_def, "serviceConnection", None)
                if service_conn is not None:
                    layer_name_attr = getattr(service_conn, "layerName", "")
                    template_url_attr = getattr(service_conn, "templateUrl", "")
                    if (
                        layer_name_attr.startswith("WB_")
                        or "wayback" in template_url_attr.lower()
                    ):
                        return True
            except Exception as err:
                logger.debug("Failed inspecting CIM definition for layer '%s': %s", layer_name, err)

        return False

    def find_wayback_layer(self, map_obj: Any) -> Optional[Any]:
        """Searches the given map for the first managed Wayback imagery layer.

        Args:
            map_obj: An arcpy.mp.Map object.

        Returns:
            The matching arcpy.mp.Layer instance, or None if no Wayback layer is present.
        """
        for layer in map_obj.listLayers():
            if self.is_wayback_layer(layer):
                return layer
        return None

    def get_current_release_from_layer(self, layer: Any) -> Optional[WaybackRelease]:
        """Detects and extracts the active WaybackRelease currently configured on a layer.

        Args:
            layer: An arcpy.mp.Layer instance.

        Returns:
            The corresponding WaybackRelease from catalog/cache, or a synthesized instance.
        """
        layer_name = getattr(layer, "name", "")
        release_id = ""
        release_date = ""

        # Check CIM service connection first
        if hasattr(layer, "getDefinition"):
            try:
                cim_def = layer.getDefinition("V3")
                service_conn = getattr(cim_def, "serviceConnection", None)
                if service_conn is not None:
                    release_id = getattr(service_conn, "layerName", "")
            except Exception as err:
                logger.debug("CIM definition check failed for current release: %s", err)

        # Check name for release ID or date
        if not release_id:
            id_match = RELEASE_ID_REGEX.search(layer_name)
            if id_match:
                release_id = id_match.group(1).upper()

        date_match = DATE_EXTRACTOR_REGEX.search(layer_name)
        if date_match:
            release_date = date_match.group(1)

        # Lookup in cache catalog
        if release_id:
            rel = self.cache_manager.get_release_by_id(release_id)
            if rel is not None:
                return rel

        if release_date:
            rel = self.cache_manager.get_release_by_date(release_date)
            if rel is not None:
                return rel

        # If not in catalog, construct fallback instance
        if release_id or release_date:
            return WaybackRelease(
                release_id=release_id or "WB_UNKNOWN",
                title=layer_name,
                release_date=release_date or "",
                tile_url_template="",
                release_index=0,
            )

        return None

    def get_current_release(self, map_name: Optional[str] = None) -> Optional[WaybackRelease]:
        """Discovers the active WaybackRelease in the target map.

        Args:
            map_name: Optional map name.

        Returns:
            The active WaybackRelease, or None if no Wayback layer exists in the map.
        """
        map_obj = self.get_target_map(map_name)
        wayback_layer = self.find_wayback_layer(map_obj)
        if wayback_layer is None:
            return None
        return self.get_current_release_from_layer(wayback_layer)

    def get_wayback_layer_name(self, map_name: Optional[str] = None) -> Optional[str]:
        """Returns the display name of the managed Wayback layer in the target map.

        This is a lightweight check that reads only the layer name from the
        map's Contents pane — it does NOT inspect the CIM definition.  It is
        designed for fast deduplication checks during slider validation cycles.

        Args:
            map_name: Optional map name (None or "CURRENT" for the active map).

        Returns:
            The layer name string, or None if no Wayback layer exists.
        """
        try:
            map_obj = self.get_target_map(map_name)
        except (ValueError, RuntimeError):
            return None
        wayback_layer = self.find_wayback_layer(map_obj)
        if wayback_layer is None:
            return None
        return getattr(wayback_layer, "name", None)

    def list_map_names(self) -> List[str]:
        """Returns a list of all map names in the current ArcGIS Pro project.

        This is used to populate the "Target Map" dropdown in tool parameter
        dialogs so the user can select a specific map by name.

        Returns:
            A list of map name strings.  Returns an empty list if the
            project cannot be accessed or has no maps.
        """
        try:
            aprx = self.get_project()
        except (ValueError, RuntimeError):
            return []
        try:
            return [m.name for m in aprx.listMaps()]
        except Exception:
            return []

    def list_wayback_layers(self, map_name: Optional[str] = None) -> List[str]:
        """Returns display names of all Wayback-related layers in the target map.

        This includes both the managed adjustable layer (matching
        ``WAYBACK_LAYER_REGEX``) and standalone saved layers (matching the
        ``WAYBACK_ANY_LAYER_REGEX`` broader pattern).  It also inspects each
        layer's CIM service connection for Wayback identifiers.

        The managed (adjustable) layer, if present, is always listed first.

        Args:
            map_name: Optional map name (None or "CURRENT" for the active map).

        Returns:
            A list of layer name strings.  Empty if no Wayback layers exist or
            the map cannot be accessed.
        """
        try:
            map_obj = self.get_target_map(map_name)
        except (ValueError, RuntimeError):
            return []

        managed_layers: List[str] = []
        other_layers: List[str] = []

        for layer in map_obj.listLayers():
            layer_name = getattr(layer, "name", "")
            if not layer_name:
                continue

            # Check if this is the managed adjustable layer
            if WAYBACK_LAYER_REGEX.search(layer_name):
                managed_layers.append(layer_name)
            # Check if it matches the broader pattern (saved/standalone layers)
            elif WAYBACK_ANY_LAYER_REGEX.search(layer_name):
                other_layers.append(layer_name)
            # Also check CIM connection for layers with non-standard names
            elif self.is_wayback_layer(layer):
                other_layers.append(layer_name)

        # Return managed layers first, then saved/standalone layers
        return managed_layers + other_layers

    def apply_release_to_cim_layer(self, layer: Any, release: WaybackRelease) -> None:
        """Applies a WaybackRelease to an existing layer's CIM definition in place.

        Updates the CIMWMTSServiceConnection properties (layerName, templateUrl, style,
        imageFormat, tileMatrixSet) and modifies the layer display title.

        Args:
            layer: The arcpy.mp.Layer object to modify.
            release: The target WaybackRelease instance to apply.
        """
        if not hasattr(layer, "getDefinition") or not hasattr(layer, "setDefinition"):
            raise ValueError(f"Layer '{getattr(layer, 'name', '')}' does not support CIM definition access.")

        cim_def = layer.getDefinition("V3")
        service_conn = getattr(cim_def, "serviceConnection", None)

        if service_conn is None:
            # Create a new CIMWMTSServiceConnection if missing
            service_conn = arcpy.cim.CreateCIMObjectFromClassName("CIMWMTSServiceConnection", "V3")
            cim_def.serviceConnection = service_conn

        # Update connection attributes
        service_conn.layerName = release.release_id
        service_conn.templateUrl = release.tile_url_template
        service_conn.style = "default"
        service_conn.tileMatrixSet = "default028mm"
        service_conn.imageFormat = "image/jpeg"

        # Ensure server connection object is configured using the concrete CIM type
        server_conn = getattr(service_conn, "serverConnection", None)
        if server_conn is None:
            server_conn = arcpy.cim.CreateCIMObjectFromClassName(CIM_SERVER_CONNECTION_TYPE, "V3")
            service_conn.serverConnection = server_conn

        # Use the base WMTS service URL, not the full capabilities document URL
        server_conn.url = derive_wmts_base_url(self.cache_manager.capabilities_url)
        server_conn.anonymous = True
        server_conn.hideUserProperty = True

        # Update layer display name, title, and description with metadata info
        cim_def.name = release.title
        cim_def.description = _build_layer_description(release)

        # Apply the updated CIM definition back to the live layer
        layer.setDefinition(cim_def)

        # Update layer name attribute
        try:
            layer.name = release.title
        except Exception:
            pass

    def add_new_wayback_layer(self, map_obj: Any, release: WaybackRelease) -> Any:
        """Constructs and inserts a new Wayback imagery layer into the map.

        Generates a temporary .lyrx file from the CIM layer specification and loads it
        into the map via `map_obj.addLayer()`.

        Args:
            map_obj: Target arcpy.mp.Map instance.
            release: The WaybackRelease to initialize the layer with.

        Returns:
            The newly created arcpy.mp.Layer object.
        """
        lyrx_data = build_wayback_lyrx_json(release, self.cache_manager.capabilities_url)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lyrx",
            delete=False,
            encoding="utf-8",
        ) as tmp_file:
            json.dump(lyrx_data, tmp_file, indent=2)
            tmp_lyrx_path = tmp_file.name

        try:
            layer_file = arcpy.mp.LayerFile(tmp_lyrx_path)
            # Add to bottom of the operational layers stack / as basemap background
            map_obj.addLayer(layer_file, "AUTO_ARRANGE")
            # Discover and return the newly added layer
            new_layer = self.find_wayback_layer(map_obj)
            if new_layer is not None:
                return new_layer
            # If find_wayback_layer couldn't match, return the first layer matching title
            for l in map_obj.listLayers():
                if getattr(l, "name", "") == release.title:
                    return l
            raise RuntimeError("Layer file added but could not be resolved in the map.")
        finally:
            try:
                if os.path.exists(tmp_lyrx_path):
                    os.remove(tmp_lyrx_path)
            except Exception as err:
                logger.debug("Failed cleaning up temporary .lyrx file '%s': %s", tmp_lyrx_path, err)

    def update_or_create_layer(
        self, release: WaybackRelease, map_name: Optional[str] = None
    ) -> Any:
        """Updates the existing Wayback layer in place or creates a new layer if none exists.

        Args:
            release: The target WaybackRelease instance to set.
            map_name: Optional name of the map to target.

        Returns:
            The updated or newly created arcpy.mp.Layer object.
        """
        map_obj = self.get_target_map(map_name)
        existing_layer = self.find_wayback_layer(map_obj)

        if existing_layer is not None:
            self.apply_release_to_cim_layer(existing_layer, release)
            return existing_layer
        else:
            return self.add_new_wayback_layer(map_obj, release)

    def add_standalone_layer(
        self, release: WaybackRelease, map_name: Optional[str] = None
    ) -> Any:
        """Creates an independent standalone copy of a Wayback release layer in the map.

        The standalone layer is named with a "(Saved)" suffix and uses a name pattern
        that does NOT match WAYBACK_LAYER_REGEX, so find_wayback_layer() will not treat
        it as the adjustable/managed layer. This allows users to freeze a specific
        imagery release while continuing to use the slider on the adjustable layer.

        Args:
            release: The WaybackRelease to save as a standalone layer.
            map_name: Optional name of the map to target.

        Returns:
            The newly created standalone arcpy.mp.Layer object.

        Raises:
            RuntimeError: If the layer file cannot be created or added to the map.
        """
        map_obj = self.get_target_map(map_name)

        # Build a distinctive standalone name that won't match WAYBACK_LAYER_REGEX.
        # The regex matches "World Imagery (Wayback YYYY-MM-DD)", "Wayback Imagery",
        # and "WB_YYYY_RNN" patterns.  We use a "Saved:" prefix and avoid including
        # the raw release_id to prevent accidental regex matching.
        standalone_name = f"Saved: Imagery {release.release_date}"

        # Generate the .lyrx JSON for this release, then override the layer name
        lyrx_data = build_wayback_lyrx_json(release, self.cache_manager.capabilities_url)
        layer_def = lyrx_data["layerDefinitions"][0]
        layer_def["name"] = standalone_name
        # Build the description with full metadata service information
        desc_lines = [
            "Saved standalone Wayback imagery layer.",
            f"Release: {release.release_id}",
            f"Date: {release.release_date}",
            f"Title: {release.title}",
        ]
        metadata_url = release.metadata_service_url
        if metadata_url:
            desc_lines.append(f"Metadata Service: {metadata_url}")
            desc_lines.append(
                "Use ArcGIS Pro's Identify tool with the metadata feature service "
                "to query acquisition date, provider, resolution, and accuracy."
            )
        layer_def["description"] = "\n".join(desc_lines)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lyrx",
            delete=False,
            encoding="utf-8",
        ) as tmp_file:
            json.dump(lyrx_data, tmp_file, indent=2)
            tmp_lyrx_path = tmp_file.name

        try:
            layer_file = arcpy.mp.LayerFile(tmp_lyrx_path)
            map_obj.addLayer(layer_file, "AUTO_ARRANGE")
            # Find the newly added layer by its distinctive standalone name
            for layer in map_obj.listLayers():
                if getattr(layer, "name", "") == standalone_name:
                    return layer
            raise RuntimeError(
                f"Standalone layer '{standalone_name}' was added but could not be found in the map."
            )
        finally:
            try:
                if os.path.exists(tmp_lyrx_path):
                    os.remove(tmp_lyrx_path)
            except Exception as err:
                logger.debug("Failed cleaning up temporary .lyrx file '%s': %s", tmp_lyrx_path, err)

    def add_wayback_layer_as_separate(
        self,
        release: WaybackRelease,
        layer_name: str,
        map_name: Optional[str] = None,
    ) -> Any:
        """Creates an independent standalone Wayback layer with a custom name in the map.

        Args:
            release: The WaybackRelease to instantiate.
            layer_name: Custom display name for the new layer.
            map_name: Optional name of the target map.

        Returns:
            The newly created arcpy.mp.Layer object.

        Raises:
            RuntimeError: If layer file creation or map insertion fails.
        """
        map_obj = self.get_target_map(map_name)

        # Generate .lyrx JSON template
        lyrx_data = build_wayback_lyrx_json(release, self.cache_manager.capabilities_url)
        layer_def = lyrx_data["layerDefinitions"][0]
        layer_def["name"] = layer_name

        # Build layer description
        desc_lines = [
            f"Wayback Historical Imagery: {layer_name}",
            f"Release: {release.release_id}",
            f"Basemap Date: {release.release_date}",
            f"Title: {release.title}",
        ]
        metadata_url = release.metadata_service_url
        if metadata_url:
            desc_lines.append(f"Metadata Service: {metadata_url}")
        layer_def["description"] = "\n".join(desc_lines)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lyrx",
            delete=False,
            encoding="utf-8",
        ) as tmp_file:
            json.dump(lyrx_data, tmp_file, indent=2)
            tmp_lyrx_path = tmp_file.name

        try:
            layer_file = arcpy.mp.LayerFile(tmp_lyrx_path)
            map_obj.addLayer(layer_file, "AUTO_ARRANGE")
            # Find the newly added layer by name
            for layer in map_obj.listLayers():
                if getattr(layer, "name", "") == layer_name:
                    return layer
            raise RuntimeError(
                f"Layer '{layer_name}' was added but could not be found in the map."
            )
        finally:
            try:
                if os.path.exists(tmp_lyrx_path):
                    os.remove(tmp_lyrx_path)
            except Exception as err:
                logger.debug("Failed cleaning up temporary .lyrx file '%s': %s", tmp_lyrx_path, err)

    def add_all_local_change_layers(
        self,
        releases: List[Union[LocalChangeImageryRelease, WaybackRelease]],
        map_name: Optional[str] = None,
    ) -> List[str]:
        """Batch-adds multiple local change releases as separate standalone layers.

        Args:
            releases: List of LocalChangeImageryRelease or WaybackRelease objects.
            map_name: Optional name of the target map.

        Returns:
            List of added layer names.
        """
        added_names: List[str] = []
        for item in releases:
            if isinstance(item, LocalChangeImageryRelease):
                name = item.formatted_display_name
                rel = item.release
            elif hasattr(item, "formatted_display_name"):
                name = item.formatted_display_name
                rel = item
            else:
                rel = item
                name = getattr(item, "title", str(item))

            self.add_wayback_layer_as_separate(rel, name, map_name)
            added_names.append(name)
        return added_names

    def get_map_view_center_and_scale(
        self, map_name: Optional[str] = None
    ) -> Tuple[float, float, float]:
        """Retrieves the active or target map view's center coordinates (WGS 84) and scale.

        Args:
            map_name: Optional map name.

        Returns:
            Tuple of (longitude: float, latitude: float, scale: float).
        """
        default_lon = -121.4944
        default_lat = 38.5816
        default_scale = 24000.0

        try:
            aprx = self.get_project()
            mv = getattr(aprx, "activeView", None)
            if mv is not None and hasattr(mv, "camera"):
                camera = mv.camera
                center_x = getattr(camera, "X", default_lon)
                center_y = getattr(camera, "Y", default_lat)
                scale = getattr(camera, "scale", default_scale) or default_scale

                # Check spatial reference and project to 4326 if needed
                map_obj = getattr(mv, "map", None)
                map_sr = getattr(map_obj, "spatialReference", None) if map_obj else None
                if map_sr is not None and getattr(map_sr, "factoryCode", None) != 4326:
                    if HAS_ARCPY and arcpy is not None:
                        pt = arcpy.PointGeometry(arcpy.Point(center_x, center_y), map_sr)
                        proj = pt.projectAs(arcpy.SpatialReference(4326))
                        lon = proj.centroid.X
                        lat = proj.centroid.Y
                    else:
                        lon = center_x
                        lat = center_y
                else:
                    lon = center_x
                    lat = center_y

                return (float(lon), float(lat), float(scale))
        except Exception as exc:
            logger.debug("Failed retrieving active map view camera: %s", exc)

        return (default_lon, default_lat, default_scale)

    def step_forward(
        self, map_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[WaybackRelease]]:
        """Steps forward chronologically to the next newer historical imagery release.

        Args:
            map_name: Optional map name.

        Returns:
            A tuple of (success: bool, status_message: str, active_release: Optional[WaybackRelease]).
        """
        map_obj = self.get_target_map(map_name)
        current_release = self.get_current_release(map_name)

        if current_release is None:
            # No layer exists yet; initialize with the latest release
            latest = self.cache_manager.get_latest_release()
            if latest is None:
                return False, "No Wayback releases available in catalog.", None
            self.update_or_create_layer(latest, map_name)
            return True, f"Added initial Wayback layer set to latest release: {latest.formatted_display_name}.", latest

        # Find adjacent newer release (+1 direction)
        newer_release = self.cache_manager.get_adjacent_release(
            current_release.release_id, direction=1
        )

        if newer_release is None:
            # Already on newest release
            return (
                True,
                f"Already on the newest available Wayback release: {current_release.formatted_display_name}.",
                current_release,
            )

        self.update_or_create_layer(newer_release, map_name)
        return (
            True,
            f"Stepped forward to newer release: {newer_release.formatted_display_name}.",
            newer_release,
        )

    def step_backward(
        self, map_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[WaybackRelease]]:
        """Steps backward chronologically to the previous older historical imagery release.

        Args:
            map_name: Optional map name.

        Returns:
            A tuple of (success: bool, status_message: str, active_release: Optional[WaybackRelease]).
        """
        map_obj = self.get_target_map(map_name)
        current_release = self.get_current_release(map_name)

        if current_release is None:
            # No layer exists yet; initialize with the latest release
            latest = self.cache_manager.get_latest_release()
            if latest is None:
                return False, "No Wayback releases available in catalog.", None
            self.update_or_create_layer(latest, map_name)
            return True, f"Added initial Wayback layer set to latest release: {latest.formatted_display_name}.", latest

        # Find adjacent older release (-1 direction)
        older_release = self.cache_manager.get_adjacent_release(
            current_release.release_id, direction=-1
        )

        if older_release is None:
            # Already on oldest release
            return (
                True,
                f"Already on the oldest available Wayback release: {current_release.formatted_display_name}.",
                current_release,
            )

        self.update_or_create_layer(older_release, map_name)
        return (
            True,
            f"Stepped backward to older release: {older_release.formatted_display_name}.",
            older_release,
        )

    def set_release_by_date(
        self, date_str: str, map_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[WaybackRelease]]:
        """Switches the active Wayback layer to the release matching the specified date.

        Args:
            date_str: Target date string in 'YYYY-MM-DD' format.
            map_name: Optional map name.

        Returns:
            A tuple of (success: bool, status_message: str, active_release: Optional[WaybackRelease]).
        """
        release = self.cache_manager.get_release_by_date(date_str)
        if release is None:
            # Try parsing date from a formatted string (e.g. '2026-08-05 (WB_2026_R07)')
            date_match = DATE_EXTRACTOR_REGEX.search(date_str)
            if date_match:
                release = self.cache_manager.get_release_by_date(date_match.group(1))

        if release is None:
            return False, f"Release for date '{date_str}' not found in Wayback catalog.", None

        self.update_or_create_layer(release, map_name)
        return True, f"Set Wayback imagery layer to release: {release.formatted_display_name}.", release

    def set_release_by_id(
        self, release_id: str, map_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[WaybackRelease]]:
        """Switches the active Wayback layer to the release matching the specified release ID.

        Args:
            release_id: Release identifier (e.g., 'WB_2026_R07').
            map_name: Optional map name.

        Returns:
            A tuple of (success: bool, status_message: str, active_release: Optional[WaybackRelease]).
        """
        release = self.cache_manager.get_release_by_id(release_id)
        if release is None:
            return False, f"Release ID '{release_id}' not found in Wayback catalog.", None

        self.update_or_create_layer(release, map_name)
        return True, f"Set Wayback imagery layer to release: {release.formatted_display_name}.", release

    def jump_to_latest(
        self, map_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[WaybackRelease]]:
        """Instantly jumps the Wayback layer to the most recent historical release.

        Args:
            map_name: Optional map name.

        Returns:
            A tuple of (success: bool, status_message: str, active_release: Optional[WaybackRelease]).
        """
        latest = self.cache_manager.get_latest_release()
        if latest is None:
            return False, "No Wayback releases available in catalog.", None

        self.update_or_create_layer(latest, map_name)
        return True, f"Jumped to latest release: {latest.formatted_display_name}.", latest

    def jump_to_oldest(
        self, map_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[WaybackRelease]]:
        """Instantly jumps the Wayback layer to the baseline oldest historical release.

        Args:
            map_name: Optional map name.

        Returns:
            A tuple of (success: bool, status_message: str, active_release: Optional[WaybackRelease]).
        """
        oldest = self.cache_manager.get_oldest_release()
        if oldest is None:
            return False, "No Wayback releases available in catalog.", None

        self.update_or_create_layer(oldest, map_name)
        return True, f"Jumped to oldest release: {oldest.formatted_display_name}.", oldest

    @staticmethod
    def query_metadata(
        release: WaybackRelease,
        longitude: float,
        latitude: float,
        map_scale: Optional[float] = None,
        zoom: Optional[int] = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Queries the Wayback metadata feature service for imagery details at a point.

        Primary Approach:
        Queries the resolution-specific sublayer directly via
        `/MapServer/{layerId}/query` with point spatial intersection.
        The sublayer ID is derived from zoom / map_scale via:
            layerId = max(0, min(13, 23 - zoom))

        Fallback Approach:
        If direct sublayer query returns no records or encounters an error,
        gracefully falls back to querying the MapServer `/identify` endpoint.

        Args:
            release: The WaybackRelease whose metadata service to query.
            longitude: The longitude of the query point (WGS 84 / EPSG:4326).
            latitude: The latitude of the query point (WGS 84 / EPSG:4326).
            map_scale: Optional current map scale (e.g., 24000.0 for 1:24,000).
            zoom: Optional Web Mercator zoom level (0 to 23).
            timeout: Request timeout in seconds (default 15.0s).

        Returns:
            A dictionary with keys: ``date``, ``provider``, ``source``,
            ``description``, ``resolution``, ``accuracy``, ``nice_name``,
            ``layer_name``.
            Values are ``None`` when the field is not present in the response.

        Raises:
            ValueError: If no metadata service URL can be derived for the release.
            RuntimeError: If both direct sublayer query and identify fallback fail.
        """
        import urllib.request
        import urllib.parse
        import json as _json

        metadata_url = release.metadata_service_url
        if metadata_url is None:
            raise ValueError(
                f"Cannot derive metadata service URL for release {release.release_id}."
            )

        # Determine effective Web Mercator zoom level
        if zoom is not None:
            effective_zoom = max(0, min(int(zoom), 23))
        elif map_scale is not None and map_scale > 0:
            from .change_detector import scale_to_zoom_level

            effective_zoom = scale_to_zoom_level(map_scale)
        else:
            effective_zoom = 15  # Default ~1:18,000 scale (Layer 8)

        layer_id = zoom_to_metadata_layer_id(effective_zoom)

        def _parse_attributes(
            attrs: Dict[str, Any], layer_name_val: Optional[str] = None
        ) -> Dict[str, Any]:
            date_str = None
            src_date2 = attrs.get("SRC_DATE2")
            if src_date2:
                raw_date = src_date2
            else:
                raw_date = attrs.get("SRC_DATE")
            if raw_date is not None:
                try:
                    date_int = int(raw_date)
                    date_str = datetime(date_int)
                    date_str = date_str.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date_str = str(f"Fell back to {raw_date}")

            return {
                "date": date_str,
                "provider": attrs.get("NICE_DESC") or attrs.get("NICE_NAME"),
                "source": attrs.get("SRC_DESC"),
                "description": attrs.get("NICE_NAME"),
                "resolution": attrs.get("SRC_RES"),
                "accuracy": attrs.get("SRC_ACC"),
                "nice_name": attrs.get("NICE_NAME"),
                "layer_name": layer_name_val or attrs.get("layerName"),
            }

        # 1. Primary Approach: Direct sublayer query
        query_url = f"{metadata_url}/{layer_id}/query"
        query_params = {
            "geometry": f"{longitude},{latitude}",
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
        }
        full_query_url = f"{query_url}?{urllib.parse.urlencode(query_params)}"

        try:
            req = urllib.request.Request(
                full_query_url,
                headers={"User-Agent": "ArcGIS-Pro-Wayback-Imagery-Addin/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                query_data = _json.loads(resp.read().decode("utf-8"))

            features = query_data.get("features", [])
            if features:
                first_feat = features[0]
                attrs = first_feat.get("attributes", {})
                layer_name = query_data.get("name") or f"Layer {layer_id}"
                logger.debug(
                    "Resolved metadata via sublayer %d query for %s",
                    layer_id,
                    release.release_id,
                )
                return _parse_attributes(attrs, layer_name)
        except Exception as query_err:
            logger.debug(
                "Direct sublayer query failed on layer %d (%s). Falling back to identify endpoint.",
                layer_id,
                query_err,
            )

        # 2. Fallback Approach: MapServer /identify
        if map_scale is not None and map_scale > 0:
            degrees_per_pixel = (map_scale * 0.0254) / (96.0 * 111320.0)
            half_w = degrees_per_pixel * 300.0
            half_h = degrees_per_pixel * 275.0
        else:
            half_w = 0.005
            half_h = 0.005

        extent_xmin = max(longitude - half_w, -180.0)
        extent_ymin = max(latitude - half_h, -90.0)
        extent_xmax = min(longitude + half_w, 180.0)
        extent_ymax = min(latitude + half_h, 90.0)

        identify_url = f"{metadata_url}/identify"
        identify_params = {
            "geometry": f"{longitude},{latitude}",
            "geometryType": "esriGeometryPoint",
            "sr": "4326",
            "mapExtent": f"{extent_xmin},{extent_ymin},{extent_xmax},{extent_ymax}",
            "imageDisplay": "600,550,96",
            "tolerance": "1",
            "layers": "all",
            "returnGeometry": "false",
            "f": "json",
        }
        full_identify_url = f"{identify_url}?{urllib.parse.urlencode(identify_params)}"

        req = urllib.request.Request(
            full_identify_url,
            headers={"User-Agent": "ArcGIS-Pro-Wayback-Imagery-Addin/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            identify_data = _json.loads(resp.read().decode("utf-8"))

        results = identify_data.get("results", [])
        if not results:
            raise RuntimeError(
                f"No metadata features returned for ({longitude}, {latitude}) "
                f"on release {release.release_id}."
            )

        attrs = results[0].get("attributes", {})
        layer_name = results[0].get("layerName")
        logger.debug(
            "Resolved metadata via identify endpoint for %s", release.release_id
        )
        return _parse_attributes(attrs, layer_name)
