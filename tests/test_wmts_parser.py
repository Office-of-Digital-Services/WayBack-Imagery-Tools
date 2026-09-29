"""Unit tests for Esri Wayback WMTS Capabilities XML Parser.
"""

import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import xml.etree.ElementTree as ET

from wayback_addin.models import CapabilitiesMetadata
from wayback_addin.wmts_parser import (
    DEFAULT_NETWORK_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    DEFAULT_WMTS_URL,
    WMTSParser,
    fetch_capabilities,
    parse_capabilities_xml,
)

SAMPLE_WMTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Capabilities xmlns="http://www.opengis.net/wmts/1.0"
              xmlns:ows="http://www.opengis.net/ows/1.1"
              xmlns:xlink="http://www.w3.org/1999/xlink"
              version="1.0.0">
  <ows:ServiceIdentification>
    <ows:Title>Esri Wayback World Imagery</ows:Title>
    <ows:Abstract>Historical imagery archive</ows:Abstract>
  </ows:ServiceIdentification>
  <Contents>
    <Layer>
      <ows:Title>World Imagery (Wayback 2026-08-05)</ows:Title>
      <ows:Identifier>WB_2026_R07</ows:Identifier>
      <ResourceURL format="image/jpeg" resourceType="tile"
                   template="https://wayback.maptiles.arcgis.com/WMTS/1.0.0/{TileMatrixSet}/MapServer/tile/26334/{TileMatrix}/{TileRow}/{TileCol}"/>
    </Layer>
    <Layer>
      <ows:Title>World Imagery (Wayback 2024-05-15)</ows:Title>
      <ows:Identifier>WB_2024_R05</ows:Identifier>
      <ResourceURL format="image/jpeg" resourceType="tile"
                   template="https://wayback.maptiles.arcgis.com/WMTS/1.0.0/{TileMatrixSet}/MapServer/tile/24100/{TileMatrix}/{TileRow}/{TileCol}"/>
    </Layer>
    <Layer>
      <ows:Title>World Imagery (Wayback 2026-01-10)</ows:Title>
      <ows:Identifier>WB_2026_R01</ows:Identifier>
      <ResourceURL format="image/jpeg" resourceType="tile"
                   template="https://wayback.maptiles.arcgis.com/WMTS/1.0.0/{TileMatrixSet}/MapServer/tile/25900/{TileMatrix}/{TileRow}/{TileCol}"/>
    </Layer>
    <Layer>
      <!-- Non-Wayback root layer or metadata layer without identifier -->
      <ows:Title>Generic Service Layer</ows:Title>
    </Layer>
  </Contents>
</Capabilities>
"""


class TestWMTSParser(unittest.TestCase):
    """Test suite for WMTSParser XML parsing, sorting, and error handling."""

    def test_default_constants(self) -> None:
        """Tests default endpoint URL and network configuration constants."""
        self.assertTrue(DEFAULT_WMTS_URL.startswith("https://wayback.maptiles.arcgis.com"))
        self.assertIn("Wayback", DEFAULT_USER_AGENT)
        self.assertGreaterEqual(DEFAULT_NETWORK_TIMEOUT_SECONDS, 10)

    def test_parse_sample_xml_content(self) -> None:
        """Tests parsing sample XML and confirms chronological ordering and indices."""
        parser = WMTSParser()
        metadata = parser.parse_xml_content(SAMPLE_WMTS_XML, "https://test.url/wmts.xml")

        self.assertIsInstance(metadata, CapabilitiesMetadata)
        self.assertEqual(metadata.service_title, "Esri Wayback World Imagery")
        self.assertEqual(metadata.capabilities_url, "https://test.url/wmts.xml")
        self.assertEqual(metadata.release_count, 3)

        # Confirm chronological descending order (newest date first)
        # 1. 2026-08-05 (WB_2026_R07) -> Index 0
        # 2. 2026-01-10 (WB_2026_R01) -> Index 1
        # 3. 2024-05-15 (WB_2024_R05) -> Index 2
        r0 = metadata.releases[0]
        self.assertEqual(r0.release_id, "WB_2026_R07")
        self.assertEqual(r0.release_date, "2026-08-05")
        self.assertEqual(r0.release_index, 0)
        self.assertIn("26334", r0.tile_url_template)

        r1 = metadata.releases[1]
        self.assertEqual(r1.release_id, "WB_2026_R01")
        self.assertEqual(r1.release_date, "2026-01-10")
        self.assertEqual(r1.release_index, 1)

        r2 = metadata.releases[2]
        self.assertEqual(r2.release_id, "WB_2024_R05")
        self.assertEqual(r2.release_date, "2024-05-15")
        self.assertEqual(r2.release_index, 2)

    def test_parse_bytes_content(self) -> None:
        """Tests that parse_xml_content accepts raw bytes."""
        parser = WMTSParser()
        metadata = parser.parse_xml_content(SAMPLE_WMTS_XML.encode("utf-8"))
        self.assertEqual(metadata.release_count, 3)

    def test_parse_malformed_xml_raises_error(self) -> None:
        """Tests that malformed XML raises an ElementTree ParseError."""
        parser = WMTSParser()
        with self.assertRaises(ET.ParseError):
            parser.parse_xml_content("<invalid xml content><unclosed>")

    def test_convenience_function_parse_capabilities_xml(self) -> None:
        """Tests parse_capabilities_xml helper function."""
        metadata = parse_capabilities_xml(SAMPLE_WMTS_XML)
        self.assertEqual(metadata.release_count, 3)
        self.assertEqual(metadata.latest_release.release_id, "WB_2026_R07")

    @patch("urllib.request.urlopen")
    def test_fetch_xml_success(self, mock_urlopen: MagicMock) -> None:
        """Tests network fetching simulation with mocked HTTP response."""
        mock_response = MagicMock()
        mock_response.read.return_value = SAMPLE_WMTS_XML.encode("utf-8")
        mock_response.headers.get_content_charset.return_value = "utf-8"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        parser = WMTSParser(capabilities_url="https://mock.wayback/capabilities.xml")
        xml_result = parser.fetch_xml()
        self.assertIn("WB_2026_R07", xml_result)

    @patch("urllib.request.urlopen")
    def test_fetch_xml_network_error(self, mock_urlopen: MagicMock) -> None:
        """Tests that URLError is propagated properly when network is down."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        parser = WMTSParser(capabilities_url="https://unreachable.wayback/capabilities.xml")

        with self.assertRaises(urllib.error.URLError):
            parser.fetch_xml()

    @patch("wayback_addin.wmts_parser.WMTSParser.fetch_xml")
    def test_fetch_capabilities_convenience_function(self, mock_fetch_xml: MagicMock) -> None:
        """Tests fetch_capabilities convenience wrapper."""
        mock_fetch_xml.return_value = SAMPLE_WMTS_XML
        meta = fetch_capabilities()
        self.assertEqual(meta.release_count, 3)
        self.assertEqual(meta.latest_release.release_id, "WB_2026_R07")


if __name__ == "__main__":
    unittest.main()
