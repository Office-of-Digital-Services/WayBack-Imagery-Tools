# ArcGIS Pro Wayback Imagery Add-In - User Guide

## Overview
The **ArcGIS Pro Wayback Imagery Add-In** provides an interactive historical imagery navigation experience directly inside ArcGIS Pro. Using Esri's official Wayback World Imagery WMTS service, the tool allows you to seamlessly step forward or backward through time across 190+ historical imagery releases (spanning from 2014 to present) or jump directly to any historical date without creating duplicate layers in your active map.

---

## Key Features
- **In-Place Layer Updating**: Automatically updates your map's existing Wayback imagery base layer without cluttering your Contents pane with multiple layers.
- **Interactive Stepwise Navigation**: Step forward to newer imagery or rewind backward to older imagery with single-click execution.
- **Direct Date Selection**: Dynamically populated dropdown list containing every historical release date.
- **Ribbon & Toolbar Ready**: Easily pin one-click "Step Forward" and "Step Backward" buttons to your ArcGIS Pro Ribbon or Quick Access Toolbar.
- **Fast Offline Resilience**: Local metadata caching provides instantaneous sub-second response times, with automatic bundled fallback when offline.

---

## Getting Started

### 1. Adding the Toolbox to Your ArcGIS Pro Project
1. Open your project (`.aprx`) in **ArcGIS Pro**.
2. In the **Catalog** pane (View tab -> Catalog Pane), expand **Project**.
3. Right-click **Toolboxes** and select **Add Toolbox**.
4. Browse to the folder containing `WaybackImagery.pyt`, select it, and click **OK**.
5. The **Wayback Imagery Tools** toolbox is now available with five tools:
   - **Wayback Imagery Stepper** (Unified stepping and jumping tool)
   - **Wayback Imagery Time Slider** (Interactive timeline slider with live validation updates)
   - **Step Forward (Newer Imagery)** (Instant 1-click forward)
   - **Step Backward (Older Imagery)** (Instant 1-click rewind)
   - **Identify Imagery Metadata** (Query imagery source details at the map center)
   - **Wayback Capture Date & Local Changes** (Discover local changes and true acquisition dates)

---

## Using the Wayback Imagery Stepper

Open the **Wayback Imagery Stepper** tool from the Geoprocessing pane:

### Action Modes
1. **`Step Forward (Newer)`** *(Default)*:
   - Advances the active map's Wayback layer to the next newer historical release.
   - If no Wayback layer exists in your map, it creates the initial layer set to the latest release date.
   - If you are already on the newest release, the tool keeps the current release active and displays an informational notification.

2. **`Step Backward (Older)`**:
   - Rewinds the active map's Wayback layer to the previous older historical release.
   - If you reach the earliest baseline release (2014), the tool displays an informational notification.

3. **`Jump to Date`**:
   - Enables the **Historical Release Date** dropdown parameter.
   - Select any specific release date (e.g., `2026-08-05 (WB_2026_R07)`) to immediately switch the map's imagery to that date.

4. **`Jump to Latest Date`**:
   - Instantly resets the map's Wayback imagery layer to the most recent historical imagery release.

5. **`Jump to Oldest Date`**:
   - Instantly sets the map's Wayback imagery layer to the earliest available baseline imagery release (February 2014).

### Target Map Selection
- By default, the tool operates on the **`CURRENT`** active map view.
- If working with multiple maps, you can type or select the name of any map in your open project.

---

## Using the Wayback Imagery Time Slider

Open the **Wayback Imagery Time Slider** tool from the Geoprocessing pane:

### Real-Time Interactive Scrubbing
- **Interactive Slider Bar**: Drag the slider from left (oldest historical release from 2014) to right (most recent release).
- **Zero-Execution Map Updates**: As you drag or adjust the slider bar, the tool uses ArcGIS Pro parameter validation to **immediately update the active map layer in real time**. You do **not** need to click "Run". The slider is now more responsive — it processes position changes during validation cycles rather than waiting for you to release the slider.
- **Active Historical Release Indicator**: Displays the formatted date, release identifier (e.g. `WB_2026_R07`), and chronological position (e.g. `[#196 of 196] (Latest Release)`).
- **Live Update Toggle**: Check or uncheck **Live Update Map on Slide** to control whether the map refreshes automatically as you scrub.
- **Docking & Floating**: You can keep the Geoprocessing pane docked alongside your map view for continuous visual exploration across different years.

### Saving a Layer (Standalone Freeze)
- **Save Current Layer**: Check the **Save Current Layer** checkbox to save the current imagery release as an independent frozen layer in your map. The saved layer appears as "Saved: Imagery YYYY-MM-DD" and is separate from the adjustable slider layer — you can continue using the slider to browse other dates while the saved layer remains fixed.
- **Multiple Saves**: You can save multiple different dates. Each save creates a new independent layer, allowing you to compare imagery from different time periods side-by-side.
- **Auto-Reset**: The checkbox automatically unchecks itself after saving, so you can save again at a different slider position without manually unchecking it first.

---

## Adding One-Click Stepping to the ArcGIS Pro Ribbon & Quick Access Toolbar

To achieve a true "time slider" experience with single-click buttons directly in the ArcGIS Pro interface:

### Adding to the Quick Access Toolbar (QAT)
1. In the **Catalog** pane, expand **Toolboxes** -> **Wayback Imagery Tools**.
2. Right-click **Step Forward (Newer Imagery)** and select **Add to Quick Access Toolbar**.
3. Right-click **Step Backward (Older Imagery)** and select **Add to Quick Access Toolbar**.
4. You will now see dedicated forward and backward buttons in the top-left title bar of ArcGIS Pro for rapid imagery stepping.

### Adding to the ArcGIS Pro Ribbon
1. Click the **Project** tab in ArcGIS Pro and select **Options**.
2. In the Options dialog, select **Customize the Ribbon**.
3. Under **Choose commands from**, select **Geoprocessing Tools**.
4. Browse to or search for `Step Forward (Newer Imagery)` and `Step Backward (Older Imagery)`.
5. Under **Customize the Ribbon** on the right side, select the **Map** tab (or create a **New Group** named *Wayback Imagery*).
6. Click **Add** to place the buttons into your ribbon group.
7. Click **OK** to save your customization.

---

## Identifying Imagery Metadata at a Location

The **Identify Imagery Metadata** tool queries the Wayback metadata feature service to return detailed imagery source information at your current map center.

### Using the Identify Imagery Metadata Tool

1. Open the **Identify Imagery Metadata** tool from the **Wayback Imagery Tools** toolbox in the Geoprocessing pane.
2. **Select the Target Map**: The tool automatically lists all maps in your project as a dropdown. It defaults to the active map. Choose any map that contains a Wayback imagery layer.
3. **Select the Imagery Layer**: Once a map is selected, the tool populates a second dropdown with all Wayback imagery layers found in that map — including both the managed adjustable layer and any saved standalone layers. The managed layer is always listed first (as the default).
4. Click **Run**. The tool reads the map view's center coordinates, projects them to WGS 84 if needed, and queries the Wayback metadata service.
5. Results are displayed in the geoprocessing messages pane:
   - **Capture Date**: When the source imagery was acquired (e.g., "04/12/2022")
   - **Provider**: The imagery provider (e.g., "Maxar")
   - **Source**: The satellite or sensor (e.g., "WV02", "GE01")
   - **Resolution Tier**: Which metadata sublayer responded (e.g., "1.2m Resolution Metadata")
   - **Resolution**: Spatial resolution of the imagery in meters
   - **Accuracy**: Positional accuracy in meters
   - **Map Scale**: The current map scale used for the query (when available)

### How Scale-Aware Metadata Works

The Wayback metadata service has 14 sublayers covering different resolution ranges (from 1.9 cm at sublayer 0 to 150 m at sublayer 13). The tool uses the current map scale to compute a synthetic map extent for the `identify` endpoint, which automatically selects the most relevant resolution sublayer. For example:
- At **1:1,000** scale, you'll typically see 30cm or finer resolution metadata
- At **1:50,000** scale, you'll see 4.8m or 10m resolution metadata
- At **1:500,000** or wider, you'll see 150m resolution metadata (TerraColor)

### Layer Description Metadata

Each Wayback imagery layer also includes metadata service information in its layer description. To access it:
1. In the **Contents** pane, right-click the Wayback imagery layer and select **Properties**.
2. In the **General** tab, the **Description** field contains the release date, release ID, and a **Metadata Service URL**.
3. You can use this URL to add the metadata as a separate feature layer in your map for manual point-and-click identification.

### Adding the Metadata Feature Layer Manually
1. Copy the metadata service URL from the layer description (e.g., `https://metadata.maptiles.arcgis.com/arcgis/rest/services/World_Imagery_Metadata_2023_r11/MapServer`).
2. In ArcGIS Pro, go to **Map** tab → **Add Data** → **Data From Path**.
3. Paste the metadata service URL and click **Add**.
4. The metadata feature layer will be added to your map. You can now use ArcGIS Pro's built-in **Identify** tool (on the Map tab) to click on any location and see detailed imagery source information.

### Note on Saved Layers
When you save a standalone layer using the "Save Current Layer" checkbox, the saved layer's description also includes the metadata service URL for easy reference. You can select any saved layer in the Identify Imagery Metadata tool's dropdown to query its metadata.

---

## Using the Wayback Capture Date & Local Changes Tool

The **Wayback Capture Date & Local Changes** tool goes beyond global basemap release dates by analyzing your active map viewport, discovering only the historical Wayback releases that have **actual imagery changes** in your local area, and resolving the **true aerial acquisition date** and vendor attribution.

### Why Ground Capture Dates Matter
Each Esri Wayback basemap release is published on a specific basemap release date (e.g. `2022-05-18`). However, the satellite/aerial photos making up that basemap in your area of interest were captured on different dates (e.g. `2022-04-12`). Furthermore, in many locations, imagery remains unchanged across dozens of consecutive Wayback basemap releases. This tool filters out redundant duplicates and presents only the releases that contain local updates.

### Key Capabilities
- **Local Change Detection**: Queries Esri's Wayback tilemap API (`/tilemap/{releaseNum}/{level}/{row}/{col}`) to identify historical releases with distinct tile content in your viewport.
- **Acquisition Date Discovery**: Automatically queries each changed release's metadata identify endpoint to extract the exact capture date (`SRC_DATE2` / `SRC_DATE`) and vendor (e.g. Maxar, Airbus, USDA).
- **Interactive Dropdown**: Formats each historical change as `YYYY-MM-DD (Wayback YYYY-MM-DD - Provider)` (e.g. `2022-04-12 (Wayback 2022-05-18 - Maxar)`).
- **Scale Guard (Default 1:24,000)**: Protects against date ambiguity at regional scales by enforcing a user-configurable maximum scale threshold (1:24,000 USGS quad scale or closer).
- **Batch Add All Releases**: Check the **Add All Listed Releases as Separate Layers** checkbox to instantiate every detected local change release as a separate, standalone layer in your map for easy swipe comparisons and temporal analysis.

### Step-by-Step Workflow
1. Navigate your map view to your study area of interest and zoom in to quad scale (1:24,000 or closer, e.g. 1:10,000).
2. Open **Wayback Capture Date & Local Changes** in the Geoprocessing pane.
3. Select your **Target Map**.
4. Adjust the **Maximum Scale Threshold** if needed (defaults to `24000`). If your map scale exceeds this threshold, the tool prompts you to zoom in.
5. Review the **Historical Imagery Capture Date** dropdown:
   - Select any specific acquisition date to view detailed metadata in the output summary.
6. **Execution Options**:
   - **Single Layer Update**: Leave *Add All Listed Releases as Separate Layers* unchecked and click **Run** to update or create the primary Wayback layer.
   - **Batch Layer Creation**: Check *Add All Listed Releases as Separate Layers* and click **Run** to add all detected historical releases as individual named layers in your map.

---

## Troubleshooting & Tips

- **First Run Connection**: On the first execution with an active internet connection, the tool queries the authoritative Esri `waybackconfig.json` configuration endpoint (falling back to WMTS Capabilities XML if needed) and caches all release dates locally. Subsequent executions load instantaneously from cache.
- **Offline Use**: If you work in a disconnected or air-gapped network environment, the add-in automatically switches to its bundled offline catalog snapshot.
- **Layer Positioning**: When the tool adds a new Wayback layer to an empty map, it inserts it into the map layer stack so standard vector operational layers remain visible on top.
- **Persistent Activity Logging**: The add-in writes structured operational logs to `wayback_addin.log` in the add-in root directory. If you encounter unexpected behavior or metadata retrieval errors, open `wayback_addin.log` in any text editor to view detailed execution traces and network diagnostics.
