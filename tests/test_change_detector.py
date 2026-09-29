"""Unit and mock integration tests for Wayback local change detection and capture date resolution.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from wayback_addin.change_detector import (
    fetch_tilemap,
    get_local_changes_with_metadata,
    get_releases_with_local_changes,
    lat_to_tile_y,
    lon_to_tile_x,
    scale_to_zoom_level,
)
from wayback_addin.models import LocalChangeImageryRelease, WaybackRelease


class TestChangeDetectorTileMath(unittest.TestCase):
    """Test suite for coordinate-to-tile conversions and scale calculations."""

    def test_lon_to_tile_x_bounds(self) -> None:
        """Tests longitude to tile column conversion at various zoom levels."""
        # Prime Meridian (0 deg lon) at zoom 0 -> tile 0
        self.assertEqual(lon_to_tile_x(0.0, 0), 0)
        # 0 deg lon at zoom 1 -> tile 1 (out of 2: 0, 1)
        self.assertEqual(lon_to_tile_x(0.0, 1), 1)
        # -180 deg lon -> tile 0
        self.assertEqual(lon_to_tile_x(-180.0, 10), 0)
        # 180 deg lon clamped -> 2^zoom - 1
        self.assertEqual(lon_to_tile_x(180.0, 10), 1023)
        # Sacramento, CA (-121.4944) at zoom 15
        x_15 = lon_to_tile_x(-121.4944, 15)
        self.assertEqual(x_15, 5325)

    def test_lat_to_tile_y_bounds(self) -> None:
        """Tests latitude to tile row conversion at various zoom levels."""
        # Equator (0 deg lat) at zoom 0 -> tile 0
        self.assertEqual(lat_to_tile_y(0.0, 0), 0)
        # Equator at zoom 1 -> tile 1
        self.assertEqual(lat_to_tile_y(0.0, 1), 1)
        # High north latitude (85.0511 deg) -> tile 0
        self.assertEqual(lat_to_tile_y(85.0511, 10), 0)
        # Sacramento, CA (38.5816) at zoom 15
        y_15 = lat_to_tile_y(38.5816, 15)
        self.assertEqual(y_15, 12572)

    def test_scale_to_zoom_level(self) -> None:
        """Tests calculating Web Mercator zoom level from scale."""
        # 1:24,000 scale should map to zoom 15
        self.assertEqual(scale_to_zoom_level(24000.0), 15)
        # 1:10,000 scale should map to zoom 16
        self.assertEqual(scale_to_zoom_level(10000.0), 16)
        # 1:50,000 scale should map to zoom 13
        self.assertEqual(scale_to_zoom_level(50000.0), 13)
        # 1:1,000 scale should map to zoom 19
        self.assertEqual(scale_to_zoom_level(1000.0), 19)
        # Zero or negative scale fallback
        self.assertEqual(scale_to_zoom_level(0.0), 15)
        self.assertEqual(scale_to_zoom_level(-100.0), 15)


class TestChangeDetectorTilemapQueries(unittest.TestCase):
    """Test suite for tilemap HTTP querying, deduplication, and change detection."""

    def setUp(self) -> None:
        """Sets up sample releases."""
        self.releases = [
            WaybackRelease(
                release_id="WB_2023_R11",
                title="World Imagery (Wayback 2023-12-07)",
                release_date="2023-12-07",
                tile_url_template="https://wayback/tile/56102/{TileMatrix}/{TileRow}/{TileCol}",
                release_index=0,
            ),
            WaybackRelease(
                release_id="WB_2023_R10",
                title="World Imagery (Wayback 2023-10-18)",
                release_date="2023-10-18",
                tile_url_template="https://wayback/tile/55000/{TileMatrix}/{TileRow}/{TileCol}",
                release_index=1,
            ),
            WaybackRelease(
                release_id="WB_2022_R05",
                title="World Imagery (Wayback 2022-05-18)",
                release_date="2022-05-18",
                tile_url_template="https://wayback/tile/50000/{TileMatrix}/{TileRow}/{TileCol}",
                release_index=2,
            ),
        ]

    @patch("urllib.request.urlopen")
    def test_fetch_tilemap_success(self, mock_urlopen: MagicMock) -> None:
        """Tests successful tilemap query and JSON parsing."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"data": [12345]}).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        data = fetch_tilemap(56102, 15, 12626, 5325)
        self.assertIsNotNone(data)
        self.assertEqual(data.get("data"), [12345])

    @patch("urllib.request.urlopen")
    def test_fetch_tilemap_failure_returns_none(self, mock_urlopen: MagicMock) -> None:
        """Tests that HTTP or network failures return None gracefully."""
        mock_urlopen.side_effect = Exception("Connection refused")
        data = fetch_tilemap(56102, 15, 12626, 5325)
        self.assertIsNone(data)

    @patch("wayback_addin.change_detector.fetch_tilemap")
    def test_get_releases_with_local_changes_deduplication(
        self, mock_fetch: MagicMock
    ) -> None:
        """Tests that releases sharing identical tile signatures are deduplicated."""
        # 2023_R11 has tile signature 100
        # 2023_R10 has tile signature 100 (no change from R11)
        # 2022_R05 has tile signature 200 (older imagery)
        def side_effect(rel_num, zoom, row, col, timeout=8.0):
            if rel_num == 56102:
                return {"data": [100]}
            elif rel_num == 55000:
                return {"data": [100]}
            elif rel_num == 50000:
                return {"data": [200]}
            return None

        mock_fetch.side_effect = side_effect

        changed = get_releases_with_local_changes(
            lon=-121.4944, lat=38.5816, zoom=15, releases=self.releases
        )

        # Should only return R11 and R05 (R10 was deduplicated because tile was unchanged)
        self.assertEqual(len(changed), 2)
        self.assertEqual(changed[0].release_id, "WB_2023_R11")
        self.assertEqual(changed[1].release_id, "WB_2022_R05")

    @patch("wayback_addin.change_detector.fetch_tilemap")
    def test_get_releases_with_local_changes_fallback_when_offline(
        self, mock_fetch: MagicMock
    ) -> None:
        """Tests that when tilemap is completely offline, latest release is returned as fallback."""
        mock_fetch.return_value = None

        changed = get_releases_with_local_changes(
            lon=-121.4944, lat=38.5816, zoom=15, releases=self.releases
        )

        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].release_id, "WB_2023_R11")

    @patch("wayback_addin.map_manager.MapManager.query_metadata")
    @patch("wayback_addin.change_detector.get_releases_with_local_changes")
    def test_get_local_changes_with_metadata(
        self, mock_changes: MagicMock, mock_meta: MagicMock
    ) -> None:
        """Tests full resolution of changed releases and metadata extraction."""
        mock_changes.return_value = [self.releases[0], self.releases[2]]

        def meta_side_effect(rel, longitude, latitude, map_scale=None, zoom=None, **kwargs):
            if rel.release_id == "WB_2023_R11":
                return {
                    "date": "2023-11-01",
                    "provider": "Maxar",
                    "accuracy": "1m",
                    "resolution": "0.3m",
                    "source": "WorldView-3",
                }
            elif rel.release_id == "WB_2022_R05":
                return {
                    "date": "2022-04-12",
                    "provider": "Airbus",
                    "accuracy": "2m",
                    "resolution": "0.5m",
                    "source": "Pleiades",
                }
            return {}

        mock_meta.side_effect = meta_side_effect

        results = get_local_changes_with_metadata(
            lon=-121.4944, lat=38.5816, scale=24000.0, releases=self.releases
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].capture_date, "2023-11-01")
        self.assertEqual(results[0].provider, "Maxar")
        self.assertEqual(
            results[0].formatted_display_name,
            "2023-11-01 (Wayback 2023-12-07 - Maxar)",
        )

        self.assertEqual(results[1].capture_date, "2022-04-12")
        self.assertEqual(results[1].provider, "Airbus")
        self.assertEqual(
            results[1].formatted_display_name,
            "2022-04-12 (Wayback 2022-05-18 - Airbus)",
        )


if __name__ == "__main__":
    unittest.main()
