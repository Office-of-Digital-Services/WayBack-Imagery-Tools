# -*- coding: utf-8 -*-
"""ArcGIS Pro Python Toolbox for Esri Wayback Historical Imagery.

Provides interactive time-stepping, date jumping, and dynamic layer updating for
Esri's Wayback World Imagery WMTS service directly within the ArcGIS Pro interface.
"""

import os
import sys
from typing import Any, List, Optional

# Ensure that the bundled wayback_addin package is available for import
toolbox_directory = os.path.dirname(os.path.abspath(__file__))
if toolbox_directory not in sys.path:
    sys.path.insert(0, toolbox_directory)

try:
    import arcpy
    HAS_ARCPY = True
except ImportError:
    HAS_ARCPY = False
    arcpy = None

from wayback_addin.cache import CacheManager
from wayback_addin.change_detector import get_local_changes_with_metadata, scale_to_zoom_level
from wayback_addin.logger import get_logger
from wayback_addin import map_manager
from wayback_addin.models import LocalChangeImageryRelease, WaybackRelease

from six.moves import reload_module as reload
reload(map_manager)
from wayback_addin.map_manager import MapManager

logger = get_logger("wayback_addin.toolbox")

# Constants for action modes
ACTION_STEP_FORWARD: str = "Step Forward (Newer)"
ACTION_STEP_BACKWARD: str = "Step Backward (Older)"
ACTION_JUMP_TO_DATE: str = "Jump to Date"
ACTION_JUMP_TO_LATEST: str = "Jump to Latest Date"
ACTION_JUMP_TO_OLDEST: str = "Jump to Oldest Date"

ALL_ACTION_MODES: list = [
    ACTION_STEP_FORWARD,
    ACTION_STEP_BACKWARD,
    ACTION_JUMP_TO_DATE,
    ACTION_JUMP_TO_LATEST,
    ACTION_JUMP_TO_OLDEST,
]


class Toolbox:
    """ArcGIS Pro Python Toolbox container definition."""

    def __init__(self) -> None:
        """Initializes toolbox metadata and registered geoprocessing tools."""
        self.label = "Wayback Imagery Tools"
        self.alias = "WaybackImagery"
        self.description = (
            "Interactive time-stepping, slider controls, and date navigation tools for Esri Wayback historical aerial imagery."
        )
        self.tools = [
            WaybackStepperTool,
            WaybackSliderTool,
            StepForwardTool,
            StepBackwardTool,
            IdentifyMetadataTool,
            WaybackCaptureDateTool,
        ]


class WaybackStepperTool:
    """Unified Wayback Imagery Stepper Tool.

    Supports stepping forward/backward, direct date selection from a dynamic dropdown,
    and jumping to the newest or oldest historical imagery releases.
    """

    def __init__(self) -> None:
        """Initializes tool metadata."""
        self.label = "Wayback Imagery Stepper"
        self.description = (
            "Interactively advance, rewind, or jump to specific historical imagery dates in the active map."
        )
        self.canRunInBackground = False
        self.cache_manager = CacheManager()

    def getParameterInfo(self) -> list:
        """Defines the tool's input and output geoprocessing parameters.

        Returns:
            List of arcpy.Parameter objects.
        """
        if not HAS_ARCPY:
            return []

        # Parameter 0: Action Mode
        param_action = arcpy.Parameter(
            displayName="Action Mode",
            name="action_mode",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        param_action.filter.type = "ValueList"
        param_action.filter.list = ALL_ACTION_MODES
        param_action.value = ACTION_STEP_FORWARD

        # Parameter 1: Historical Release Date (Dropdown populated dynamically)
        param_date = arcpy.Parameter(
            displayName="Historical Release Date",
            name="release_date",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        param_date.filter.type = "ValueList"
        try:
            releases = self.cache_manager.get_releases()
            param_date.filter.list = [r.formatted_display_name for r in releases]
        except Exception:
            param_date.filter.list = []
        param_date.enabled = False

        # Parameter 2: Target Map
        param_map = arcpy.Parameter(
            displayName="Target Map",
            name="target_map",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        param_map.value = "CURRENT"

        # Parameter 3: Derived Output Status (for ModelBuilder and geoprocessing chaining)
        param_out_status = arcpy.Parameter(
            displayName="Active Release Date",
            name="out_release_date",
            datatype="GPString",
            parameterType="Derived",
            direction="Output",
        )

        return [param_action, param_date, param_map, param_out_status]

    def isLicensed(self) -> bool:
        """Checks if tool is licensed to execute."""
        return True

    def updateParameters(self, parameters: list) -> None:
        """Modifies parameter values and enabled states dynamically before validation.

        Args:
            parameters: List of arcpy.Parameter objects.
        """
        if not parameters or len(parameters) < 3:
            return

        param_action = parameters[0]
        param_date = parameters[1]

        # Ensure date dropdown filter list is populated
        if not param_date.filter.list:
            try:
                releases = self.cache_manager.get_releases()
                param_date.filter.list = [r.formatted_display_name for r in releases]
            except Exception:
                pass

        action_value = param_action.valueAsText or ACTION_STEP_FORWARD

        if action_value == ACTION_JUMP_TO_DATE:
            param_date.enabled = True
            # Default to the newest release if not selected
            if not param_date.value and param_date.filter.list:
                param_date.value = param_date.filter.list[0]
        else:
            param_date.enabled = False

    def updateMessages(self, parameters: list) -> None:
        """Validates parameter inputs and raises geoprocessing errors or warnings.

        Args:
            parameters: List of arcpy.Parameter objects.
        """
        if not parameters or len(parameters) < 2:
            return

        param_action = parameters[0]
        param_date = parameters[1]

        if (param_action.valueAsText == ACTION_JUMP_TO_DATE) and not param_date.valueAsText:
            param_date.setErrorMessage("A Historical Release Date must be selected when using 'Jump to Date'.")

    def execute(self, parameters: list, messages: Any) -> None:
        """Executes the Wayback Imagery navigation operation.

        Args:
            parameters: List of arcpy.Parameter objects.
            messages: Geoprocessing messages object.
        """
        if not HAS_ARCPY:
            raise RuntimeError("ArcPy is required to execute geoprocessing tools.")

        action_mode = parameters[0].valueAsText or ACTION_STEP_FORWARD
        selected_date = parameters[1].valueAsText if len(parameters) > 1 else ""
        target_map_name = (parameters[2].valueAsText if len(parameters) > 2 else "CURRENT") or "CURRENT"

        arcpy.AddMessage(f"Initializing Wayback Imagery Stepper (Action: {action_mode}, Map: {target_map_name})...")
        logger.info(
            "WaybackStepperTool: action_mode='%s', selected_date='%s', map='%s'",
            action_mode,
            selected_date,
            target_map_name,
        )

        manager = MapManager(cache_manager=self.cache_manager)

        try:
            if action_mode == ACTION_STEP_FORWARD:
                success, msg, active_rel = manager.step_forward(target_map_name)
            elif action_mode == ACTION_STEP_BACKWARD:
                success, msg, active_rel = manager.step_backward(target_map_name)
            elif action_mode == ACTION_JUMP_TO_DATE:
                if not selected_date:
                    arcpy.AddError("No release date provided for 'Jump to Date'.")
                    return
                success, msg, active_rel = manager.set_release_by_date(selected_date, target_map_name)
            elif action_mode == ACTION_JUMP_TO_LATEST:
                success, msg, active_rel = manager.jump_to_latest(target_map_name)
            elif action_mode == ACTION_JUMP_TO_OLDEST:
                success, msg, active_rel = manager.jump_to_oldest(target_map_name)
            else:
                arcpy.AddError(f"Unrecognized action mode: '{action_mode}'.")
                return

            if success:
                logger.info("WaybackStepperTool success: %s", msg)
                arcpy.AddMessage(f"[SUCCESS] {msg}")
                if active_rel is not None:
                    arcpy.AddMessage(f"Active Release: {active_rel.formatted_display_name}")
                    if len(parameters) > 3:
                        parameters[3].value = active_rel.release_date
            else:
                logger.warning("WaybackStepperTool warning: %s", msg)
                arcpy.AddWarning(f"[WARNING] {msg}")

        except Exception as err:
            logger.error("WaybackStepperTool error: %s", err, exc_info=True)
            arcpy.AddError(f"Wayback Imagery Stepper failed: {err}")
            raise


class WaybackSliderTool:
    """Interactive Wayback Imagery Timeline Slider Tool.

    Provides a graphical slider control to scrub through historical imagery dates.
    As the slider is moved, the tool's validation methods dynamically update the
    Wayback imagery layer in the active map in real time without requiring tool execution.
    """

    def __init__(self) -> None:
        """Initializes tool metadata."""
        self.label = "Wayback Imagery Time Slider"
        self.description = (
            "Interactively preview and scrub through historical imagery dates using a timeline slider. "
            "Moving the slider dynamically updates the active map in real time without running the tool."
        )
        self.canRunInBackground = False
        self.cache_manager = CacheManager()
        self.map_manager = MapManager(cache_manager=self.cache_manager)
        self._releases_cache: Optional[List[WaybackRelease]] = None
        self.releases = self._get_releases()

    def _get_releases(self) -> List[WaybackRelease]:
        """Retrieves and caches the list of historical releases."""
        if self._releases_cache is None:
            try:
                self._releases_cache = self.cache_manager.get_releases()
            except Exception:
                self._releases_cache = []
        return self._releases_cache

    def getParameterInfo(self) -> list:
        """Defines the tool's input and output geoprocessing parameters with a slider control.

        Returns:
            List of arcpy.Parameter objects.
        """

        if not HAS_ARCPY:
            return []

        releases = self.releases
        total_releases = len(releases)
        max_slider_val = total_releases if total_releases > 0 else 1

        # Parameter 0: Release Timeline Slider
        # GPLong parameter with Range filter and slider control CLSID
        param_slider = arcpy.Parameter(
            displayName="Imagery Date Slider (Oldest -> Newest)",
            name="release_slider",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param_slider.filter.type = "Range"
        param_slider.filter.list = [1, max_slider_val]
        # Set Esri standard slider control CLSID
        param_slider.controlCLSID = "{C8C46E43-3D27-4485-9B38-A49F3AC588D9}"
        # Default to the newest release (highest index on the slider)
        param_slider.value = max_slider_val


        # Parameter 1: Selected Release Information (Read-Only Display)
        param_info = arcpy.Parameter(
            displayName="Active Historical Release",
            name="active_release_info",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        param_info.enabled = True
        if releases:
            newest_rel = releases[0]
            param_info.value = (
                f"{newest_rel.release_date} ({newest_rel.release_id}) [#{max_slider_val} of {total_releases}] (Latest Release)"
            )

        # Parameter 2: Target Map
        param_map = arcpy.Parameter(
            displayName="Target Map",
            name="target_map",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        param_map.value = "CURRENT"

        # Parameter 3: Live Map Update Toggle
        param_live = arcpy.Parameter(
            displayName="Live Update Map on Slide",
            name="live_update",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        param_live.value = True

        # Parameter 4: Save Current Layer Checkbox
        # When checked, creates a standalone frozen copy of the current imagery release
        # as an independent layer, then auto-resets to unchecked.
        param_save = arcpy.Parameter(
            displayName="Save Current Layer",
            name="save_current_layer",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        param_save.value = False

        return [param_slider, param_info, param_map, param_live, param_save]

    def isLicensed(self) -> bool:
        """Checks if tool is licensed to execute."""
        return True

    def updateParameters(self, parameters: list) -> None:
        """Updates parameter values and dynamically applies map layer changes during validation.

        Handles three concerns:
        1. Slider position changes → update the info display and optionally the map layer
        2. Save checkbox → create a standalone frozen copy of the current release
        3. Deduplication → compare target release title against the actual layer name
           in the map's Contents pane rather than relying on instance state (which
           may not persist between ArcGIS Pro validation cycles)

        Args:
            parameters: List of arcpy.Parameter objects.
        """
        if not parameters or len(parameters) < 4:
            return

        param_slider = parameters[0]
        param_info = parameters[1]
        param_map = parameters[2]
        param_live = parameters[3]
        # Save checkbox is parameter 4 (optional — may not exist in older configs)
        param_save = parameters[4] if len(parameters) > 4 else None

        releases = self.releases
        total_releases = len(releases)
        if total_releases == 0:
            return

        # Parse current slider position from the string representation for maximum
        # compatibility — valueAsText always returns a string regardless of internal type
        try:
            slider_val = int(param_slider.valueAsText)
        except (ValueError, TypeError):
            slider_val = total_releases

        # Clamp slider value within valid range [1, total_releases]
        slider_val = max(1, min(total_releases, slider_val))

        # 1-based chronological mapping: 1 = oldest release, total_releases = newest release
        rel_index = total_releases - slider_val
        target_release = releases[rel_index]

        target_map_name = (param_map.valueAsText or "CURRENT").strip() or "CURRENT"

        # Handle "Save Current Layer" checkbox action.
        # This is processed independently of the layer-name dedup check because
        # saving should work even when the slider position hasn't changed.
        if param_save is not None and bool(param_save.value):
            try:
                self.map_manager.add_standalone_layer(target_release, target_map_name)
            except Exception:
                # Silently catch when running outside active ArcGIS Pro GUI context
                pass
            # Auto-reset the checkbox to unchecked after the action completes
            param_save.value = False

        # Update the read-only descriptive info display with release details.
        # We always update the info text so the user sees feedback as they drag,
        # but we guard the expensive map layer update below using the layer name.
        param_info.enabled = True
        is_latest = (rel_index == 0)
        is_oldest = (rel_index == total_releases - 1)
        tag = " (Latest Release)" if is_latest else (" (Oldest Baseline)" if is_oldest else "")
        info_text = f"{target_release.release_date} ({target_release.release_id}) [#{slider_val} of {total_releases}]{tag}"
        param_info.value = info_text

        # Deduplication guard: compare the selected release title against the
        # actual Wayback layer name currently visible in the map's Contents pane.
        # This approach is durable across ArcGIS Pro validation cycles because it
        # reads persisted map state rather than relying on tool instance variables
        # (which may be lost if ArcGIS Pro creates a new tool instance per cycle).
        is_live_enabled = bool(param_live.value) if param_live.value is not None else True
        if is_live_enabled:
            current_layer_name = self.map_manager.get_wayback_layer_name(target_map_name)
            # Only update the map layer if the target release differs from what is
            # currently displayed.  When no Wayback layer exists yet (None), always
            # proceed to create one.
            if current_layer_name != target_release.title:
                try:
                    self.map_manager.update_or_create_layer(target_release, target_map_name)
                except Exception:
                    # Silently catch when running outside active ArcGIS Pro GUI context
                    pass

    def updateMessages(self, parameters: list) -> None:
        """Validates parameters and displays helper messages.

        Args:
            parameters: List of arcpy.Parameter objects.
        """
        if not parameters or len(parameters) < 1:
            return

        param_slider = parameters[0]
        releases = self._get_releases()
        total_releases = len(releases)

        if total_releases > 0:
            try:
                val = int(param_slider.value) if param_slider.value is not None else 0
                if val < 1 or val > total_releases:
                    param_slider.setErrorMessage(f"Release slider index must be between 1 and {total_releases}.")
            except (ValueError, TypeError):
                param_slider.setErrorMessage("Release slider index must be an integer.")

    def execute(self, parameters: list, messages: Any) -> None:
        """Executes the tool if manually triggered, ensuring the chosen release is applied.

        Args:
            parameters: List of arcpy.Parameter objects.
            messages: Geoprocessing messages object.
        """
        if not HAS_ARCPY:
            raise RuntimeError("ArcPy is required to execute geoprocessing tools.")

        releases = self._get_releases()
        total_releases = len(releases)
        if total_releases == 0:
            arcpy.AddError("No Wayback releases available.")
            return

        param_slider = parameters[0]
        target_map_name = (parameters[2].valueAsText if len(parameters) > 2 else "CURRENT") or "CURRENT"

        try:
            slider_val = int(param_slider.value) if param_slider.value is not None else total_releases
        except (ValueError, TypeError):
            slider_val = total_releases

        slider_val = max(1, min(total_releases, slider_val))
        rel_index = total_releases - slider_val
        target_release = releases[rel_index]

        arcpy.AddMessage(
            f"Wayback Time Slider: Setting imagery layer to {target_release.formatted_display_name} on map '{target_map_name}'..."
        )
        map_manager = MapManager(cache_manager=self.cache_manager)
        try:
            map_manager.update_or_create_layer(target_release, target_map_name)
            arcpy.AddMessage(f"[SUCCESS] Updated Wayback imagery layer to {target_release.formatted_display_name}.")
        except Exception as err:
            arcpy.AddError(f"Failed to update Wayback imagery layer: {err}")
            raise

        # Handle "Save Current Layer" checkbox on manual execution
        param_save = parameters[4] if len(parameters) > 4 else None
        if param_save is not None and bool(param_save.value):
            try:
                map_manager.add_standalone_layer(target_release, target_map_name)
                arcpy.AddMessage(
                    f"[SUCCESS] Saved standalone layer for {target_release.formatted_display_name}."
                )
            except Exception as err:
                arcpy.AddError(f"Failed to save standalone layer: {err}")
            # Reset the checkbox after the action
            param_save.value = False


class StepForwardTool:
    """Convenience tool for stepping forward (newer release) with single-click ribbon integration."""

    def __init__(self) -> None:
        """Initializes tool metadata."""
        self.label = "Step Forward (Newer Imagery)"
        self.description = "Advance the active map's Wayback imagery layer to the next newer historical date."
        self.canRunInBackground = False
        self.cache_manager = CacheManager()

    def getParameterInfo(self) -> list:
        """Defines parameters for StepForwardTool."""
        if not HAS_ARCPY:
            return []

        param_map = arcpy.Parameter(
            displayName="Target Map",
            name="target_map",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        param_map.value = "CURRENT"

        param_out_status = arcpy.Parameter(
            displayName="Active Release Date",
            name="out_release_date",
            datatype="GPString",
            parameterType="Derived",
            direction="Output",
        )
        return [param_map, param_out_status]

    def isLicensed(self) -> bool:
        return True

    def execute(self, parameters: list, messages: Any) -> None:
        target_map_name = (parameters[0].valueAsText if parameters and parameters[0].valueAsText else "CURRENT") or "CURRENT"
        manager = MapManager(cache_manager=self.cache_manager)
        success, msg, active_rel = manager.step_forward(target_map_name)
        if success:
            arcpy.AddMessage(f"[SUCCESS] {msg}")
            if active_rel is not None and len(parameters) > 1:
                parameters[1].value = active_rel.release_date
        else:
            arcpy.AddWarning(f"[WARNING] {msg}")


class StepBackwardTool:
    """Convenience tool for stepping backward (older release) with single-click ribbon integration."""

    def __init__(self) -> None:
        """Initializes tool metadata."""
        self.label = "Step Backward (Older Imagery)"
        self.description = "Rewind the active map's Wayback imagery layer to the previous older historical date."
        self.canRunInBackground = False
        self.cache_manager = CacheManager()

    def getParameterInfo(self) -> list:
        """Defines parameters for StepBackwardTool."""
        if not HAS_ARCPY:
            return []

        param_map = arcpy.Parameter(
            displayName="Target Map",
            name="target_map",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        param_map.value = "CURRENT"

        param_out_status = arcpy.Parameter(
            displayName="Active Release Date",
            name="out_release_date",
            datatype="GPString",
            parameterType="Derived",
            direction="Output",
        )
        return [param_map, param_out_status]

    def isLicensed(self) -> bool:
        return True

    def execute(self, parameters: list, messages: Any) -> None:
        target_map_name = (parameters[0].valueAsText if parameters and parameters[0].valueAsText else "CURRENT") or "CURRENT"
        manager = MapManager(cache_manager=self.cache_manager)
        success, msg, active_rel = manager.step_backward(target_map_name)
        if success:
            arcpy.AddMessage(f"[SUCCESS] {msg}")
            if active_rel is not None and len(parameters) > 1:
                parameters[1].value = active_rel.release_date
        else:
            arcpy.AddWarning(f"[WARNING] {msg}")


class IdentifyMetadataTool:
    """Queries the Wayback metadata service for the current map center location.

    Provides dropdown selection for the target map and Wayback imagery layer,
    then reads the active map view's center coordinates and queries the metadata
    feature service to return imagery details such as acquisition date, provider,
    source, resolution, and accuracy.
    """

    def __init__(self) -> None:
        """Initializes tool metadata."""
        self.label = "Identify Imagery Metadata"
        self.description = (
            "Query the Wayback metadata service at the current map center to retrieve "
            "imagery details (acquisition date, provider, resolution, accuracy) for a "
            "selected Wayback imagery layer."
        )
        self.canRunInBackground = False
        self.cache_manager = CacheManager()
        self.map_manager = MapManager(cache_manager=self.cache_manager)

    def getParameterInfo(self) -> list:
        """Defines the tool's input and output parameters.

        Parameters:
            0 — Target Map: dropdown of all map names in the project
            1 — Imagery Layer: dropdown of Wayback layers in the selected map
            2 — Metadata Results: derived output with the query results

        Returns:
            List of arcpy.Parameter objects.
        """
        if not HAS_ARCPY:
            return []

        # Parameter 0: Target Map — dynamic dropdown of all maps in the project
        param_map = arcpy.Parameter(
            displayName="Target Map",
            name="target_map",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        param_map.filter.type = "ValueList"
        # Populate with available map names; default to the active map
        try:
            map_names = self.map_manager.list_map_names()
            param_map.filter.list = map_names if map_names else ["CURRENT"]
            # Default to the active map if available
            aprx = self.map_manager.get_project()
            active_map = getattr(aprx, "activeMap", None)
            if active_map is not None and active_map.name in map_names:
                param_map.value = active_map.name
            elif map_names:
                param_map.value = map_names[0]
        except Exception:
            param_map.filter.list = ["CURRENT"]
            param_map.value = "CURRENT"

        # Parameter 1: Imagery Layer — dropdown of Wayback layers in the selected map
        param_layer = arcpy.Parameter(
            displayName="Imagery Layer",
            name="imagery_layer",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        param_layer.filter.type = "ValueList"
        # Pre-populate with layers from the default map
        try:
            selected_map_name = param_map.value or "CURRENT"
            wayback_layers = self.map_manager.list_wayback_layers(selected_map_name)
            param_layer.filter.list = wayback_layers if wayback_layers else []
            # Default to the first layer (managed layer is always first if present)
            if wayback_layers:
                param_layer.value = wayback_layers[0]
        except Exception:
            param_layer.filter.list = []

        # Parameter 2: Output — metadata results (read-only text display)
        param_output = arcpy.Parameter(
            displayName="Metadata Results",
            name="metadata_results",
            datatype="GPString",
            parameterType="Derived",
            direction="Output",
        )

        return [param_map, param_layer, param_output]

    def isLicensed(self) -> bool:
        """Checks if tool is licensed to execute."""
        return True

    def updateParameters(self, parameters: list) -> None:
        """Dynamically updates the imagery layer dropdown when the map selection changes.

        When the user selects a different map from the Target Map dropdown,
        this method repopulates the Imagery Layer dropdown with the Wayback
        layers found in that map.

        Args:
            parameters: List of arcpy.Parameter objects.
        """
        if not parameters or len(parameters) < 2:
            return

        param_map = parameters[0]
        param_layer = parameters[1]

        # Only refresh the layer list when the map parameter has been altered
        if param_map.altered:
            selected_map = param_map.valueAsText or "CURRENT"
            try:
                wayback_layers = self.map_manager.list_wayback_layers(selected_map)
                param_layer.filter.list = wayback_layers if wayback_layers else []
                # Auto-select the first (managed) layer if available
                if wayback_layers:
                    param_layer.value = wayback_layers[0]
                else:
                    param_layer.value = None
            except Exception:
                param_layer.filter.list = []
                param_layer.value = None

    def updateMessages(self, parameters: list) -> None:
        """Validates parameters and displays helper messages.

        Args:
            parameters: List of arcpy.Parameter objects.
        """
        if not parameters or len(parameters) < 2:
            return

        param_layer = parameters[1]
        if not param_layer.valueAsText:
            param_layer.setWarningMessage(
                "No Wayback imagery layer selected. "
                "Please add a Wayback layer using the Slider or Stepper tool first."
            )

    def execute(self, parameters: list, messages: Any) -> None:
        """Executes the metadata identify query.

        Reads the active map view's center coordinates, determines the release
        from the selected Wayback layer, queries the metadata service, and
        outputs the results.

        Args:
            parameters: List of arcpy.Parameter objects.
            messages: ArcGIS geoprocessing messages object.
        """
        if not HAS_ARCPY:
            raise RuntimeError("ArcPy is required to execute geoprocessing tools.")

        target_map_name = (
            (parameters[0].valueAsText if parameters else "CURRENT") or "CURRENT"
        )
        selected_layer_name = (
            parameters[1].valueAsText if len(parameters) > 1 else None
        )

        map_manager = MapManager(cache_manager=self.cache_manager)

        # Resolve the Wayback release from the selected layer.
        # If a specific layer was chosen, find that layer in the map and read
        # its release.  Otherwise fall back to the managed adjustable layer.
        current_release = None
        try:
            target_map = map_manager.get_target_map(target_map_name)
            if selected_layer_name:
                # Find the specific layer by name
                for lyr in target_map.listLayers():
                    if getattr(lyr, "name", "") == selected_layer_name:
                        current_release = map_manager.get_current_release_from_layer(lyr)
                        break
            # Fallback to the managed layer if no match or no layer specified
            if current_release is None:
                current_release = map_manager.get_current_release(target_map_name)
        except Exception as err:
            arcpy.AddError(f"Failed to read Wayback layer: {err}")
            return

        if current_release is None:
            arcpy.AddError(
                "No Wayback imagery layer found in the selected map. "
                "Please use the Wayback Imagery Slider or Stepper to add one first."
            )
            return

        arcpy.AddMessage(
            f"Active Wayback layer: {current_release.title} ({current_release.release_id})"
        )
        if selected_layer_name:
            arcpy.AddMessage(f"Selected layer: {selected_layer_name}")

        # Get the map view center coordinates
        try:
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            # Get the active map view's camera
            mv = aprx.activeView
            if mv is None:
                arcpy.AddError("No active map view. Please open a map view first.")
                return

            camera = mv.camera
            center_x = camera.X
            center_y = camera.Y

            # The camera coordinates are in the map's spatial reference.
            # We need WGS 84 (4326) for the metadata query.
            map_sr = mv.map.spatialReference
            if map_sr is not None and map_sr.factoryCode != 4326:
                # Project the center point to WGS 84
                point = arcpy.PointGeometry(
                    arcpy.Point(center_x, center_y),
                    map_sr,
                )
                projected = point.projectAs(arcpy.SpatialReference(4326))
                longitude = projected.centroid.X
                latitude = projected.centroid.Y
            else:
                longitude = center_x
                latitude = center_y

        except Exception as err:
            arcpy.AddError(f"Failed to read map center coordinates: {err}")
            return

        arcpy.AddMessage(f"Map center: ({longitude:.6f}, {latitude:.6f})")

        # Read the current map scale for the identify endpoint's extent calculation.
        # The metadata service has 14 sublayers at different resolution scales;
        # providing the actual map scale ensures the most relevant sublayer responds.
        map_scale = None
        try:
            if mv is not None:
                map_scale = getattr(mv.camera, "scale", None)
        except Exception:
            pass  # Scale is optional — the identify endpoint uses a default extent

        # Query the metadata service using direct sublayer query + identify fallback
        try:
            zoom_val = scale_to_zoom_level(map_scale) if map_scale else None
            logger.info(
                "IdentifyMetadataTool querying metadata for %s at (%s, %s), scale=%s, zoom=%s",
                current_release.release_id,
                longitude,
                latitude,
                map_scale,
                zoom_val,
            )
            metadata = MapManager.query_metadata(
                current_release, longitude, latitude, map_scale=map_scale, zoom=zoom_val
            )
        except ValueError as err:
            logger.error("IdentifyMetadataTool ValueError: %s", err)
            arcpy.AddError(str(err))
            return
        except RuntimeError as err:
            logger.warning("IdentifyMetadataTool RuntimeError: %s", err)
            arcpy.AddWarning(str(err))
            return
        except Exception as err:
            logger.error("IdentifyMetadataTool Exception: %s", err, exc_info=True)
            arcpy.AddError(f"Metadata query failed: {err}")
            return

        # Format and output the results
        arcpy.AddMessage("=" * 50)
        arcpy.AddMessage("IMAGERY METADATA")
        arcpy.AddMessage("=" * 50)
        arcpy.AddMessage(f"  Release:       {current_release.title}")
        arcpy.AddMessage(f"  Release ID:    {current_release.release_id}")
        arcpy.AddMessage(f"  Location:      ({longitude:.6f}, {latitude:.6f})")
        if map_scale is not None:
            arcpy.AddMessage(f"  Map Scale:     1:{map_scale:,.0f}")
        layer_name = metadata.get("layer_name")
        if layer_name:
            arcpy.AddMessage(f"  Resolution Tier: {layer_name}")
        arcpy.AddMessage(f"  ──────────────────────────────────")
        arcpy.AddMessage(f"  Capture Date:  {metadata.get('date', 'N/A')}")
        arcpy.AddMessage(f"  Provider:      {metadata.get('provider', 'N/A')}")
        arcpy.AddMessage(f"  Source:        {metadata.get('source', 'N/A')}")
        description = metadata.get("description")
        if description and description != metadata.get("provider"):
            arcpy.AddMessage(f"  Description:   {description}")
        arcpy.AddMessage(f"  Resolution:    {metadata.get('resolution', 'N/A')} m")
        arcpy.AddMessage(f"  Accuracy:      {metadata.get('accuracy', 'N/A')} m")
        arcpy.AddMessage("=" * 50)

        # Build the derived output parameter with a comprehensive summary
        summary = (
            f"Release: {current_release.release_id} | "
            f"Location: ({longitude:.4f}, {latitude:.4f}) | "
            f"Date: {metadata.get('date', 'N/A')} | "
            f"Provider: {metadata.get('provider', 'N/A')} | "
            f"Source: {metadata.get('source', 'N/A')} | "
            f"Resolution: {metadata.get('resolution', 'N/A')} m | "
            f"Accuracy: {metadata.get('accuracy', 'N/A')} m"
        )
        # The derived output parameter is the last one (index 2)
        if len(parameters) > 2:
            parameters[2].value = summary


class WaybackCaptureDateTool:
    """Discovers historical Wayback releases with local changes and resolves true capture dates.

    Queries Esri's Wayback tilemap API to identify historical basemap releases that contain
    actual tile updates at the current map view location, resolves the underlying aerial
    acquisition date and provider attribution via the metadata service, and allows adding
    either a single release or all detected releases as separate map layers.
    """

    def __init__(self) -> None:
        """Initializes tool metadata."""
        self.label = "Wayback Capture Date & Local Changes"
        self.description = (
            "Identify historical Wayback imagery releases with local changes in the current viewport "
            "and view actual imagery capture dates rather than basemap publication dates."
        )
        self.canRunInBackground = False
        self.cache_manager = CacheManager()
        self.map_manager = MapManager(cache_manager=self.cache_manager)

    def getParameterInfo(self) -> list:
        """Defines the tool's input and output parameters.

        Parameters:
            0 — Target Map (GPString, Required)
            1 — Maximum Scale Threshold (GPLong, Optional, default 24000)
            2 — Historical Imagery Capture Date (GPString, Required, ValueList)
            3 — Add All Listed Releases as Separate Layers (GPBoolean, Optional, default False)
            4 — Imagery Metadata Details (GPString, Derived, Output)

        Returns:
            List of arcpy.Parameter objects.
        """
        if not HAS_ARCPY:
            return []

        # Parameter 0: Target Map
        param_map = arcpy.Parameter(
            displayName="Target Map",
            name="target_map",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        param_map.filter.type = "ValueList"
        try:
            map_names = self.map_manager.list_map_names()
            param_map.filter.list = map_names if map_names else ["CURRENT"]
            aprx = self.map_manager.get_project()
            active_map = getattr(aprx, "activeMap", None)
            if active_map is not None and active_map.name in map_names:
                param_map.value = active_map.name
            elif map_names:
                param_map.value = map_names[0]
        except Exception:
            param_map.filter.list = ["CURRENT"]
            param_map.value = "CURRENT"

        # Parameter 1: Maximum Scale Threshold (1:N)
        param_scale = arcpy.Parameter(
            displayName="Maximum Scale Threshold (1:N)",
            name="scale_threshold",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input",
        )
        param_scale.value = 24000

        # Parameter 2: Historical Imagery Capture Date
        param_release = arcpy.Parameter(
            displayName="Historical Imagery Capture Date",
            name="release_date",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        param_release.filter.type = "ValueList"
        param_release.filter.list = []

        # Parameter 3: Add All Releases as Separate Layers
        param_add_all = arcpy.Parameter(
            displayName="Add All Listed Releases as Separate Layers",
            name="add_all_layers",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        param_add_all.value = False

        # Parameter 4: Imagery Details (Output)
        param_details = arcpy.Parameter(
            displayName="Imagery Metadata Details",
            name="imagery_details",
            datatype="GPString",
            parameterType="Derived",
            direction="Output",
        )

        return [param_map, param_scale, param_release, param_add_all, param_details]

    def isLicensed(self) -> bool:
        """Checks if tool is licensed to execute."""
        return True

    def updateParameters(self, parameters: list) -> None:
        """Dynamically validates map scale, detects local tile changes, and populates dropdown."""
        if not parameters or len(parameters) < 5:
            return

        param_map = parameters[0]
        param_scale = parameters[1]
        param_release = parameters[2]
        param_details = parameters[4]

        selected_map = param_map.valueAsText or "CURRENT"
        threshold = param_scale.value if param_scale.value is not None else 24000

        try:
            lon, lat, current_scale = self.map_manager.get_map_view_center_and_scale(selected_map)
        except Exception:
            lon, lat, current_scale = -121.4944, 38.5816, 24000.0

        if current_scale > threshold:
            param_release.filter.list = []
            param_release.value = None
            param_details.value = (
                f"Current map scale (1:{current_scale:,.0f}) exceeds maximum threshold (1:{threshold:,.0f}). "
                "Please zoom in closer to detect local imagery changes."
            )
            return

        # Scale is valid — scan for local changes and resolve metadata
        try:
            local_changes = get_local_changes_with_metadata(
                lon=lon,
                lat=lat,
                scale=current_scale,
                max_scale=threshold,
                cache_manager=self.cache_manager,
            )
            labels = [item.formatted_display_name for item in local_changes]
            param_release.filter.list = labels

            # Ensure a valid selection
            if param_release.value not in labels:
                if labels:
                    param_release.value = labels[0]
                else:
                    param_release.value = None

            # Update imagery details text for selected item
            selected_item = None
            if param_release.value:
                for item in local_changes:
                    if item.formatted_display_name == param_release.value:
                        selected_item = item
                        break

            if selected_item:
                details_text = (
                    f"Capture Date: {selected_item.capture_date or 'Unknown'} | "
                    f"Wayback Release: {selected_item.release.release_date} ({selected_item.release.release_id}) | "
                    f"Provider: {selected_item.provider or 'N/A'} | "
                    f"Resolution: {selected_item.resolution or 'N/A'} m | "
                    f"Accuracy: {selected_item.accuracy or 'N/A'} m"
                )
                param_details.value = details_text
            elif labels:
                param_details.value = f"Found {len(labels)} historical releases with local changes."
        except Exception as exc:
            param_details.value = f"Failed detecting local changes: {exc}"

    def updateMessages(self, parameters: list) -> None:
        """Validates parameters and sets warning messages if out of scale."""
        if not parameters or len(parameters) < 2:
            return

        param_map = parameters[0]
        param_scale = parameters[1]

        selected_map = param_map.valueAsText or "CURRENT"
        threshold = param_scale.value if param_scale.value is not None else 24000

        try:
            lon, lat, current_scale = self.map_manager.get_map_view_center_and_scale(selected_map)
            if current_scale > threshold:
                param_scale.setWarningMessage(
                    f"Current map scale (1:{current_scale:,.0f}) exceeds threshold (1:{threshold:,.0f}). "
                    "Zoom in to quad scale (1:24,000 or closer) to detect local changes."
                )
            else:
                param_scale.clearMessage()
        except Exception:
            pass

    def execute(self, parameters: list, messages: Any) -> None:
        """Executes the WaybackCaptureDateTool."""
        if not HAS_ARCPY:
            return

        param_map = parameters[0]
        param_scale = parameters[1]
        param_release = parameters[2]
        param_add_all = parameters[3]

        target_map_name = param_map.valueAsText or "CURRENT"
        threshold = param_scale.value if param_scale.value is not None else 24000
        selected_label = param_release.valueAsText
        add_all = bool(param_add_all.value) if param_add_all.value is not None else False

        lon, lat, current_scale = self.map_manager.get_map_view_center_and_scale(target_map_name)

        arcpy.AddMessage(f"Analyzing local changes at ({lon:.4f}, {lat:.4f}) at scale 1:{current_scale:,.0f}...")

        local_changes = get_local_changes_with_metadata(
            lon=lon,
            lat=lat,
            scale=current_scale,
            max_scale=threshold,
            cache_manager=self.cache_manager,
        )

        if not local_changes:
            arcpy.AddWarning("No historical releases with local changes detected.")
            return

        if add_all:
            arcpy.AddMessage(f"Batch adding {len(local_changes)} local change releases as separate layers...")
            added_names = self.map_manager.add_all_local_change_layers(local_changes, target_map_name)
            arcpy.AddMessage(f"[SUCCESS] Successfully added {len(added_names)} layers to map '{target_map_name}':")
            for name in added_names:
                arcpy.AddMessage(f"  + {name}")
        else:
            # Find matching release
            target_release = None
            if selected_label:
                for item in local_changes:
                    if item.formatted_display_name == selected_label:
                        target_release = item.release
                        break

            if target_release is None and local_changes:
                target_release = local_changes[0].release

            if target_release:
                self.map_manager.update_or_create_layer(target_release, target_map_name)
                arcpy.AddMessage(f"[SUCCESS] Set Wayback layer to {target_release.formatted_display_name}.")
