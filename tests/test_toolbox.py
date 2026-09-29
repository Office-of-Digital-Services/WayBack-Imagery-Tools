"""Functional unit tests for ArcGIS Pro Python Toolbox (WaybackImagery.pyt).
"""

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

from wayback_addin.models import LocalChangeImageryRelease, WaybackRelease

# Mock arcpy for testing environment if not loaded
mock_arcpy = MagicMock()
sys.modules["arcpy"] = mock_arcpy

# Dynamically load the .pyt module using SourceFileLoader
PYT_PATH = str(Path(__file__).resolve().parent.parent / "WaybackImagery.pyt")
loader = importlib.machinery.SourceFileLoader("WaybackImagery", PYT_PATH)
spec = importlib.util.spec_from_file_location("WaybackImagery", PYT_PATH, loader=loader)
wayback_pyt = importlib.util.module_from_spec(spec)
sys.modules["WaybackImagery"] = wayback_pyt
spec.loader.exec_module(wayback_pyt)
wayback_pyt.HAS_ARCPY = True
wayback_pyt.arcpy = mock_arcpy


def _create_mock_param(*args, **kwargs):
    name = kwargs.get("name", "")
    datatype = kwargs.get("datatype", "GPString")
    return MockParameter(name=name, datatype=datatype)


mock_arcpy.Parameter.side_effect = _create_mock_param


class MockParameter:
    """Mock representing arcpy.Parameter for testing tool validation without ArcPy runtime.

    Mirrors key ArcGIS Pro parameter properties including hasBeenValidated and altered
    which control re-validation behavior in the tool dialog.
    """

    def __init__(
        self,
        name: str,
        value: str = "",
        enabled: bool = True,
        datatype: str = "GPString",
    ) -> None:
        self.name = name
        self.value = value
        self.valueAsText = value
        self.enabled = enabled
        self.datatype = datatype
        self.filter = MagicMock()
        self.filter.list = []
        self._error_message = None
        self._warning_message = None
        # ArcGIS Pro validation properties:
        # hasBeenValidated: False when the user has changed the value since the last
        #   updateParameters + internal validate cycle. True after internal validation.
        # altered: True if the user has ever modified this parameter's value.
        self.hasBeenValidated = False
        self.altered = False

    def setErrorMessage(self, msg: str) -> None:
        self._error_message = msg

    def setWarningMessage(self, msg: str) -> None:
        self._warning_message = msg

    def clearMessage(self) -> None:
        self._error_message = None
        self._warning_message = None


class TestWaybackToolbox(unittest.TestCase):
    """Test suite for WaybackImagery.pyt toolbox structure and tool parameter validators."""

    def setUp(self) -> None:
        """Sets up sample releases and mock objects."""
        self.sample_release = WaybackRelease(
            release_id="WB_2026_R07",
            title="World Imagery (Wayback 2026-08-05)",
            release_date="2026-08-05",
            tile_url_template="https://wayback/tile/26334",
            release_index=0,
        )

    def test_toolbox_definition(self) -> None:
        """Tests Toolbox metadata and registered tools."""
        tb = wayback_pyt.Toolbox()
        self.assertEqual(tb.label, "Wayback Imagery Tools")
        self.assertEqual(tb.alias, "WaybackImagery")
        self.assertEqual(len(tb.tools), 6)
        self.assertIn(wayback_pyt.WaybackStepperTool, tb.tools)
        self.assertIn(wayback_pyt.WaybackSliderTool, tb.tools)
        self.assertIn(wayback_pyt.StepForwardTool, tb.tools)
        self.assertIn(wayback_pyt.StepBackwardTool, tb.tools)
        self.assertIn(wayback_pyt.IdentifyMetadataTool, tb.tools)
        self.assertIn(wayback_pyt.WaybackCaptureDateTool, tb.tools)

    def test_stepper_tool_initialization(self) -> None:
        """Tests WaybackStepperTool initialization and attributes."""
        tool = wayback_pyt.WaybackStepperTool()
        self.assertEqual(tool.label, "Wayback Imagery Stepper")
        self.assertFalse(tool.canRunInBackground)

    def test_stepper_update_parameters_jump_mode(self) -> None:
        """Tests that selecting 'Jump to Date' enables the date dropdown parameter."""
        tool = wayback_pyt.WaybackStepperTool()

        param_action = MockParameter("action_mode", value="Jump to Date")
        param_date = MockParameter("release_date", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")

        parameters = [param_action, param_date, param_map]
        tool.updateParameters(parameters)

        self.assertTrue(param_date.enabled)
        self.assertTrue(len(param_date.filter.list) > 0)
        # Should default to first available date in list
        self.assertEqual(param_date.value, param_date.filter.list[0])

    def test_stepper_update_parameters_step_mode(self) -> None:
        """Tests that selecting 'Step Forward' disables the date dropdown parameter."""
        tool = wayback_pyt.WaybackStepperTool()

        param_action = MockParameter("action_mode", value="Step Forward (Newer)")
        param_date = MockParameter("release_date", value="2026-08-05", enabled=True)
        param_map = MockParameter("target_map", value="CURRENT")

        parameters = [param_action, param_date, param_map]
        tool.updateParameters(parameters)

        self.assertFalse(param_date.enabled)

    def test_stepper_update_messages_missing_date(self) -> None:
        """Tests that updateMessages flags missing date when in Jump to Date mode."""
        tool = wayback_pyt.WaybackStepperTool()

        param_action = MockParameter("action_mode", value="Jump to Date")
        param_date = MockParameter("release_date", value="")

        parameters = [param_action, param_date]
        tool.updateMessages(parameters)

        self.assertIsNotNone(param_date._error_message)
        self.assertIn("A Historical Release Date must be selected", param_date._error_message)

    @patch("wayback_addin.map_manager.MapManager.step_forward")
    def test_stepper_execute_step_forward(self, mock_step: MagicMock) -> None:
        """Tests executing Step Forward mode."""
        mock_step.return_value = (True, "Stepped forward successfully.", self.sample_release)

        tool = wayback_pyt.WaybackStepperTool()

        param_action = MockParameter("action_mode", value="Step Forward (Newer)")
        param_date = MockParameter("release_date", value="")
        param_map = MockParameter("target_map", value="CURRENT")
        param_out = MockParameter("out_release_date", value="")

        parameters = [param_action, param_date, param_map, param_out]

        with patch("arcpy.AddMessage"):
            tool.execute(parameters, None)

        mock_step.assert_called_once_with("CURRENT")
        self.assertEqual(param_out.value, "2026-08-05")

    @patch("wayback_addin.map_manager.MapManager.set_release_by_date")
    def test_stepper_execute_jump_to_date(self, mock_set_date: MagicMock) -> None:
        """Tests executing Jump to Date mode."""
        mock_set_date.return_value = (True, "Date set successfully.", self.sample_release)

        tool = wayback_pyt.WaybackStepperTool()

        param_action = MockParameter("action_mode", value="Jump to Date")
        param_date = MockParameter("release_date", value="2026-08-05 (WB_2026_R07)")
        param_map = MockParameter("target_map", value="MainMap")
        param_out = MockParameter("out_release_date", value="")

        parameters = [param_action, param_date, param_map, param_out]

        with patch("arcpy.AddMessage"):
            tool.execute(parameters, None)

        mock_set_date.assert_called_once_with("2026-08-05 (WB_2026_R07)", "MainMap")

    @patch("wayback_addin.map_manager.MapManager.step_forward")
    def test_step_forward_tool_execute(self, mock_step: MagicMock) -> None:
        """Tests StepForwardTool convenience execution."""
        mock_step.return_value = (True, "Stepped forward.", self.sample_release)

        tool = wayback_pyt.StepForwardTool()
        param_map = MockParameter("target_map", value="CURRENT")
        param_out = MockParameter("out_release_date", value="")
        parameters = [param_map, param_out]

        with patch("arcpy.AddMessage"):
            tool.execute(parameters, None)

        mock_step.assert_called_once_with("CURRENT")
        self.assertEqual(param_out.value, "2026-08-05")

    @patch("wayback_addin.map_manager.MapManager.step_backward")
    def test_step_backward_tool_execute(self, mock_step: MagicMock) -> None:
        """Tests StepBackwardTool convenience execution."""
        mock_step.return_value = (True, "Stepped backward.", self.sample_release)

        tool = wayback_pyt.StepBackwardTool()
        param_map = MockParameter("target_map", value="CURRENT")
        param_out = MockParameter("out_release_date", value="")
        parameters = [param_map, param_out]

        with patch("arcpy.AddMessage"):
            tool.execute(parameters, None)

        mock_step.assert_called_once_with("CURRENT")
        self.assertEqual(param_out.value, "2026-08-05")

    def test_slider_tool_initialization(self) -> None:
        """Tests WaybackSliderTool initialization and attributes."""
        tool = wayback_pyt.WaybackSliderTool()
        self.assertEqual(tool.label, "Wayback Imagery Time Slider")
        self.assertFalse(tool.canRunInBackground)

    def test_slider_tool_getParameterInfo(self) -> None:
        """Tests WaybackSliderTool parameter initialization and slider control CLSID."""
        tool = wayback_pyt.WaybackSliderTool()
        params = tool.getParameterInfo()
        self.assertEqual(len(params), 5)

        slider_param = params[0]
        self.assertEqual(slider_param.name, "release_slider")
        self.assertIn(slider_param.datatype, ["GPLong", "Long"])
        self.assertEqual(slider_param.controlCLSID, "{C8C46E43-3D27-4485-9B38-A49F3AC588D9}")
        self.assertEqual(slider_param.filter.type, "Range")
        self.assertTrue(len(slider_param.filter.list) == 2)
        self.assertEqual(slider_param.filter.list[0], 1)

        info_param = params[1]
        self.assertEqual(info_param.name, "active_release_info")
        self.assertIn(info_param.datatype, ["GPString", "String"])

        map_param = params[2]
        self.assertEqual(map_param.name, "target_map")
        self.assertEqual(map_param.value, "CURRENT")

        live_param = params[3]
        self.assertEqual(live_param.name, "live_update")
        self.assertTrue(live_param.value)

    def test_slider_update_parameters_formatting(self) -> None:
        """Tests that moving the slider formats the display text parameter.

        With the layer-name dedup approach, the info text is always updated on
        every updateParameters call so the user sees slider position feedback.
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        # Start with newest position
        param_slider = MockParameter("release_slider", value=str(total_releases), datatype="GPLong")
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]
        tool.updateParameters(parameters)

        # Info text is always updated — should show newest release info
        self.assertIn("Latest Release", param_info.value)
        self.assertIn(releases[0].release_id, param_info.value)

        # Move slider to oldest release (index 1)
        param_slider.value = "1"
        param_slider.valueAsText = "1"
        tool.updateParameters(parameters)
        self.assertIn("Oldest Baseline", param_info.value)
        self.assertIn(releases[-1].release_id, param_info.value)

        # Move slider back to newest release
        param_slider.value = str(total_releases)
        param_slider.valueAsText = str(total_releases)
        tool.updateParameters(parameters)
        self.assertIn("Latest Release", param_info.value)
        self.assertIn(releases[0].release_id, param_info.value)

    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_update_parameters_live_map_update(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that slider updates perform dynamic live map updates during validation.

        The layer-name dedup guard compares target_release.title against the actual
        layer name in the map (via get_wayback_layer_name).  When they differ, the
        map layer is updated; when they match, the update is skipped.
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        # Track the current layer name as the map would persist it
        current_layer_name = [None]

        def update_side_effect(release, map_name):
            current_layer_name[0] = release.title
            return MagicMock()

        mock_update.side_effect = update_side_effect
        mock_get_name.side_effect = lambda map_name=None: current_layer_name[0]

        # Start with default position (newest) — no layer exists yet (None)
        param_slider = MockParameter("release_slider", value=str(total_releases), datatype="GPLong")
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]

        # First call creates the layer (no layer exists → name is None → differs from title)
        tool.updateParameters(parameters)
        mock_update.assert_called_once_with(releases[0], "CURRENT")

        # Re-validation with same value — layer name now matches, so update is skipped
        mock_update.reset_mock()
        tool.updateParameters(parameters)
        mock_update.assert_not_called()

        # Move slider to oldest release (slider value = 1)
        param_slider.value = "1"
        param_slider.valueAsText = "1"
        tool.updateParameters(parameters)

        # Map should be updated to oldest release (index total - 1)
        mock_update.assert_called_once_with(releases[-1], "CURRENT")

        # Re-validation with same value — blocked by dedup
        mock_update.reset_mock()
        tool.updateParameters(parameters)
        mock_update.assert_not_called()

        # Moving slider to newest release (total_releases) — triggers update again
        param_slider.value = str(total_releases)
        param_slider.valueAsText = str(total_releases)
        tool.updateParameters(parameters)
        mock_update.assert_called_once_with(releases[0], "CURRENT")

    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_update_parameters_live_disabled(self, mock_update: MagicMock) -> None:
        """Tests that disabling live update prevents map updates during parameter validation."""
        tool = wayback_pyt.WaybackSliderTool()
        param_slider = MockParameter("release_slider", value="1", datatype="GPLong")
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]
        tool.updateParameters(parameters)

        mock_update.assert_not_called()

    def test_slider_update_messages(self) -> None:
        """Tests updateMessages validation rules for the slider."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        # Valid value
        param_slider = MockParameter("release_slider", value="5")
        parameters = [param_slider]
        tool.updateMessages(parameters)
        self.assertIsNone(param_slider._error_message)

        # Out of bounds value
        param_slider.value = str(total_releases + 10)
        tool.updateMessages(parameters)
        self.assertIsNotNone(param_slider._error_message)

        # Non-integer value
        param_slider.value = "abc"
        tool.updateMessages(parameters)
        self.assertIsNotNone(param_slider._error_message)

    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_execute(self, mock_update: MagicMock) -> None:
        """Tests executing WaybackSliderTool manually."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        param_slider = MockParameter("release_slider", value=str(total_releases))
        param_info = MockParameter("active_release_info", value="")
        param_map = MockParameter("target_map", value="MyMap")
        param_live = MockParameter("live_update", value=True)

        parameters = [param_slider, param_info, param_map, param_live]

        with patch("arcpy.AddMessage"):
            tool.execute(parameters, None)

        mock_update.assert_called_once_with(releases[0], "MyMap")


    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_no_redundant_map_update_when_layer_matches(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that no redundant map update occurs when the layer already shows the
        selected release. This is the core anti-flickering guarantee.

        The dedup guard reads the layer name from the map and skips the update if
        the target release title already matches.
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        # Simulate a map that already has the newest release layer
        mock_get_name.return_value = releases[0].title
        mock_update.return_value = MagicMock()

        param_slider = MockParameter("release_slider", value=str(total_releases), datatype="GPLong")
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]
        tool.updateParameters(parameters)

        # Map update should NOT have been called — layer already shows this release
        mock_update.assert_not_called()
        # Info text should still be updated (lightweight, no loop risk)
        self.assertIn(releases[0].release_id, param_info.value)

    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_repeated_calls_same_value_no_map_update(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that calling updateParameters repeatedly with the same slider value
        does not trigger redundant map layer updates (prevents flickering).

        After the first call creates/updates the layer, subsequent calls with the same
        slider value find the layer name matches and skip the map update.
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        # Track the current layer name as the map would persist it
        current_layer_name = [None]

        def update_side_effect(release, map_name):
            current_layer_name[0] = release.title
            return MagicMock()

        mock_update.side_effect = update_side_effect
        mock_get_name.side_effect = lambda map_name=None: current_layer_name[0]

        # Move slider to a non-default position
        param_slider = MockParameter("release_slider", value="5", datatype="GPLong")
        param_slider.valueAsText = "5"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]

        # First call triggers map update (no layer exists yet)
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1)

        # Simulate 5 re-validation cycles with the same value.
        # Layer name now matches → dedup guard blocks updates.
        for _ in range(5):
            tool.updateParameters(parameters)

        # Still only 1 call total
        self.assertEqual(mock_update.call_count, 1)

    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_sequential_position_changes_trigger_updates(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that each distinct slider position change triggers exactly one map update.

        Each move simulates the full ArcGIS Pro cycle:
        1. User moves slider to a new position → triggers update (layer name differs)
        2. Re-validation with same value → blocked (layer name now matches)
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        # Track current layer name dynamically
        current_layer_name = [None]

        def update_side_effect(release, map_name):
            current_layer_name[0] = release.title
            return MagicMock()

        mock_update.side_effect = update_side_effect
        mock_get_name.side_effect = lambda map_name=None: current_layer_name[0]

        param_slider = MockParameter("release_slider", value=str(total_releases), datatype="GPLong")
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]

        # Default position — no layer yet, so update creates it
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1)

        # Move to position 10 — different release
        param_slider.value = "10"
        param_slider.valueAsText = "10"
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 2)

        # Re-validation with same value — blocked
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 2)

        # Move to position 50 — different release
        param_slider.value = "50"
        param_slider.valueAsText = "50"
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 3)

        # Move back to position 10 — different from current, triggers update
        param_slider.value = "10"
        param_slider.valueAsText = "10"
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 4)

    def test_slider_clamping_out_of_range_values(self) -> None:
        """Tests that out-of-range slider values are clamped within valid bounds."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()

        # Test value above maximum — should be clamped to total_releases
        param_slider = MockParameter("release_slider", value=str(len(releases) + 100), datatype="GPLong")
        param_slider.valueAsText = str(len(releases) + 100)
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]
        tool.updateParameters(parameters)

        # Info text always updated — should show newest release (clamped value)
        self.assertIn("Latest Release", param_info.value)
        self.assertIn(releases[0].release_id, param_info.value)

    def test_slider_invalid_valueAsText_defaults_gracefully(self) -> None:
        """Tests that non-integer slider values are handled gracefully with fallback to newest."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()

        param_slider = MockParameter("release_slider", value="not_a_number", datatype="GPLong")
        param_slider.valueAsText = "not_a_number"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]
        tool.updateParameters(parameters)

        # Info text always updated — should fall back to newest
        self.assertIn("Latest Release", param_info.value)
        self.assertIn(releases[0].release_id, param_info.value)

    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_revalidation_after_cim_update_no_flicker(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that ArcGIS Pro re-validation triggered by CIM layer updates does not cause
        flickering or redundant map updates.

        Simulates the real-world scenario where:
        1. User moves slider to position 50 → update fires (layer name differs)
        2. Re-validation with same value → blocked (layer name now matches)
        3. User moves slider to position 80 → update fires again
        4. Re-validation with same value → blocked
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        current_layer_name = [None]

        def update_side_effect(release, map_name):
            current_layer_name[0] = release.title
            return MagicMock()

        mock_update.side_effect = update_side_effect
        mock_get_name.side_effect = lambda map_name=None: current_layer_name[0]

        param_slider = MockParameter("release_slider", value="50", datatype="GPLong")
        param_slider.valueAsText = "50"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]

        # Step 1: User moves slider to position 50
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1, "First user move should trigger one map update")

        # Step 2: CIM change triggers re-validation — layer name now matches
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1, "Re-validation with same release should NOT trigger")

        # Step 3: User moves slider to position 80
        param_slider.value = "80"
        param_slider.valueAsText = "80"
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 2, "Second user move should trigger one map update")

        # Step 4: Another re-validation — blocked
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 2, "Second re-validation should NOT trigger")

    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_dedup_allows_new_positions_during_revalidation(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that re-validation cycles carrying genuinely new slider positions
        ARE processed (improved responsiveness), while same-release cycles are still
        blocked by the layer-name deduplication guard.
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        current_layer_name = [None]

        def update_side_effect(release, map_name):
            current_layer_name[0] = release.title
            return MagicMock()

        mock_update.side_effect = update_side_effect
        mock_get_name.side_effect = lambda map_name=None: current_layer_name[0]

        param_slider = MockParameter("release_slider", value="30", datatype="GPLong")
        param_slider.valueAsText = "30"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]

        # Initial update
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1)

        # Same value → blocked (layer name matches)
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1, "Same release should be blocked")

        # Different value maps to a different release → should be processed
        param_slider.value = "50"
        param_slider.valueAsText = "50"
        tool.updateParameters(parameters)
        self.assertGreaterEqual(mock_update.call_count, 2,
            "Different release should be processed for responsiveness")

    @patch("wayback_addin.map_manager.MapManager.get_wayback_layer_name")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_same_release_always_blocked(self, mock_update: MagicMock, mock_get_name: MagicMock) -> None:
        """Tests that repeated calls resolving to the same release are always blocked.
        This is the core loop-prevention mechanism using layer-name comparison."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()

        current_layer_name = [None]

        def update_side_effect(release, map_name):
            current_layer_name[0] = release.title
            return MagicMock()

        mock_update.side_effect = update_side_effect
        mock_get_name.side_effect = lambda map_name=None: current_layer_name[0]

        param_slider = MockParameter("release_slider", value="30", datatype="GPLong")
        param_slider.valueAsText = "30"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live]

        # First call creates the layer
        tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1)

        # Multiple calls with same value — all blocked by layer-name dedup
        for _ in range(10):
            tool.updateParameters(parameters)
        self.assertEqual(mock_update.call_count, 1, "Same release should never cause redundant updates")


    def test_slider_tool_getParameterInfo_includes_save_checkbox(self) -> None:
        """Tests that WaybackSliderTool parameter list includes the Save checkbox."""
        tool = wayback_pyt.WaybackSliderTool()
        params = tool.getParameterInfo()
        # Now 5 parameters: slider, info, map, live_update, save_current_layer
        self.assertEqual(len(params), 5)

        save_param = params[4]
        self.assertEqual(save_param.name, "save_current_layer")
        self.assertIn(save_param.datatype, ["GPBoolean", "Boolean"])
        self.assertFalse(save_param.value)

    @patch("wayback_addin.map_manager.MapManager.add_standalone_layer")
    def test_slider_save_checkbox_triggers_standalone_layer(self, mock_add: MagicMock) -> None:
        """Tests that checking the Save checkbox triggers add_standalone_layer()."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        mock_add.return_value = MagicMock()

        # Set slider to a non-default position first so it processes
        param_slider = MockParameter("release_slider", value="5", datatype="GPLong")
        param_slider.valueAsText = "5"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")
        param_save = MockParameter("save_current_layer", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live, param_save]
        tool.updateParameters(parameters)

        # add_standalone_layer should have been called
        mock_add.assert_called_once()
        # Checkbox should have been auto-reset to False
        self.assertFalse(param_save.value)

    @patch("wayback_addin.map_manager.MapManager.add_standalone_layer")
    def test_slider_save_checkbox_auto_resets(self, mock_add: MagicMock) -> None:
        """Tests that the Save checkbox auto-resets to False after the action."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        mock_add.return_value = MagicMock()

        param_slider = MockParameter("release_slider", value="10", datatype="GPLong")
        param_slider.valueAsText = "10"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")
        param_save = MockParameter("save_current_layer", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live, param_save]
        tool.updateParameters(parameters)

        # Verify auto-reset
        self.assertFalse(param_save.value)

        # Call again — save should NOT be triggered again (it's now False)
        mock_add.reset_mock()
        tool.updateParameters(parameters)
        mock_add.assert_not_called()

    @patch("wayback_addin.map_manager.MapManager.add_standalone_layer")
    def test_slider_save_checkbox_works_without_slider_change(self, mock_add: MagicMock) -> None:
        """Tests that save works even when the slider position hasn't changed.

        The save action is processed independently of the deduplication guard.
        """
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        mock_add.return_value = MagicMock()

        # First, set slider to position 5 so the tool processes it
        param_slider = MockParameter("release_slider", value="5", datatype="GPLong")
        param_slider.valueAsText = "5"
        param_info = MockParameter("active_release_info", value="", enabled=False)
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=False, datatype="GPBoolean")
        param_save = MockParameter("save_current_layer", value=False, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live, param_save]
        tool.updateParameters(parameters)  # Process the slider position

        # Now check save without changing slider — dedup guard would block slider update,
        # but save should still work
        param_save.value = True
        tool.updateParameters(parameters)

        mock_add.assert_called_once()
        self.assertFalse(param_save.value)

    @patch("wayback_addin.map_manager.MapManager.add_standalone_layer")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_slider_save_on_execute(self, mock_update: MagicMock, mock_add: MagicMock) -> None:
        """Tests that the Save checkbox works during manual execute()."""
        tool = wayback_pyt.WaybackSliderTool()
        releases = tool._get_releases()
        total_releases = len(releases)

        mock_update.return_value = MagicMock()
        mock_add.return_value = MagicMock()

        param_slider = MockParameter("release_slider", value=str(total_releases))
        param_info = MockParameter("active_release_info", value="")
        param_map = MockParameter("target_map", value="CURRENT")
        param_live = MockParameter("live_update", value=True)
        param_save = MockParameter("save_current_layer", value=True, datatype="GPBoolean")

        parameters = [param_slider, param_info, param_map, param_live, param_save]

        with patch("arcpy.AddMessage"):
            tool.execute(parameters, None)

        # Both update and save should have been called
        mock_update.assert_called_once()
        mock_add.assert_called_once()
        # Checkbox should be reset
        self.assertFalse(param_save.value)


    def test_identify_metadata_tool_initialization(self) -> None:
        """Tests IdentifyMetadataTool initialization and attributes."""
        tool = wayback_pyt.IdentifyMetadataTool()
        self.assertEqual(tool.label, "Identify Imagery Metadata")
        self.assertIn("metadata", tool.description.lower())
        self.assertFalse(tool.canRunInBackground)
        # Should have a MapManager instance for map/layer listing
        self.assertIsNotNone(tool.map_manager)

    def test_identify_metadata_tool_has_map_and_layer_params(self) -> None:
        """Tests that IdentifyMetadataTool defines map dropdown, layer dropdown, and output params.

        Note: getParameterInfo() returns [] when HAS_ARCPY is False (standalone test
        environment), so we test the parameter structure by inspecting the method directly.
        """
        tool = wayback_pyt.IdentifyMetadataTool()
        # In standalone (no arcpy) mode, getParameterInfo returns empty
        params = tool.getParameterInfo()
        if wayback_pyt.HAS_ARCPY:
            # When arcpy is available, should have 3 parameters:
            # [0] Target Map, [1] Imagery Layer, [2] Metadata Results (derived)
            self.assertEqual(len(params), 3)

    def test_identify_metadata_update_parameters_handles_empty(self) -> None:
        """Tests that updateParameters handles empty parameter list gracefully."""
        tool = wayback_pyt.IdentifyMetadataTool()
        # Should not raise with empty or short parameter lists
        tool.updateParameters([])
        tool.updateParameters(None)

    def test_identify_metadata_update_parameters_with_altered_map(self) -> None:
        """Tests that updateParameters refreshes layer list when map is altered."""
        tool = wayback_pyt.IdentifyMetadataTool()

        # Create mock parameters
        param_map = MockParameter("target_map", value="Map")
        param_map.altered = True
        param_layer = MockParameter("imagery_layer", value="")
        param_layer.filter = MagicMock()
        param_layer.filter.list = []

        # Mock the list_wayback_layers to return test layers
        with patch.object(
            tool.map_manager,
            "list_wayback_layers",
            return_value=["World Imagery (Wayback 2026-08-05)", "Saved: Imagery 2025-01-15"],
        ):
            tool.updateParameters([param_map, param_layer])

        # Layer dropdown should have been populated
        self.assertEqual(
            param_layer.filter.list,
            ["World Imagery (Wayback 2026-08-05)", "Saved: Imagery 2025-01-15"],
        )
        # Should default to the first (managed) layer
        self.assertEqual(param_layer.value, "World Imagery (Wayback 2026-08-05)")

    def test_identify_metadata_update_parameters_not_refreshed_when_unchanged(self) -> None:
        """Tests that updateParameters does NOT refresh layer list when map is not altered."""
        tool = wayback_pyt.IdentifyMetadataTool()

        param_map = MockParameter("target_map", value="Map")
        param_map.altered = False
        param_layer = MockParameter("imagery_layer", value="Some Layer")
        param_layer.filter = MagicMock()
        param_layer.filter.list = ["Some Layer"]

        with patch.object(tool.map_manager, "list_wayback_layers") as mock_list:
            tool.updateParameters([param_map, param_layer])
            # list_wayback_layers should NOT be called when map is not altered
            mock_list.assert_not_called()

    def test_identify_metadata_update_messages_warns_on_empty_layer(self) -> None:
        """Tests that updateMessages warns when no layer is selected."""
        tool = wayback_pyt.IdentifyMetadataTool()

        param_map = MockParameter("target_map", value="Map")
        param_layer = MockParameter("imagery_layer", value=None)
        param_layer.valueAsText = None

        tool.updateMessages([param_map, param_layer])

        # Should set a warning message about no layer selected
        self.assertIsNotNone(getattr(param_layer, "_warning_message", None))
        self.assertIn("No Wayback", param_layer._warning_message)


class TestWaybackCaptureDateTool(unittest.TestCase):
    """Test suite for WaybackCaptureDateTool parameters, validation, and execution."""

    def setUp(self) -> None:
        """Sets up test releases and local change instances."""
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
        self.local_1 = LocalChangeImageryRelease(
            release=self.release_1,
            capture_date="2023-11-01",
            provider="Maxar",
            accuracy="1m",
            resolution="0.3m",
        )
        self.local_2 = LocalChangeImageryRelease(
            release=self.release_2,
            capture_date="2022-04-12",
            provider="Airbus",
            accuracy="2m",
            resolution="0.5m",
        )

    def test_capture_date_tool_initialization(self) -> None:
        """Tests WaybackCaptureDateTool initialization."""
        tool = wayback_pyt.WaybackCaptureDateTool()
        self.assertEqual(tool.label, "Wayback Capture Date & Local Changes")
        self.assertFalse(tool.canRunInBackground)
        self.assertTrue(tool.isLicensed())

    @patch("wayback_addin.map_manager.MapManager.get_map_view_center_and_scale")
    def test_update_parameters_out_of_scale(self, mock_center_scale: MagicMock) -> None:
        """Tests updateParameters when current map scale exceeds threshold."""
        mock_center_scale.return_value = (-121.4944, 38.5816, 50000.0)

        tool = wayback_pyt.WaybackCaptureDateTool()

        param_map = MockParameter("target_map", value="Map")
        param_scale = MockParameter("scale_threshold", value=24000)
        param_scale.value = 24000
        param_release = MockParameter("release_date", value="")
        param_add_all = MockParameter("add_all_layers", value=False)
        param_details = MockParameter("imagery_details", value="")

        params = [param_map, param_scale, param_release, param_add_all, param_details]
        tool.updateParameters(params)

        self.assertEqual(param_release.filter.list, [])
        self.assertIsNone(param_release.value)
        self.assertIn("exceeds maximum threshold", param_details.value)

    @patch("WaybackImagery.get_local_changes_with_metadata")
    @patch("wayback_addin.map_manager.MapManager.get_map_view_center_and_scale")
    def test_update_parameters_within_scale(
        self, mock_center_scale: MagicMock, mock_changes: MagicMock
    ) -> None:
        """Tests updateParameters populates capture dates and details when within scale."""
        mock_center_scale.return_value = (-121.4944, 38.5816, 10000.0)
        mock_changes.return_value = [self.local_1, self.local_2]

        tool = wayback_pyt.WaybackCaptureDateTool()

        param_map = MockParameter("target_map", value="Map")
        param_scale = MockParameter("scale_threshold", value=24000)
        param_scale.value = 24000
        param_release = MockParameter("release_date", value="")
        param_add_all = MockParameter("add_all_layers", value=False)
        param_details = MockParameter("imagery_details", value="")

        params = [param_map, param_scale, param_release, param_add_all, param_details]
        tool.updateParameters(params)

        self.assertEqual(len(param_release.filter.list), 2)
        self.assertEqual(
            param_release.filter.list[0],
            "2023-11-01 (Wayback 2023-12-07 - Maxar)",
        )
        self.assertEqual(
            param_release.value,
            "2023-11-01 (Wayback 2023-12-07 - Maxar)",
        )
        self.assertIn("Maxar", param_details.value)
        self.assertIn("2023-11-01", param_details.value)

    @patch("wayback_addin.map_manager.MapManager.get_map_view_center_and_scale")
    def test_update_messages_warns_on_scale_exceeded(self, mock_center_scale: MagicMock) -> None:
        """Tests updateMessages sets a warning message when map scale is too high."""
        mock_center_scale.return_value = (-121.4944, 38.5816, 50000.0)

        tool = wayback_pyt.WaybackCaptureDateTool()
        param_map = MockParameter("target_map", value="Map")
        param_scale = MockParameter("scale_threshold", value=24000)
        param_scale.value = 24000

        tool.updateMessages([param_map, param_scale])
        self.assertIsNotNone(param_scale._warning_message)
        self.assertIn("exceeds threshold", param_scale._warning_message)

    @patch("WaybackImagery.get_local_changes_with_metadata")
    @patch("wayback_addin.map_manager.MapManager.get_map_view_center_and_scale")
    @patch("wayback_addin.map_manager.MapManager.update_or_create_layer")
    def test_execute_single_layer(
        self, mock_update: MagicMock, mock_center_scale: MagicMock, mock_changes: MagicMock
    ) -> None:
        """Tests executing tool to apply single capture date release."""
        mock_center_scale.return_value = (-121.4944, 38.5816, 10000.0)
        mock_changes.return_value = [self.local_1, self.local_2]

        tool = wayback_pyt.WaybackCaptureDateTool()

        param_map = MockParameter("target_map", value="Map")
        param_scale = MockParameter("scale_threshold", value=24000)
        param_scale.value = 24000
        param_release = MockParameter(
            "release_date",
            value="2022-04-12 (Wayback 2022-05-18 - Airbus)",
        )
        param_add_all = MockParameter("add_all_layers", value=False)
        param_details = MockParameter("imagery_details", value="")

        params = [param_map, param_scale, param_release, param_add_all, param_details]

        with patch("arcpy.AddMessage"):
            tool.execute(params, None)

        mock_update.assert_called_once_with(self.release_2, "Map")

    @patch("WaybackImagery.get_local_changes_with_metadata")
    @patch("wayback_addin.map_manager.MapManager.get_map_view_center_and_scale")
    @patch("wayback_addin.map_manager.MapManager.add_all_local_change_layers")
    def test_execute_add_all_layers(
        self, mock_add_all: MagicMock, mock_center_scale: MagicMock, mock_changes: MagicMock
    ) -> None:
        """Tests executing tool with add_all_layers checked."""
        mock_center_scale.return_value = (-121.4944, 38.5816, 10000.0)
        mock_changes.return_value = [self.local_1, self.local_2]
        mock_add_all.return_value = [
            "2023-11-01 (Wayback 2023-12-07 - Maxar)",
            "2022-04-12 (Wayback 2022-05-18 - Airbus)",
        ]

        tool = wayback_pyt.WaybackCaptureDateTool()

        param_map = MockParameter("target_map", value="Map")
        param_scale = MockParameter("scale_threshold", value=24000)
        param_scale.value = 24000
        param_release = MockParameter("release_date", value="")
        param_add_all = MockParameter("add_all_layers", value=True)
        param_add_all.value = True
        param_details = MockParameter("imagery_details", value="")

        params = [param_map, param_scale, param_release, param_add_all, param_details]

        with patch("arcpy.AddMessage"):
            tool.execute(params, None)

        mock_add_all.assert_called_once_with([self.local_1, self.local_2], "Map")


if __name__ == "__main__":
    unittest.main()
