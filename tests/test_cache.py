"""Unit tests for Hybrid Two-Tier Cache Manager.
"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from wayback_addin.cache import (
    DEFAULT_CACHE_TTL_SECONDS,
    CacheManager,
    get_bundled_fallback_path,
    get_default_cache_path,
)
from wayback_addin.models import CapabilitiesMetadata, WaybackRelease


class TestCacheManager(unittest.TestCase):
    """Test suite for CacheManager hybrid tiering, TTL validation, and navigation helpers."""

    def setUp(self) -> None:
        """Sets up a temporary directory and sample data for isolated cache testing."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = os.path.join(self.temp_dir.name, "test_cache.json")
        self.fallback_file = os.path.join(self.temp_dir.name, "test_fallback.json")

        self.sample_releases = [
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
        self.sample_metadata = CapabilitiesMetadata(
            service_title="Esri Wayback World Imagery WMTS",
            capabilities_url="https://wayback/capabilities.xml",
            fetched_at="2026-08-21T12:00:00Z",
            releases=self.sample_releases,
        )

        # Write fallback file
        with open(self.fallback_file, "w", encoding="utf-8") as f:
            json.dump(self.sample_metadata.to_dict(), f)

    def tearDown(self) -> None:
        """Cleans up temporary directory after testing."""
        self.temp_dir.cleanup()

    def test_default_paths(self) -> None:
        """Tests that default cache path and bundled fallback paths are resolvable."""
        default_path = get_default_cache_path()
        self.assertTrue(default_path.endswith("wayback_capabilities_cache.json"))

        fallback_path = get_bundled_fallback_path()
        self.assertTrue(fallback_path.endswith("fallback_capabilities.json"))
        self.assertTrue(os.path.isfile(fallback_path), "Bundled fallback capabilities file should exist")

    def test_save_and_load_disk_cache(self) -> None:
        """Tests writing to disk cache and reading back identical metadata."""
        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        self.assertFalse(manager.is_disk_cache_valid())

        # Save metadata
        saved = manager.save_to_disk(self.sample_metadata)
        self.assertTrue(saved)
        self.assertTrue(os.path.isfile(self.cache_file))
        self.assertTrue(manager.is_disk_cache_valid())

        # Load metadata
        loaded = manager.load_from_disk()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.release_count, 3)
        self.assertEqual(loaded.releases[0].release_id, "WB_2026_R07")

    def test_disk_cache_ttl_expiration(self) -> None:
        """Tests that disk cache expiration is detected when TTL is exceeded."""
        manager = CacheManager(
            cache_file_path=self.cache_file,
            ttl_seconds=1,  # 1 second TTL
            bundled_fallback_path=self.fallback_file,
        )
        manager.save_to_disk(self.sample_metadata)
        self.assertTrue(manager.is_disk_cache_valid())

        # Artificially age the file modified time
        old_time = time.time() - 100
        os.utime(self.cache_file, (old_time, old_time))

        self.assertFalse(manager.is_disk_cache_valid())

    def test_in_memory_cache_tier(self) -> None:
        """Tests that active in-memory cache is returned immediately without disk access."""
        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        manager._in_memory_metadata = self.sample_metadata

        # get_metadata should return in-memory without checking disk
        meta = manager.get_metadata(force_refresh=False)
        self.assertEqual(meta, self.sample_metadata)

    @patch("wayback_addin.cache.fetch_and_parse_wayback_config")
    def test_live_network_tier_and_persistence(self, mock_fetch_config: MagicMock) -> None:
        """Tests live network query when cache is missing, confirming it persists to disk."""
        mock_fetch_config.return_value = self.sample_metadata

        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        meta = manager.get_metadata(force_refresh=True)

        self.assertEqual(meta.release_count, 3)
        mock_fetch_config.assert_called_once()
        # Verify it was saved to disk
        self.assertTrue(os.path.isfile(self.cache_file))

    @patch("wayback_addin.cache.WMTSParser.fetch_and_parse")
    @patch("wayback_addin.cache.fetch_and_parse_wayback_config")
    def test_live_network_wmts_fallback(
        self, mock_fetch_config: MagicMock, mock_fetch_wmts: MagicMock
    ) -> None:
        """Tests that when waybackconfig.json fails, WMTS capabilities XML is fetched and parsed."""
        mock_fetch_config.side_effect = RuntimeError("Config URL unavailable")
        mock_fetch_wmts.return_value = self.sample_metadata

        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        meta = manager.get_metadata(force_refresh=True)

        self.assertEqual(meta.release_count, 3)
        mock_fetch_config.assert_called_once()
        mock_fetch_wmts.assert_called_once()
        self.assertTrue(os.path.isfile(self.cache_file))

    @patch("wayback_addin.cache.WMTSParser.fetch_and_parse")
    @patch("wayback_addin.cache.fetch_and_parse_wayback_config")
    def test_offline_fallback_to_bundled_json(
        self, mock_fetch_config: MagicMock, mock_fetch_wmts: MagicMock
    ) -> None:
        """Tests that when both live network options fail and no disk cache exists, bundled fallback is loaded."""
        mock_fetch_config.side_effect = RuntimeError("Config URL down")
        mock_fetch_wmts.side_effect = RuntimeError("WMTS down")

        manager = CacheManager(
            cache_file_path=self.cache_file,  # does not exist
            bundled_fallback_path=self.fallback_file,
        )
        meta = manager.get_metadata()

        self.assertIsNotNone(meta)
        self.assertEqual(meta.release_count, 3)
        self.assertEqual(meta.releases[0].release_id, "WB_2026_R07")

    def test_navigation_helpers_stepping(self) -> None:
        """Tests adjacent release stepping logic (forward = newer, backward = older)."""
        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        manager._in_memory_metadata = self.sample_metadata

        # Current is middle release: Index 1 (WB_2026_R06, 2026-07-01)
        # Step forward (+1, newer): should go to Index 0 (WB_2026_R07)
        newer = manager.get_adjacent_release("WB_2026_R06", direction=1)
        self.assertIsNotNone(newer)
        self.assertEqual(newer.release_id, "WB_2026_R07")
        self.assertEqual(newer.release_index, 0)

        # Step backward (-1, older): should go to Index 2 (WB_2014_R01)
        older = manager.get_adjacent_release("WB_2026_R06", direction=-1)
        self.assertIsNotNone(older)
        self.assertEqual(older.release_id, "WB_2014_R01")
        self.assertEqual(older.release_index, 2)

        # Step using date string instead of ID
        newer_by_date = manager.get_adjacent_release("2026-07-01", direction=1)
        self.assertEqual(newer_by_date.release_id, "WB_2026_R07")

    def test_navigation_boundaries(self) -> None:
        """Tests boundary handling when stepping beyond newest or oldest releases."""
        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        manager._in_memory_metadata = self.sample_metadata

        # Stepping newer from latest release (Index 0) -> should return None
        at_newest = manager.get_adjacent_release("WB_2026_R07", direction=1)
        self.assertIsNone(at_newest)

        # Stepping older from oldest release (Index 2) -> should return None
        at_oldest = manager.get_adjacent_release("WB_2014_R01", direction=-1)
        self.assertIsNone(at_oldest)

        # Non-existent identifier -> returns None
        unknown = manager.get_adjacent_release("WB_NON_EXISTENT", direction=1)
        self.assertIsNone(unknown)

    def test_clear_cache(self) -> None:
        """Tests clearing memory and deleting disk cache file."""
        manager = CacheManager(
            cache_file_path=self.cache_file,
            bundled_fallback_path=self.fallback_file,
        )
        manager.save_to_disk(self.sample_metadata)
        manager._in_memory_metadata = self.sample_metadata

        self.assertTrue(os.path.isfile(self.cache_file))
        manager.clear_cache()

        self.assertIsNone(manager._in_memory_metadata)
        self.assertFalse(os.path.isfile(self.cache_file))


if __name__ == "__main__":
    unittest.main()
