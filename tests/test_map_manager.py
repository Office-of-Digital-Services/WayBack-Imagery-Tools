"""Unit and mock integration tests for ArcGIS Pro Map and CIM Layer Management.
"""

import json
from typing import Any, Optional
import unittest
from unittest.mock import MagicMock, patch

from wayback_addin.cache import CacheManager
from wayback_addin.map_manager import (
    CIM_SERVER_CONNECTION_TYPE,
    MapManager,
    WAYBACK_ANY_LAYER_REGEX,
    WAYBACK_LAYER_REGEX,
    _build_layer_description,
    build_wayback_lyrx_json,
    derive_wmts_base_url,
)
from wayback_addin.models import CapabilitiesMetadata, LocalChangeImageryRelease, WaybackRelease


class MockCIMInternetServerConnection:
    """Mock object representing ArcGIS Pro CIMInternetServerConnection."""

    def __init__(self) -> None:
        self.url = ""
        self.anonymous = True
        self.hideUserProperty = True


class MockCIMWMTSServiceConnection:
    """Mock object representing ArcGIS Pro CIMWMTSServiceConnection."""

    def __init__(self) -> None:
        self.layerName = ""
        self.templateUrl = ""
        self.style = "default"
        self.tileMatrixSet = "default028mm"
        self.imageFormat = "image/jpeg"
        # Provide a concrete server connection mock so tests don't need arcpy.cim
        self.serverConnection = MockCIMInternetServerConnection()


class MockCIMLayerDefinition:
    """Mock object representing ArcGIS Pro CIMTiledServiceLayer definition."""

    def __init__(self, name: str = "", layer_name: str = "", template_url: str = "") -> None:
        self.name = name
        self.description = name
        self.serviceConnection = MockCIMWMTSServiceConnection()
        self.serviceConnection.layerName = layer_name
        self.serviceConnection.templateUrl = template_url


class MockArcPyLayer:
    """Mock object representing arcpy.mp.Layer."""

    def __init__(self, name: str, layer_name: str = "", template_url: str = "") -> None:
        self.name = name
        self._cim_def = MockCIMLayerDefinition(name, layer_name, template_url)

    def getDefinition(self, version: str = "V3") -> MockCIMLayerDefinition:
        return self._cim_def

    def setDefinition(self, cim_def: MockCIMLayerDefinition) -> None:
        self._cim_def = cim_def
        self.name = cim_def.name


class MockArcPyMap:
    """Mock object representing arcpy.mp.Map."""

    def __init__(self, name: str = "Map", layers: list = None) -> None:
        self.name = name
        self._layers = list(layers or [])
        # Track the name to use for the next added layer (set by test fixtures)
        self._next_layer_name: Optional[str] = None

    def listLayers(self) -> list:
        return list(self._layers)

    def addLayer(self, layer_file: Any, position: str = "AUTO_ARRANGE") -> None:
        # Simulate adding a layer from a layer file.
        # If _next_layer_name is set, use that name; otherwise use the default.
        layer_name = self._next_layer_name or "World Imagery (Wayback 2026-08-05)"
        new_layer = MockArcPyLayer(layer_name, "WB_2026_R07", "https://wayback/tile/26334")
        self._layers.append(new_layer)
        self._next_layer_name = None  # Reset after use


class MockArcGISProject:
    """Mock object representing arcpy.mp.ArcGISProject."""

    def __init__(self, active_map: MockArcPyMap = None, maps: list = None) -> None:
        self.activeMap = active_map
        self._maps = list(maps or ([active_map] if active_map else []))

    def listMaps(self, name_wildcard: str = None) -> list:
        if name_wildcard:
            return [m for m in self._maps if m.name == name_wildcard]
        return list(self._maps)


class TestDeriveWmtsBaseUrl(unittest.TestCase):
    """Tests for the derive_wmts_base_url helper function."""

    def test_strips_capabilities_xml_from_standard_url(self) -> None:
        """Tests stripping the version/capabilities path from a standard Wayback URL."""
        full_url = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
        )
        expected = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS"
        )
        self.assertEqual(derive_wmts_base_url(full_url), expected)

    def test_preserves_url_already_at_wmts_base(self) -> None:
        """Tests that a URL already ending at /WMTS is returned unchanged."""
        base_url = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS"
        )
        self.assertEqual(derive_wmts_base_url(base_url), base_url)

    def test_handles_trailing_slash(self) -> None:
        """Tests that a trailing slash on the capabilities URL is handled."""
        url_with_slash = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml/"
        )
        expected = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS"
        )
        self.assertEqual(derive_wmts_base_url(url_with_slash), expected)

    def test_case_insensitive_wmts_segment(self) -> None:
        """Tests that the /WMTS segment is found case-insensitively."""
        mixed_case_url = (
            "https://example.com/services/MapServer/wmts/1.0.0/WMTSCapabilities.xml"
        )
        result = derive_wmts_base_url(mixed_case_url)
        # Should preserve original casing of "wmts" segment
        self.assertTrue(result.endswith("/wmts"))

    def test_fallback_strips_xml_filename(self) -> None:
        """Tests fallback behavior when no /WMTS segment is present but URL ends in .xml."""
        xml_url = "https://example.com/some/service/capabilities.xml"
        result = derive_wmts_base_url(xml_url)
        self.assertEqual(result, "https://example.com/some/service")

    def test_returns_url_unchanged_when_no_wmts_or_xml(self) -> None:
        """Tests that a URL without /WMTS or .xml extension is returned unchanged."""
        plain_url = "https://example.com/some/service"
        self.assertEqual(derive_wmts_base_url(plain_url), plain_url)


class TestMapManager(unittest.TestCase):
    """Test suite for MapManager layer discovery, CIM updating, and navigation operations."""

    def setUp(self) -> None:
        """Sets up sample releases and mock cache manager."""
        self.releases = [
            WaybackRelease(
                release_id="WB_2026_R07",
                title="World Imagery (Wayback 2026-08-05)",
                release_date="2026-08-05",
                tile_url_template="https://wayback/tile/26334",
                release_index=0,
            ),
            WaybackRelease(
                release_id="WB_2026_R06",
                title="World Imagery (Wayback 2026-07-01)",
                release_date="2026-07-01",
                tile_url_template="https://wayback/tile/26300",
                release_index=1,
            ),
            WaybackRelease(
                release_id="WB_2014_R01",
                title="World Imagery (Wayback 2014-02-20)",
                release_date="2014-02-20",
                tile_url_template="https://wayback/tile/10",
                release_index=2,
            ),
        ]
        self.metadata = CapabilitiesMetadata(
            service_title="Esri Wayback World Imagery WMTS",
            capabilities_url="https://wayback/capabilities.xml",
            fetched_at="2026-08-21T12:00:00Z",
            releases=self.releases,
        )

        self.mock_cache = MagicMock(spec=CacheManager)
        self.mock_cache.capabilities_url = "https://wayback/capabilities.xml"
        self.mock_cache.get_metadata.return_value = self.metadata
        self.mock_cache.get_releases.return_value = self.releases
        self.mock_cache.get_latest_release.return_value = self.releases[0]
        self.mock_cache.get_oldest_release.return_value = self.releases[2]

        def mock_get_by_id(rid: str) -> Optional[WaybackRelease]:
            for r in self.releases:
                if r.release_id.upper() == rid.upper():
                    return r
            return None

        def mock_get_by_date(d: str) -> Optional[WaybackRelease]:
            for r in self.releases:
                if r.release_date == d:
                    return r
            return None

        def mock_get_adjacent(cur_id: str, direction: int) -> Optional[WaybackRelease]:
            cur = mock_get_by_id(cur_id) or mock_get_by_date(cur_id)
            if not cur:
                return None
            idx = cur.release_index - direction if direction > 0 else cur.release_index - direction
            # If direction=1 (newer), target_idx = cur.release_index - 1
            # If direction=-1 (older), target_idx = cur.release_index + 1
            target_idx = cur.release_index - 1 if direction > 0 else cur.release_index + 1
            if 0 <= target_idx < len(self.releases):
                return self.releases[target_idx]
            return None

        self.mock_cache.get_release_by_id.side_effect = mock_get_by_id
        self.mock_cache.get_release_by_date.side_effect = mock_get_by_date
        self.mock_cache.get_adjacent_release.side_effect = mock_get_adjacent

        self.manager = MapManager(cache_manager=self.mock_cache)

    def test_build_wayback_lyrx_json(self) -> None:
        """Tests .lyrx document generation for creating new layers."""
        capabilities_url = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
        )
        lyrx = build_wayback_lyrx_json(self.releases[0], capabilities_url)
        self.assertEqual(lyrx["type"], "CIMLayerDocument")
        layer_def = lyrx["layerDefinitions"][0]
        self.assertEqual(layer_def["type"], "CIMTiledServiceLayer")
        self.assertEqual(layer_def["name"], "World Imagery (Wayback 2026-08-05)")
        self.assertEqual(layer_def["serviceConnection"]["layerName"], "WB_2026_R07")
        self.assertEqual(layer_def["serviceConnection"]["templateUrl"], "https://wayback/tile/26334")

    def test_build_lyrx_uses_concrete_cim_type(self) -> None:
        """Tests that the .lyrx JSON uses the concrete CIMInternetServerConnection type,
        not the abstract base class CIMInternetServerConnectionBase."""
        capabilities_url = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
        )
        lyrx = build_wayback_lyrx_json(self.releases[0], capabilities_url)
        server_conn = lyrx["layerDefinitions"][0]["serviceConnection"]["serverConnection"]
        # Must use concrete type, not the abstract base
        self.assertEqual(server_conn["type"], "CIMInternetServerConnection")
        self.assertNotEqual(server_conn["type"], "CIMInternetServerConnectionBase")

    def test_build_lyrx_strips_capabilities_filename_from_url(self) -> None:
        """Tests that the server connection URL is the base WMTS endpoint,
        not the full WMTSCapabilities.xml URL."""
        capabilities_url = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
        )
        lyrx = build_wayback_lyrx_json(self.releases[0], capabilities_url)
        server_conn_url = lyrx["layerDefinitions"][0]["serviceConnection"]["serverConnection"]["url"]
        # URL should end with /WMTS, not contain the capabilities XML filename
        self.assertTrue(server_conn_url.endswith("/WMTS"))
        self.assertNotIn("WMTSCapabilities.xml", server_conn_url)
        self.assertNotIn("1.0.0", server_conn_url)

    def test_build_lyrx_includes_version(self) -> None:
        """Tests that the CIMWMTSServiceConnection includes version 1.0.0."""
        lyrx = build_wayback_lyrx_json(self.releases[0])
        service_conn = lyrx["layerDefinitions"][0]["serviceConnection"]
        self.assertEqual(service_conn["version"], "1.0.0")

    def test_build_lyrx_description_includes_metadata_info(self) -> None:
        """Tests that the .lyrx layer description includes metadata service information."""
        # Use a tile URL with an extractable release number
        release_with_num = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template=(
                "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
                "World_Imagery/MapServer/tile/56102/{TileMatrix}/{TileRow}/{TileCol}"
            ),
            release_index=0,
        )
        lyrx = build_wayback_lyrx_json(release_with_num)
        description = lyrx["layerDefinitions"][0]["description"]
        # Description should include release info and metadata URL
        self.assertIn("WB_2023_R11", description)
        self.assertIn("2023-12-07", description)
        self.assertIn("metadata.maptiles.arcgis.com", description)
        # URL now uses release_id-based format (year_rseq), not release number
        self.assertIn("World_Imagery_Metadata_2023_r11", description)
        self.assertIn("Identify", description)

    def test_build_layer_description_without_metadata(self) -> None:
        """Tests that the description works even without a metadata URL."""
        release_no_num = WaybackRelease(
            release_id="WB_UNKNOWN",
            title="Unknown Release",
            release_date="2020-01-01",
            tile_url_template="",
            release_index=0,
        )
        description = _build_layer_description(release_no_num)
        self.assertIn("WB_UNKNOWN", description)
        self.assertIn("2020-01-01", description)
        # Should NOT contain metadata URL since release number can't be extracted
        self.assertNotIn("metadata.maptiles.arcgis.com", description)

    def test_build_lyrx_json_structure_is_valid(self) -> None:
        """Tests that the full .lyrx JSON structure contains all required CIM fields."""
        lyrx = build_wayback_lyrx_json(self.releases[0])
        # Top-level structure
        self.assertIn("type", lyrx)
        self.assertIn("version", lyrx)
        self.assertIn("layers", lyrx)
        self.assertIn("layerDefinitions", lyrx)
        self.assertEqual(len(lyrx["layerDefinitions"]), 1)
        # Layer definition required fields
        layer_def = lyrx["layerDefinitions"][0]
        self.assertIn("serviceConnection", layer_def)
        self.assertIn("name", layer_def)
        self.assertIn("uRI", layer_def)
        # Service connection required fields
        svc_conn = layer_def["serviceConnection"]
        self.assertEqual(svc_conn["type"], "CIMWMTSServiceConnection")
        self.assertIn("serverConnection", svc_conn)
        self.assertIn("layerName", svc_conn)
        self.assertIn("templateUrl", svc_conn)
        self.assertIn("version", svc_conn)
        # Server connection required fields
        srv_conn = svc_conn["serverConnection"]
        self.assertEqual(srv_conn["type"], CIM_SERVER_CONNECTION_TYPE)
        self.assertIn("url", srv_conn)
        self.assertTrue(srv_conn["anonymous"])

    def test_is_wayback_layer_by_name_and_cim(self) -> None:
        """Tests layer identification logic with various names and CIM connections."""
        # Standard naming
        lyr1 = MockArcPyLayer("World Imagery (Wayback 2026-08-05)")
        self.assertTrue(self.manager.is_wayback_layer(lyr1))

        # Custom name but WB_ identifier in CIM connection
        lyr2 = MockArcPyLayer("My Historical Base Layer", layer_name="WB_2026_R06")
        self.assertTrue(self.manager.is_wayback_layer(lyr2))

        # Non-Wayback layer
        lyr3 = MockArcPyLayer("Highways and Streets", layer_name="Streets_Layer")
        self.assertFalse(self.manager.is_wayback_layer(lyr3))

    def test_find_wayback_layer(self) -> None:
        """Tests finding the Wayback layer among multiple other map layers."""
        layer_roads = MockArcPyLayer("Roads")
        layer_wb = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06")
        layer_parcels = MockArcPyLayer("Parcels")

        mock_map = MockArcPyMap(layers=[layer_roads, layer_wb, layer_parcels])
        found = self.manager.find_wayback_layer(mock_map)

        self.assertIsNotNone(found)
        self.assertEqual(found.name, "World Imagery (Wayback 2026-07-01)")

    def test_get_wayback_layer_name(self) -> None:
        """Tests getting the current Wayback layer name from the map."""
        layer_wb = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06")
        mock_map = MockArcPyMap(layers=[layer_wb])
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        name = self.manager.get_wayback_layer_name()
        self.assertEqual(name, "World Imagery (Wayback 2026-07-01)")

    def test_get_wayback_layer_name_no_layer(self) -> None:
        """Tests that get_wayback_layer_name returns None when no Wayback layer exists."""
        mock_map = MockArcPyMap(layers=[MockArcPyLayer("Roads")])
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        name = self.manager.get_wayback_layer_name()
        self.assertIsNone(name)

    def test_get_wayback_layer_name_no_project(self) -> None:
        """Tests that get_wayback_layer_name returns None gracefully when no project exists."""
        self.manager._aprx_instance = None
        name = self.manager.get_wayback_layer_name()
        self.assertIsNone(name)

    def test_get_current_release_from_layer(self) -> None:
        """Tests extracting the current WaybackRelease from layer attributes."""
        layer = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06")
        rel = self.manager.get_current_release_from_layer(layer)
        self.assertIsNotNone(rel)
        self.assertEqual(rel.release_id, "WB_2026_R06")
        self.assertEqual(rel.release_date, "2026-07-01")

    def test_apply_release_to_cim_layer(self) -> None:
        """Tests in-place CIM layer modification."""
        layer = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06", "https://wayback/tile/26300")
        target_release = self.releases[0]  # WB_2026_R07 (2026-08-05)

        self.manager.apply_release_to_cim_layer(layer, target_release)

        self.assertEqual(layer.name, "World Imagery (Wayback 2026-08-05)")
        cim_def = layer.getDefinition("V3")
        self.assertEqual(cim_def.serviceConnection.layerName, "WB_2026_R07")
        self.assertEqual(cim_def.serviceConnection.templateUrl, "https://wayback/tile/26334")
        # Server connection URL should be derived (base WMTS URL, not the full capabilities URL)
        server_conn = cim_def.serviceConnection.serverConnection
        self.assertIsNotNone(server_conn)
        self.assertEqual(
            server_conn.url,
            derive_wmts_base_url(self.mock_cache.capabilities_url),
        )

    def test_navigation_step_forward(self) -> None:
        """Tests stepping forward (newer release) in the map."""
        layer = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06", "https://wayback/tile/26300")
        mock_map = MockArcPyMap(layers=[layer])
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Step forward from Index 1 (WB_2026_R06) -> Index 0 (WB_2026_R07)
        success, message, new_rel = self.manager.step_forward()
        self.assertTrue(success)
        self.assertIsNotNone(new_rel)
        self.assertEqual(new_rel.release_id, "WB_2026_R07")
        self.assertEqual(layer.name, "World Imagery (Wayback 2026-08-05)")

        # Step forward again from newest (Index 0) -> should inform at boundary
        success, message, boundary_rel = self.manager.step_forward()
        self.assertTrue(success)
        self.assertIn("Already on the newest", message)
        self.assertEqual(boundary_rel.release_id, "WB_2026_R07")

    def test_navigation_step_backward(self) -> None:
        """Tests stepping backward (older release) in the map."""
        layer = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06", "https://wayback/tile/26300")
        mock_map = MockArcPyMap(layers=[layer])
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Step backward from Index 1 (WB_2026_R06) -> Index 2 (WB_2014_R01)
        success, message, older_rel = self.manager.step_backward()
        self.assertTrue(success)
        self.assertIsNotNone(older_rel)
        self.assertEqual(older_rel.release_id, "WB_2014_R01")
        self.assertEqual(layer.name, "World Imagery (Wayback 2014-02-20)")

        # Step backward again from oldest (Index 2) -> should inform at boundary
        success, message, boundary_rel = self.manager.step_backward()
        self.assertTrue(success)
        self.assertIn("Already on the oldest", message)
        self.assertEqual(boundary_rel.release_id, "WB_2014_R01")

    def test_jump_to_latest_and_oldest(self) -> None:
        """Tests instant jumping to latest and oldest releases."""
        layer = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06", "https://wayback/tile/26300")
        mock_map = MockArcPyMap(layers=[layer])
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Jump to oldest
        success, msg, oldest_rel = self.manager.jump_to_oldest()
        self.assertTrue(success)
        self.assertEqual(oldest_rel.release_id, "WB_2014_R01")
        self.assertEqual(layer.name, "World Imagery (Wayback 2014-02-20)")

        # Jump to latest
        success, msg, latest_rel = self.manager.jump_to_latest()
        self.assertTrue(success)
        self.assertEqual(latest_rel.release_id, "WB_2026_R07")
        self.assertEqual(layer.name, "World Imagery (Wayback 2026-08-05)")

    def test_set_release_by_date_and_id(self) -> None:
        """Tests direct selection by date string or release identifier."""
        layer = MockArcPyLayer("World Imagery (Wayback 2026-07-01)", "WB_2026_R06", "https://wayback/tile/26300")
        mock_map = MockArcPyMap(layers=[layer])
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Set by date
        success, msg, rel = self.manager.set_release_by_date("2014-02-20")
        self.assertTrue(success)
        self.assertEqual(rel.release_id, "WB_2014_R01")

        # Set by formatted dropdown string
        success, msg, rel2 = self.manager.set_release_by_date("2026-08-05 (WB_2026_R07)")
        self.assertTrue(success)
        self.assertEqual(rel2.release_id, "WB_2026_R07")

        # Set by invalid date
        success, msg, rel_none = self.manager.set_release_by_date("1999-01-01")
        self.assertFalse(success)
        self.assertIsNone(rel_none)

        # Set by ID
        success, msg, rel_id = self.manager.set_release_by_id("WB_2026_R06")
        self.assertTrue(success)
        self.assertEqual(rel_id.release_date, "2026-07-01")

    def test_target_map_resolution_errors(self) -> None:
        """Tests that missing maps or invalid map names raise ValueError."""
        # Empty project (no maps)
        empty_project = MockArcGISProject(active_map=None, maps=[])
        self.manager._aprx_instance = empty_project

        with self.assertRaises(ValueError):
            self.manager.get_target_map()

        # Non-existent named map
        mock_map = MockArcPyMap("MainMap")
        project_with_map = MockArcGISProject(active_map=mock_map, maps=[mock_map])
        self.manager._aprx_instance = project_with_map

        with self.assertRaises(ValueError):
            self.manager.get_target_map("NonExistentMap")


class TestStandaloneLayer(unittest.TestCase):
    """Tests for the add_standalone_layer() method and standalone layer naming."""

    def setUp(self) -> None:
        """Sets up sample releases and mock cache manager."""
        self.release = WaybackRelease(
            release_id="WB_2026_R07",
            title="World Imagery (Wayback 2026-08-05)",
            release_date="2026-08-05",
            tile_url_template="https://wayback/tile/26334",
            release_index=0,
        )
        self.mock_cache = MagicMock(spec=CacheManager)
        self.mock_cache.capabilities_url = (
            "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
            "World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml"
        )
        self.manager = MapManager(cache_manager=self.mock_cache)

    def test_standalone_name_does_not_match_wayback_regex(self) -> None:
        """Tests that the standalone layer name pattern does NOT match WAYBACK_LAYER_REGEX.

        This is critical: find_wayback_layer() must not treat saved standalone layers
        as the adjustable/managed layer.
        """
        standalone_name = f"Saved: Imagery {self.release.release_date}"
        # The name should NOT match the managed layer regex
        self.assertIsNone(WAYBACK_LAYER_REGEX.search(standalone_name))

    def test_standalone_name_format(self) -> None:
        """Tests that the standalone layer name follows the expected format."""
        standalone_name = f"Saved: Imagery {self.release.release_date}"
        self.assertEqual(standalone_name, "Saved: Imagery 2026-08-05")

    @patch("wayback_addin.map_manager.arcpy")
    def test_add_standalone_layer_creates_layer(self, mock_arcpy: MagicMock) -> None:
        """Tests that add_standalone_layer creates a new layer in the map."""
        expected_name = f"Saved: Imagery {self.release.release_date}"

        # Set up mock map that will add a layer with the standalone name
        mock_map = MockArcPyMap()
        mock_map._next_layer_name = expected_name
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Mock arcpy.mp.LayerFile to return a mock layer file
        mock_layer_file = MagicMock()
        mock_arcpy.mp.LayerFile.return_value = mock_layer_file

        result_layer = self.manager.add_standalone_layer(self.release)

        # Verify the layer was created with the correct standalone name
        self.assertEqual(result_layer.name, expected_name)
        # Verify the layer was added to the map
        self.assertEqual(len(mock_map.listLayers()), 1)
        # Verify arcpy.mp.LayerFile was called (layer file was created)
        mock_arcpy.mp.LayerFile.assert_called_once()

    @patch("wayback_addin.map_manager.arcpy")
    def test_add_standalone_layer_independent_of_adjustable(self, mock_arcpy: MagicMock) -> None:
        """Tests that the standalone layer is independent of the adjustable layer.

        Both should coexist in the map, and find_wayback_layer should only find
        the adjustable one.
        """
        # Start with an existing adjustable layer
        adjustable_layer = MockArcPyLayer(
            "World Imagery (Wayback 2026-08-05)", "WB_2026_R07", "https://wayback/tile/26334"
        )
        standalone_name = f"Saved: Imagery {self.release.release_date}"
        mock_map = MockArcPyMap(layers=[adjustable_layer])
        mock_map._next_layer_name = standalone_name
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        mock_layer_file = MagicMock()
        mock_arcpy.mp.LayerFile.return_value = mock_layer_file

        # Add standalone layer
        standalone_layer = self.manager.add_standalone_layer(self.release)

        # Map should have 2 layers
        self.assertEqual(len(mock_map.listLayers()), 2)

        # find_wayback_layer should return the adjustable layer, NOT the standalone
        found = self.manager.find_wayback_layer(mock_map)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "World Imagery (Wayback 2026-08-05)")
        self.assertNotEqual(found.name, standalone_name)

    @patch("wayback_addin.map_manager.arcpy")
    def test_add_multiple_standalone_layers(self, mock_arcpy: MagicMock) -> None:
        """Tests that multiple standalone layers can be created for different releases."""
        mock_layer_file = MagicMock()
        mock_arcpy.mp.LayerFile.return_value = mock_layer_file

        release_1 = self.release
        release_2 = WaybackRelease(
            release_id="WB_2026_R06",
            title="World Imagery (Wayback 2026-07-01)",
            release_date="2026-07-01",
            tile_url_template="https://wayback/tile/26300",
            release_index=1,
        )

        mock_map = MockArcPyMap()
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Add first standalone
        standalone_name_1 = f"Saved: Imagery {release_1.release_date}"
        mock_map._next_layer_name = standalone_name_1
        layer_1 = self.manager.add_standalone_layer(release_1)

        # Add second standalone
        standalone_name_2 = f"Saved: Imagery {release_2.release_date}"
        mock_map._next_layer_name = standalone_name_2
        layer_2 = self.manager.add_standalone_layer(release_2)

        # Both should be in the map
        self.assertEqual(len(mock_map.listLayers()), 2)
        layer_names = [l.name for l in mock_map.listLayers()]
        self.assertIn(standalone_name_1, layer_names)
        self.assertIn(standalone_name_2, layer_names)


class TestWaybackAnyLayerRegex(unittest.TestCase):
    """Tests for the WAYBACK_ANY_LAYER_REGEX which matches both managed and saved layers."""

    def test_matches_managed_layer_name(self) -> None:
        """Tests that the broader regex matches standard managed layer names."""
        self.assertIsNotNone(WAYBACK_ANY_LAYER_REGEX.search("World Imagery (Wayback 2026-08-05)"))

    def test_matches_saved_layer_name(self) -> None:
        """Tests that the broader regex matches saved/standalone layer names."""
        self.assertIsNotNone(WAYBACK_ANY_LAYER_REGEX.search("Saved: Imagery 2026-08-05"))

    def test_matches_wayback_imagery(self) -> None:
        """Tests that the broader regex matches 'Wayback Imagery' pattern."""
        self.assertIsNotNone(WAYBACK_ANY_LAYER_REGEX.search("Wayback Imagery"))

    def test_matches_release_id_pattern(self) -> None:
        """Tests that the broader regex matches WB_YYYY_RNN patterns."""
        self.assertIsNotNone(WAYBACK_ANY_LAYER_REGEX.search("WB_2026_R07"))

    def test_does_not_match_unrelated(self) -> None:
        """Tests that the broader regex does not match unrelated layer names."""
        self.assertIsNone(WAYBACK_ANY_LAYER_REGEX.search("World Topographic Map"))
        self.assertIsNone(WAYBACK_ANY_LAYER_REGEX.search("US Census Data"))

    def test_saved_does_not_match_managed_regex(self) -> None:
        """Verifies that saved layer names do NOT match the managed-only regex."""
        self.assertIsNone(WAYBACK_LAYER_REGEX.search("Saved: Imagery 2026-08-05"))


class TestListMapNames(unittest.TestCase):
    """Tests for MapManager.list_map_names()."""

    def setUp(self) -> None:
        """Creates a MapManager with mock project containing multiple maps."""
        self.cache_manager = CacheManager()
        self.map_1 = MockArcPyMap(name="Map")
        self.map_2 = MockArcPyMap(name="Analysis Map")
        self.map_3 = MockArcPyMap(name="Layout Map")
        self.project = MockArcGISProject(
            active_map=self.map_1,
            maps=[self.map_1, self.map_2, self.map_3],
        )
        self.manager = MapManager(cache_manager=self.cache_manager)
        # Use _aprx_instance so that get_project() returns the mock directly
        self.manager._aprx_instance = self.project

    def test_returns_all_map_names(self) -> None:
        """Tests that list_map_names returns all map names in the project."""
        names = self.manager.list_map_names()
        self.assertEqual(names, ["Map", "Analysis Map", "Layout Map"])

    def test_returns_empty_when_no_maps(self) -> None:
        """Tests that list_map_names returns empty list when project has no maps."""
        empty_project = MockArcGISProject(active_map=None, maps=[])
        self.manager._aprx_instance = empty_project
        names = self.manager.list_map_names()
        self.assertEqual(names, [])

    def test_returns_empty_on_project_error(self) -> None:
        """Tests graceful handling when project cannot be accessed."""
        self.manager._aprx_instance = None
        # get_project will raise because _aprx_instance is None and HAS_ARCPY is False
        with patch.object(self.manager, "get_project", side_effect=RuntimeError("No project")):
            names = self.manager.list_map_names()
            self.assertEqual(names, [])


class TestListWaybackLayers(unittest.TestCase):
    """Tests for MapManager.list_wayback_layers()."""

    def setUp(self) -> None:
        """Creates a MapManager with mock map containing various layers."""
        self.cache_manager = CacheManager()
        self.manager = MapManager(cache_manager=self.cache_manager)

    def test_returns_managed_layer(self) -> None:
        """Tests that list_wayback_layers returns the managed adjustable layer."""
        managed = MockArcPyLayer("World Imagery (Wayback 2026-08-05)", "WB_2026_R07")
        unrelated = MockArcPyLayer("World Topographic Map")
        mock_map = MockArcPyMap(name="Map", layers=[unrelated, managed])
        project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = project

        result = self.manager.list_wayback_layers()
        self.assertEqual(result, ["World Imagery (Wayback 2026-08-05)"])

    def test_returns_managed_then_saved_layers(self) -> None:
        """Tests that managed layers appear before saved layers."""
        managed = MockArcPyLayer("World Imagery (Wayback 2026-08-05)", "WB_2026_R07")
        saved_1 = MockArcPyLayer("Saved: Imagery 2026-01-15")
        saved_2 = MockArcPyLayer("Saved: Imagery 2025-06-30")
        unrelated = MockArcPyLayer("OpenStreetMap")
        mock_map = MockArcPyMap(
            name="Map",
            layers=[saved_1, unrelated, managed, saved_2],
        )
        project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = project

        result = self.manager.list_wayback_layers()
        # Managed layer should be first, then saved layers in map order
        self.assertEqual(result[0], "World Imagery (Wayback 2026-08-05)")
        self.assertIn("Saved: Imagery 2026-01-15", result)
        self.assertIn("Saved: Imagery 2025-06-30", result)
        self.assertNotIn("OpenStreetMap", result)

    def test_returns_empty_when_no_wayback_layers(self) -> None:
        """Tests that an empty list is returned when no Wayback layers exist."""
        unrelated = MockArcPyLayer("World Topographic Map")
        mock_map = MockArcPyMap(name="Map", layers=[unrelated])
        project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = project

        result = self.manager.list_wayback_layers()
        self.assertEqual(result, [])

    def test_returns_empty_on_access_error(self) -> None:
        """Tests graceful handling when map cannot be accessed."""
        self.manager._aprx_instance = None
        with patch.object(
            self.manager, "get_target_map", side_effect=RuntimeError("No map")
        ):
            result = self.manager.list_wayback_layers()
            self.assertEqual(result, [])

    def test_excludes_layers_with_empty_names(self) -> None:
        """Tests that layers with empty names are excluded."""
        empty_name = MockArcPyLayer("")
        managed = MockArcPyLayer("World Imagery (Wayback 2026-08-05)", "WB_2026_R07")
        mock_map = MockArcPyMap(name="Map", layers=[empty_name, managed])
        project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = project

        result = self.manager.list_wayback_layers()
        self.assertEqual(result, ["World Imagery (Wayback 2026-08-05)"])


class TestQueryMetadata(unittest.TestCase):
    """Test suite for the MapManager.query_metadata static method.

    The method now uses the MapServer ``identify`` REST endpoint (not ``query``
    on layer 0) so that the correct resolution-specific sublayer is
    automatically selected based on the map extent and display parameters.
    """

    def test_query_metadata_raises_on_invalid_release(self) -> None:
        """Tests that query_metadata raises ValueError for releases without a metadata URL."""
        release = WaybackRelease(
            release_id="WB_UNKNOWN",
            title="Unknown",
            release_date="2020-01-01",
            tile_url_template="",
            release_index=0,
        )
        with self.assertRaises(ValueError):
            MapManager.query_metadata(release, -117.0, 34.0)

    @patch("urllib.request.urlopen")
    def test_query_metadata_parses_identify_response_with_src_date2(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Tests that query_metadata correctly parses an identify response with SRC_DATE2."""
        import json

        # Simulate an identify endpoint response with the richer field set
        response_data = {
            "results": [
                {
                    "layerId": 6,
                    "layerName": "1.2m Resolution Metadata",
                    "attributes": {
                        "SRC_DATE": 20220412,
                        "SRC_DATE2": "04/12/2022",
                        "SRC_RES": 0.46,
                        "SRC_ACC": 5.0,
                        "SRC_DESC": "GE01",
                        "NICE_NAME": "Vivid Advanced",
                        "NICE_DESC": "Maxar",
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )
        result = MapManager.query_metadata(release, -117.1825, 34.0556)

        # SRC_DATE2 should be preferred over SRC_DATE
        self.assertEqual(result["date"], "04/12/2022")
        # NICE_DESC is the provider; NICE_NAME is the description
        self.assertEqual(result["provider"], "Maxar")
        self.assertEqual(result["source"], "GE01")
        self.assertEqual(result["description"], "Vivid Advanced")
        self.assertEqual(result["resolution"], 0.46)
        self.assertEqual(result["accuracy"], 5.0)
        self.assertEqual(result["layer_name"], "1.2m Resolution Metadata")

    @patch("urllib.request.urlopen")
    def test_query_metadata_parses_src_date_integer_format(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Tests SRC_DATE parsing when SRC_DATE2 is not available.

        SRC_DATE is an integer in YYYYMMDD format (e.g., 20220412), NOT an
        epoch timestamp.  The method should parse it as a date string.
        """
        import json

        response_data = {
            "results": [
                {
                    "layerId": 8,
                    "layerName": "4.8m Resolution Metadata",
                    "attributes": {
                        "SRC_DATE": 20210315,
                        "SRC_RES": 0.5,
                        "SRC_ACC": 5.0,
                        "SRC_DESC": "WV02",
                        "NICE_NAME": "Vivid",
                        "NICE_DESC": "Maxar",
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )
        result = MapManager.query_metadata(release, -121.5, 38.5)

        # SRC_DATE 20210315 should be parsed as "2021-03-15"
        self.assertEqual(result["date"], "2021-03-15")

    @patch("urllib.request.urlopen")
    def test_query_metadata_handles_null_src_date(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Tests that query_metadata handles null SRC_DATE gracefully."""
        import json

        response_data = {
            "results": [
                {
                    "layerId": 13,
                    "layerName": "150m Resolution Metadata",
                    "attributes": {
                        "SRC_DATE": None,
                        "SRC_RES": 15.0,
                        "SRC_ACC": 12.0,
                        "SRC_DESC": "TerraColor NextGen",
                        "NICE_NAME": "TerraColor NextGen",
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )
        result = MapManager.query_metadata(release, -121.5, 38.5)

        # With no SRC_DATE or SRC_DATE2, date should be None
        self.assertIsNone(result["date"])
        self.assertEqual(result["resolution"], 15.0)

    @patch("urllib.request.urlopen")
    def test_query_metadata_direct_sublayer_query_success(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Tests that query_metadata uses direct sublayer query as primary approach."""
        import json

        response_data = {
            "name": "30cm Resolution Metadata",
            "features": [
                {
                    "attributes": {
                        "SRC_DATE": 20230615,
                        "SRC_DATE2": "06/15/2023",
                        "NICE_DESC": "Maxar",
                        "NICE_NAME": "WorldView-3",
                        "SRC_RES": 0.3,
                        "SRC_ACC": 3.0,
                    }
                }
            ],
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )

        # Zoom 19 -> layer_id = 23 - 19 = 4
        result = MapManager.query_metadata(
            release, -122.4194, 37.7749, zoom=19
        )

        self.assertEqual(result["date"], "06/15/2023")
        self.assertEqual(result["provider"], "Maxar")
        self.assertEqual(result["resolution"], 0.3)
        self.assertEqual(result["accuracy"], 3.0)

        # Verify the primary request was directed to /4/query
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        url = request.full_url
        self.assertIn("/4/query", url)
        self.assertIn("spatialRel=esriSpatialRelIntersects", url)

    def test_zoom_to_metadata_layer_id(self) -> None:
        """Tests zoom level to metadata layer ID mapping formula."""
        from wayback_addin.map_manager import zoom_to_metadata_layer_id

        self.assertEqual(zoom_to_metadata_layer_id(23), 0)
        self.assertEqual(zoom_to_metadata_layer_id(20), 3)
        self.assertEqual(zoom_to_metadata_layer_id(19), 4)
        self.assertEqual(zoom_to_metadata_layer_id(15), 8)
        self.assertEqual(zoom_to_metadata_layer_id(10), 13)
        self.assertEqual(zoom_to_metadata_layer_id(5), 13)
        self.assertEqual(zoom_to_metadata_layer_id(25), 0)

    @patch("urllib.request.urlopen")
    def test_query_metadata_raises_on_empty_results(self, mock_urlopen: MagicMock) -> None:
        """Tests that query_metadata raises RuntimeError when both query and identify return no results."""
        import json

        # Both endpoints return empty responses
        response_data = {"features": [], "results": []}
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )
        with self.assertRaises(RuntimeError):
            MapManager.query_metadata(release, -117.0, 34.0)

    @patch("urllib.request.urlopen")
    def test_query_metadata_builds_identify_url(self, mock_urlopen: MagicMock) -> None:
        """Tests that query_metadata builds the correct identify endpoint URL."""
        import json

        response_data = {
            "results": [
                {
                    "layerId": 8,
                    "layerName": "4.8m Resolution Metadata",
                    "attributes": {},
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2026_R07",
            title="World Imagery (Wayback 2026-08-05)",
            release_date="2026-08-05",
            tile_url_template="",
            release_index=0,
        )
        MapManager.query_metadata(release, -122.4194, 37.7749)

        # Verify the URL uses the identify endpoint (not query on a specific layer)
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        url = request.full_url
        self.assertIn("World_Imagery_Metadata_2026_r07", url)
        self.assertIn("/identify", url)
        self.assertNotIn("/0/query", url)
        self.assertIn("-122.4194", url)
        self.assertIn("37.7749", url)
        self.assertIn("mapExtent=", url)
        self.assertIn("imageDisplay=", url)
        self.assertIn("layers=all", url)
        self.assertIn("f=json", url)

    @patch("urllib.request.urlopen")
    def test_query_metadata_with_map_scale(self, mock_urlopen: MagicMock) -> None:
        """Tests that providing map_scale affects the extent calculation."""
        import json

        response_data = {
            "results": [
                {
                    "layerId": 4,
                    "layerName": "30cm Resolution Metadata",
                    "attributes": {
                        "SRC_DATE2": "06/15/2023",
                        "NICE_DESC": "Maxar",
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )

        # Call with a specific map scale (1:1000 — very zoomed in)
        result = MapManager.query_metadata(
            release, -117.0, 34.0, map_scale=1000.0
        )

        # The result should still parse correctly
        self.assertEqual(result["date"], "06/15/2023")
        self.assertEqual(result["provider"], "Maxar")

        # Verify the URL has a tight extent (at scale 1:1000 the extent should be very small)
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        url = request.full_url
        self.assertIn("mapExtent=", url)

    @patch("urllib.request.urlopen")
    def test_query_metadata_falls_back_to_identify_on_query_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Tests that query_metadata falls back to identify if direct sublayer query raises an error."""
        import json
        import urllib.error

        identify_data = {
            "results": [
                {
                    "layerId": 8,
                    "layerName": "4.8m Resolution Metadata",
                    "attributes": {
                        "SRC_DATE2": "08/05/2026",
                        "NICE_DESC": "Airbus",
                        "SRC_RES": 4.8,
                    },
                }
            ]
        }
        mock_identify_resp = MagicMock()
        mock_identify_resp.read.return_value = json.dumps(identify_data).encode("utf-8")
        mock_identify_resp.__enter__ = MagicMock(return_value=mock_identify_resp)
        mock_identify_resp.__exit__ = MagicMock(return_value=False)

        # First call (direct query) raises URLError; second call (identify) succeeds
        mock_urlopen.side_effect = [
            urllib.error.HTTPError("http://fake", 400, "Bad Request", {}, None),
            mock_identify_resp,
        ]

        release = WaybackRelease(
            release_id="WB_2026_R07",
            title="World Imagery (Wayback 2026-08-05)",
            release_date="2026-08-05",
            tile_url_template="",
            release_index=0,
        )
        result = MapManager.query_metadata(release, -122.4194, 37.7749)

        self.assertEqual(result["date"], "08/05/2026")
        self.assertEqual(result["provider"], "Airbus")
        self.assertEqual(result["resolution"], 4.8)

    @patch("urllib.request.urlopen")
    def test_query_metadata_provider_falls_back_to_nice_name(
        self, mock_urlopen: MagicMock
    ) -> None:
        """Tests that provider falls back to NICE_NAME when NICE_DESC is absent."""
        import json

        response_data = {
            "results": [
                {
                    "layerId": 13,
                    "layerName": "150m Resolution Metadata",
                    "attributes": {
                        "NICE_NAME": "TerraColor NextGen",
                        # NICE_DESC is deliberately absent
                    },
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )
        result = MapManager.query_metadata(release, -121.0, 38.0)

        # When NICE_DESC is absent, NICE_NAME should be used as provider
        self.assertEqual(result["provider"], "TerraColor NextGen")


class TestLocalChangeLayerManager(unittest.TestCase):
    """Tests for standalone separate layer creation and viewport center extraction."""

    def setUp(self) -> None:
        """Sets up test manager, releases, and mock objects."""
        self.cache_manager = CacheManager()
        self.manager = MapManager(cache_manager=self.cache_manager)
        self.release_1 = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="https://wayback/tile/56102",
            release_index=0,
        )
        self.release_2 = WaybackRelease(
            release_id="WB_2022_R05",
            title="World Imagery (Wayback 2022-05-18)",
            release_date="2022-05-18",
            tile_url_template="https://wayback/tile/50000",
            release_index=2,
        )
        self.local_change_1 = LocalChangeImageryRelease(
            release=self.release_1,
            capture_date="2023-11-01",
            provider="Maxar",
        )
        self.local_change_2 = LocalChangeImageryRelease(
            release=self.release_2,
            capture_date="2022-04-12",
            provider="Airbus",
        )

    @patch("wayback_addin.map_manager.arcpy")
    def test_add_wayback_layer_as_separate(self, mock_arcpy: MagicMock) -> None:
        """Tests creating a separate standalone layer with a custom formatted name."""
        mock_map = MockArcPyMap()
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        custom_name = "2023-11-01 (Wayback 2023-12-07 - Maxar)"
        mock_map._next_layer_name = custom_name

        layer = self.manager.add_wayback_layer_as_separate(self.release_1, custom_name)
        self.assertEqual(layer.name, custom_name)
        self.assertEqual(len(mock_map.listLayers()), 1)

    @patch("wayback_addin.map_manager.arcpy")
    def test_add_all_local_change_layers(self, mock_arcpy: MagicMock) -> None:
        """Tests batch-adding all local change releases as separate layers."""
        mock_map = MockArcPyMap()
        mock_project = MockArcGISProject(active_map=mock_map)
        self.manager._aprx_instance = mock_project

        # Set up layer addition simulation
        added_layers = []

        def mock_add_layer(layer_file, pos="AUTO_ARRANGE"):
            # Use next name
            name = getattr(mock_map, "_next_layer_name", "Layer")
            mock_layer = MockArcPyLayer(name)
            mock_map._layers.append(mock_layer)

        mock_map.addLayer = mock_add_layer

        def side_effect_add(release, layer_name, map_name=None):
            mock_map._next_layer_name = layer_name
            mock_map.addLayer(MagicMock())
            return mock_map._layers[-1]

        with patch.object(self.manager, "add_wayback_layer_as_separate", side_effect=side_effect_add):
            names = self.manager.add_all_local_change_layers(
                [self.local_change_1, self.local_change_2]
            )

        self.assertEqual(len(names), 2)
        self.assertIn("2023-11-01 (Wayback 2023-12-07 - Maxar)", names)
        self.assertIn("2022-04-12 (Wayback 2022-05-18 - Airbus)", names)

    def test_get_map_view_center_and_scale_fallback(self) -> None:
        """Tests fallback coordinates and scale when activeView is None."""
        mock_project = MockArcGISProject(active_map=None)
        mock_project.activeView = None
        self.manager._aprx_instance = mock_project

        lon, lat, scale = self.manager.get_map_view_center_and_scale()
        self.assertEqual(lon, -121.4944)
        self.assertEqual(lat, 38.5816)
        self.assertEqual(scale, 24000.0)

    def test_get_map_view_center_and_scale_from_camera(self) -> None:
        """Tests retrieving center and scale from activeView camera."""
        mock_camera = MagicMock()
        mock_camera.X = -122.4194
        mock_camera.Y = 37.7749
        mock_camera.scale = 10000.0

        mock_view = MagicMock()
        mock_view.camera = mock_camera
        mock_view.map = MagicMock()
        mock_view.map.spatialReference = MagicMock()
        mock_view.map.spatialReference.factoryCode = 4326

        mock_project = MagicMock()
        mock_project.activeView = mock_view
        self.manager._aprx_instance = mock_project

        lon, lat, scale = self.manager.get_map_view_center_and_scale()
        self.assertAlmostEqual(lon, -122.4194)
        self.assertAlmostEqual(lat, 37.7749)
        self.assertEqual(scale, 10000.0)


if __name__ == "__main__":
    unittest.main()
