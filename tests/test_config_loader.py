"""Unit tests for the Wayback configuration JSON loader and parser."""

import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from wayback_addin.config_loader import (
    WAYBACK_CONFIG_URL,
    fetch_and_parse_wayback_config,
    fetch_wayback_config_json,
    parse_wayback_config,
)
from wayback_addin.models import CapabilitiesMetadata, WaybackRelease

SAMPLE_WAYBACK_CONFIG = {
    "26334": {
        "itemID": "85050f00f4f849f8bb352eb91b5e3db7",
        "itemTitle": "World Imagery (Wayback 2026-08-05)",
        "itemURL": "https://www.arcgis.com/home/item.html?id=85050f00f4f849f8bb352eb91b5e3db7",
        "metadataLayerUrl": "https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2026_r07/MapServer",
        "metadataLayerItemID": "e0ca2b73ec184ebfb2424cf9635b75ce",
        "layerIdentifier": "WB_2026_R07",
        "releaseDate": "2026-08-05",
    },
    "26300": {
        "itemID": "12345f00f4f849f8bb352eb91b5e3abc",
        "itemTitle": "World Imagery (Wayback 2026-07-01)",
        "itemURL": "https://www.arcgis.com/home/item.html?id=12345f00f4f849f8bb352eb91b5e3abc",
        "metadataLayerUrl": "https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2026_r06/MapServer",
        "metadataLayerItemID": "abc12373ec184ebfb2424cf9635b75ce",
        "layerIdentifier": "WB_2026_R06",
        "releaseDate": "2026-07-01",
    },
    "8520": {
        "itemID": "99999f00f4f849f8bb352eb91b5e3fff",
        "itemTitle": "World Imagery (Wayback 2014-02-20)",
        "itemURL": "https://www.arcgis.com/home/item.html?id=99999f00f4f849f8bb352eb91b5e3fff",
        "metadataLayerUrl": "https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2014_r01/MapServer",
        "metadataLayerItemID": "fff99973ec184ebfb2424cf9635b75ce",
        "layerIdentifier": "WB_2014_R01",
        "releaseDate": "2014-02-20",
    },
}


class TestConfigLoader(unittest.TestCase):
    """Test suite for waybackconfig.json loading and parsing."""

    def test_parse_wayback_config_dict(self) -> None:
        """Verify parsing from a dictionary data structure."""
        metadata = parse_wayback_config(SAMPLE_WAYBACK_CONFIG)
        self.assertIsInstance(metadata, CapabilitiesMetadata)
        self.assertEqual(metadata.release_count, 3)

        # First release should be newest (2026-08-05)
        latest = metadata.latest_release
        self.assertIsNotNone(latest)
        self.assertEqual(latest.release_id, "WB_2026_R07")
        self.assertEqual(latest.release_date, "2026-08-05")
        self.assertEqual(latest.release_index, 0)
        self.assertEqual(latest.item_id, "85050f00f4f849f8bb352eb91b5e3db7")
        self.assertEqual(latest.numeric_release_number, 26334)
        self.assertEqual(latest.release_number, 26334)
        self.assertEqual(
            latest.metadata_service_url,
            "https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2026_r07/MapServer",
        )

        # Last release should be oldest (2014-02-20)
        oldest = metadata.oldest_release
        self.assertIsNotNone(oldest)
        self.assertEqual(oldest.release_id, "WB_2014_R01")
        self.assertEqual(oldest.release_date, "2014-02-20")
        self.assertEqual(oldest.release_index, 2)
        self.assertEqual(oldest.numeric_release_number, 8520)

    def test_parse_wayback_config_json_string(self) -> None:
        """Verify parsing from a raw JSON string."""
        json_str = json.dumps(SAMPLE_WAYBACK_CONFIG)
        metadata = parse_wayback_config(json_str)
        self.assertEqual(metadata.release_count, 3)
        self.assertEqual(metadata.releases[0].release_id, "WB_2026_R07")

    def test_parse_wayback_config_invalid_type(self) -> None:
        """Verify ValueError is raised for invalid input types."""
        with self.assertRaises(ValueError):
            parse_wayback_config(12345)

    @patch("urllib.request.urlopen")
    def test_fetch_wayback_config_json_success(self, mock_urlopen) -> None:
        """Verify fetching remote JSON successfully."""
        mock_response = MagicMock()
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.read.return_value = json.dumps(SAMPLE_WAYBACK_CONFIG).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        content = fetch_wayback_config_json("https://fake.url/waybackconfig.json")
        self.assertIn("WB_2026_R07", content)

    @patch("urllib.request.urlopen")
    def test_fetch_wayback_config_json_error(self, mock_urlopen) -> None:
        """Verify handling of network errors during fetch."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with self.assertRaises(urllib.error.URLError):
            fetch_wayback_config_json("https://fake.url/waybackconfig.json")

    @patch("wayback_addin.config_loader.fetch_wayback_config_json")
    def test_fetch_and_parse_wayback_config(self, mock_fetch) -> None:
        """Verify full fetch and parse workflow."""
        mock_fetch.return_value = json.dumps(SAMPLE_WAYBACK_CONFIG)
        meta = fetch_and_parse_wayback_config()
        self.assertEqual(meta.release_count, 3)
        self.assertEqual(meta.releases[0].release_id, "WB_2026_R07")


if __name__ == "__main__":
    unittest.main()
