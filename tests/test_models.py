"""Unit tests for Wayback imagery data models (WaybackRelease and CapabilitiesMetadata).
"""

from datetime import datetime
import unittest

from wayback_addin.models import CapabilitiesMetadata, LocalChangeImageryRelease, WaybackRelease


class TestWaybackReleaseModel(unittest.TestCase):
    """Test suite for WaybackRelease dataclass validation and serialization."""

    def setUp(self) -> None:
        """Sets up sample release instances for testing."""
        self.sample_release = WaybackRelease(
            release_id="WB_2026_R07",
            title="World Imagery (Wayback 2026-08-05)",
            release_date="2026-08-05",
            tile_url_template="https://wayback.maptiles.arcgis.com/tile/26334/{TileMatrix}/{TileRow}/{TileCol}",
            release_index=0,
        )

    def test_release_initialization_and_properties(self) -> None:
        """Tests that release attributes are correctly stored and accessible."""
        self.assertEqual(self.sample_release.release_id, "WB_2026_R07")
        self.assertEqual(self.sample_release.title, "World Imagery (Wayback 2026-08-05)")
        self.assertEqual(self.sample_release.release_date, "2026-08-05")
        self.assertEqual(self.sample_release.release_index, 0)
        self.assertIn("26334", self.sample_release.tile_url_template)

    def test_parsed_date_valid(self) -> None:
        """Tests conversion from ISO date string to datetime object."""
        parsed = self.sample_release.parsed_date
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed, datetime(2026, 8, 5))

    def test_parsed_date_invalid_or_empty(self) -> None:
        """Tests handling of invalid or empty date strings."""
        invalid_rel = WaybackRelease(
            release_id="WB_INVALID",
            title="Invalid Date",
            release_date="not-a-date",
            tile_url_template="",
            release_index=1,
        )
        self.assertIsNone(invalid_rel.parsed_date)

        empty_date_rel = WaybackRelease(
            release_id="WB_EMPTY",
            title="Empty Date",
            release_date="",
            tile_url_template="",
            release_index=2,
        )
        self.assertIsNone(empty_date_rel.parsed_date)

    def test_formatted_display_name(self) -> None:
        """Tests generation of user-facing display names for UI elements."""
        self.assertEqual(
            self.sample_release.formatted_display_name,
            "2026-08-05 (WB_2026_R07)",
        )

        no_date_rel = WaybackRelease(
            release_id="WB_NODATE",
            title="Old Layer",
            release_date="",
            tile_url_template="",
            release_index=3,
        )
        self.assertEqual(no_date_rel.formatted_display_name, "Old Layer (WB_NODATE)")

    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        """Tests complete dictionary serialization and deserialization."""
        data = self.sample_release.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["release_id"], "WB_2026_R07")
        self.assertEqual(data["release_date"], "2026-08-05")
        self.assertEqual(data["release_index"], 0)

        restored = WaybackRelease.from_dict(data)
        self.assertEqual(restored, self.sample_release)

    def test_immutability(self) -> None:
        """Tests that WaybackRelease is frozen and prevents attribute mutation."""
        with self.assertRaises((AttributeError, TypeError)):
            # Dataclass is frozen, assigning to an attribute raises an error
            self.sample_release.release_id = "WB_MODIFIED"  # type: ignore

    def test_release_number_from_tile_url(self) -> None:
        """Tests extraction of the numeric release number from the tile URL template."""
        # Standard tile URL with release number
        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template=(
                "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
                "World_Imagery/MapServer/tile/56102/{TileMatrix}/{TileRow}/{TileCol}"
            ),
            release_index=0,
        )
        self.assertEqual(release.release_number, 56102)

    def test_release_number_from_short_tile_url(self) -> None:
        """Tests extraction from short test tile URLs."""
        release = WaybackRelease(
            release_id="WB_2014_R01",
            title="World Imagery (Wayback 2014-02-20)",
            release_date="2014-02-20",
            tile_url_template="https://wayback/tile/10",
            release_index=2,
        )
        self.assertEqual(release.release_number, 10)

    def test_release_number_missing_tile_url(self) -> None:
        """Tests that release_number returns None when the tile URL has no recognizable number."""
        release = WaybackRelease(
            release_id="WB_UNKNOWN",
            title="No tile URL",
            release_date="2020-01-01",
            tile_url_template="",
            release_index=5,
        )
        self.assertIsNone(release.release_number)

    def test_metadata_service_url_construction(self) -> None:
        """Tests construction of the metadata feature service URL from release_id."""
        release = WaybackRelease(
            release_id="WB_2023_R11",
            title="World Imagery (Wayback 2023-12-07)",
            release_date="2023-12-07",
            tile_url_template="",
            release_index=0,
        )
        metadata_url = release.metadata_service_url
        self.assertIsNotNone(metadata_url)
        # URL should use year and lowercase release sequence from release_id
        self.assertIn("World_Imagery_Metadata_2023_r11", metadata_url)
        self.assertIn("metadata.maptiles.arcgis.com", metadata_url)
        self.assertTrue(metadata_url.endswith("/MapServer"))

    def test_metadata_service_url_single_digit_release(self) -> None:
        """Tests metadata URL with a single-digit release sequence maintains two-digit zero-padding (e.g., R01 → r01)."""
        release = WaybackRelease(
            release_id="WB_2014_R01",
            title="World Imagery (Wayback 2014-02-20)",
            release_date="2014-02-20",
            tile_url_template="",
            release_index=0,
        )
        metadata_url = release.metadata_service_url
        self.assertIsNotNone(metadata_url)
        self.assertIn("World_Imagery_Metadata_2014_r01", metadata_url)

    def test_metadata_service_url_custom_override(self) -> None:
        """Tests metadata URL when metadata_layer_url is explicitly provided."""
        custom_url = "https://custom.metadata.endpoint/World_Imagery_Metadata_2026_r07/MapServer"
        release = WaybackRelease(
            release_id="WB_2026_R07",
            title="World Imagery (Wayback 2026-08-05)",
            release_date="2026-08-05",
            tile_url_template="",
            metadata_layer_url=custom_url,
        )
        self.assertEqual(release.metadata_service_url, custom_url)

    def test_metadata_service_url_none_when_invalid_release_id(self) -> None:
        """Tests that metadata_service_url returns None when release_id doesn't match pattern."""
        release = WaybackRelease(
            release_id="WB_UNKNOWN",
            title="No valid ID",
            release_date="2020-01-01",
            tile_url_template="",
            release_index=5,
        )
        self.assertIsNone(release.metadata_service_url)


class TestCapabilitiesMetadataModel(unittest.TestCase):
    """Test suite for CapabilitiesMetadata collection and lookup operations."""

    def setUp(self) -> None:
        """Sets up a sample collection of releases for testing."""
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

    def test_release_count_and_boundaries(self) -> None:
        """Tests release count calculation, latest release, and oldest release lookups."""
        self.assertEqual(self.metadata.release_count, 3)
        self.assertEqual(self.metadata.latest_release, self.releases[0])
        self.assertEqual(self.metadata.oldest_release, self.releases[2])

    def test_empty_metadata_boundaries(self) -> None:
        """Tests boundary lookups on empty metadata object."""
        empty_meta = CapabilitiesMetadata(
            service_title="Empty",
            capabilities_url="",
            fetched_at="",
            releases=[],
        )
        self.assertEqual(empty_meta.release_count, 0)
        self.assertIsNone(empty_meta.latest_release)
        self.assertIsNone(empty_meta.oldest_release)

    def test_get_by_id(self) -> None:
        """Tests looking up releases by ID with case-insensitivity and non-existent IDs."""
        rel = self.metadata.get_by_id("WB_2026_R07")
        self.assertIsNotNone(rel)
        self.assertEqual(rel.release_date, "2026-08-05")

        # Case-insensitive check
        rel_lower = self.metadata.get_by_id("wb_2026_r06")
        self.assertIsNotNone(rel_lower)
        self.assertEqual(rel_lower.release_id, "WB_2026_R06")

        # Non-existent ID
        self.assertIsNone(self.metadata.get_by_id("WB_NON_EXISTENT"))

    def test_get_by_date(self) -> None:
        """Tests looking up releases by date."""
        rel = self.metadata.get_by_date("2026-07-01")
        self.assertIsNotNone(rel)
        self.assertEqual(rel.release_id, "WB_2026_R06")

        self.assertIsNone(self.metadata.get_by_date("1999-01-01"))

    def test_get_by_index(self) -> None:
        """Tests index lookup and bounds checking."""
        self.assertEqual(self.metadata.get_by_index(0), self.releases[0])
        self.assertEqual(self.metadata.get_by_index(1), self.releases[1])
        self.assertEqual(self.metadata.get_by_index(2), self.releases[2])

        self.assertIsNone(self.metadata.get_by_index(-1))
        self.assertIsNone(self.metadata.get_by_index(3))

    def test_metadata_dict_roundtrip(self) -> None:
        """Tests full serialization and deserialization of CapabilitiesMetadata."""
        data = self.metadata.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(len(data["releases"]), 3)

        restored = CapabilitiesMetadata.from_dict(data)
        self.assertEqual(restored.service_title, self.metadata.service_title)
        self.assertEqual(restored.capabilities_url, self.metadata.capabilities_url)
        self.assertEqual(restored.release_count, 3)
        self.assertEqual(restored.releases[0], self.releases[0])


class TestLocalChangeImageryReleaseModel(unittest.TestCase):
    """Test suite for LocalChangeImageryRelease dataclass validation and formatting."""

    def setUp(self) -> None:
        """Sets up sample releases and local change instances."""
        self.sample_release = WaybackRelease(
            release_id="WB_2022_R05",
            title="World Imagery (Wayback 2022-05-18)",
            release_date="2022-05-18",
            tile_url_template="https://wayback/tile/50000",
            release_index=10,
        )
        self.local_change = LocalChangeImageryRelease(
            release=self.sample_release,
            capture_date="2022-04-12",
            provider="Maxar",
            accuracy="1m",
            resolution="0.3m",
            source="DigitalGlobe GeoEye-1",
        )

    def test_initialization_and_properties(self) -> None:
        """Tests that local change properties are properly stored."""
        self.assertEqual(self.local_change.release, self.sample_release)
        self.assertEqual(self.local_change.capture_date, "2022-04-12")
        self.assertEqual(self.local_change.provider, "Maxar")
        self.assertEqual(self.local_change.accuracy, "1m")
        self.assertEqual(self.local_change.resolution, "0.3m")
        self.assertEqual(self.local_change.source, "DigitalGlobe GeoEye-1")

    def test_formatted_display_name_with_provider(self) -> None:
        """Tests formatted display name with capture date and provider."""
        self.assertEqual(
            self.local_change.formatted_display_name,
            "2022-04-12 (Wayback 2022-05-18 - Maxar)",
        )

    def test_formatted_display_name_without_provider(self) -> None:
        """Tests formatted display name when provider is None."""
        no_prov = LocalChangeImageryRelease(
            release=self.sample_release,
            capture_date="2022-04-12",
            provider=None,
        )
        self.assertEqual(
            no_prov.formatted_display_name,
            "2022-04-12 (Wayback 2022-05-18)",
        )

    def test_formatted_display_name_missing_capture_date(self) -> None:
        """Tests formatted display name when capture date is None."""
        no_date = LocalChangeImageryRelease(
            release=self.sample_release,
            capture_date=None,
            provider="USDA",
        )
        self.assertEqual(
            no_date.formatted_display_name,
            "Unknown Date (Wayback 2022-05-18 - USDA)",
        )

    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        """Tests serialization and deserialization of LocalChangeImageryRelease."""
        data = self.local_change.to_dict()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["capture_date"], "2022-04-12")
        self.assertEqual(data["provider"], "Maxar")
        self.assertEqual(data["release"]["release_id"], "WB_2022_R05")

        restored = LocalChangeImageryRelease.from_dict(data)
        self.assertEqual(restored.capture_date, self.local_change.capture_date)
        self.assertEqual(restored.provider, self.local_change.provider)
        self.assertEqual(restored.release.release_id, self.sample_release.release_id)


if __name__ == "__main__":
    unittest.main()
