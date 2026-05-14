# Airfoil Converter V6.2 Guide

This guide explains the main workflows in Airfoil Converter V6.2.

## First Launch

When the app opens, the left sidebar contains setup controls and the main workspace is on the right.

- `Setup` contains project, airfoil, geometry, and wing tools.
- `XFOIL` contains polar analysis settings.
- `Export` contains geometry export settings.
- `3D Preview` is the main workspace for stations and geometry.
- `Polar Plot`, `Compare`, `Stats / Cleanup`, and `Polar Scores` show analysis outputs.

The sidebar and the station table are resizable. Drag the pane dividers to adjust the layout.

## Adding Airfoils

1. Choose an airfoil from the `Airfoil` dropdown.
2. Set size, rotation, and offsets.
3. Click `Add`.

The station appears in the station table below the 3D preview.

## Editing Stations

Select one or more station rows in the table.

Available actions:

- `Apply` updates selected rows from the sidebar geometry values.
- `Duplicate` copies selected rows.
- `Mirror Y` creates mirrored stations across the Y axis.
- `Move up` and `Move down` reorder stations.
- `Delete` removes selected rows.

The first table column is a checkbox-style selector:

- click `[ ]` to check a row
- click `[x]` to uncheck it
- use `Check selected` to check highlighted rows
- use `Uncheck all` to clear all checks

Highlighted rows are for editing. Checked rows are for operations such as blending and selected export.

## Blending Two Airfoils

The blend workflow uses two checked station rows.

1. Add or generate at least two stations.
2. Check exactly two rows in the first table column.
3. Click `Blend Checked`.
4. Enter how many new airfoils to insert between the two stations.

The app creates blended `.dat` files in:

```text
exports/blended_airfoils/
```

It also inserts the new blended stations between the two checked stations. Geometry values such as size, twist, and offset are interpolated between the two selected rows.

## Generating A Wing

Click `Generate Wing` and enter:

- number of stations
- span / Y width
- root chord
- tip chord
- sweep
- dihedral
- root twist
- tip twist

The app creates a station layout automatically.

## 3D Preview

The 3D view supports:

- mouse-wheel zoom
- `Fit` / `Reset`
- grid toggle
- axes toggle
- draggable view rotation through Matplotlib

If no stations are present, the preview shows `No stations added`.

## Airfoil Analysis And Cleanup

Open the `Stats / Cleanup` tab.

Select a station row, then click `Analyze`.

The app reports:

- point count
- chord
- max thickness and location
- max camber and location
- leading edge radius estimate
- trailing edge gap
- duplicate steps
- normalization status
- malformed status

Cleanup modes:

- Normalize chord
- Repanel
- Close trailing edge
- Flip order
- Smooth
- Remove duplicates

Cleanup creates a new airfoil file and inserts it as a new station.

## XFOIL Polars

1. Add/select a station.
2. Open the `XFOIL` sidebar tab.
3. Set Reynolds, Mach, Ncrit, and alpha range.
4. Click `Compute selected` or `Compute batch`.

Results appear in:

- `Polar Plot`
- `Polar Scores`

You can export:

- current polar CSV
- current polar plot PNG
- batch polar CSVs

## Comparing Airfoils

Open the `Compare` tab.

- `Compare selected shapes` overlays selected station geometries.
- `Overlay selected polars` overlays computed polar curves.

## Exporting Geometry

Open the `Export` sidebar tab and choose a format:

- Plain XYZ
- SolidWorks Curve
- Fusion CSV
- OpenVSP DAT
- XFOIL DAT
- Mirrored Left/Right XYZ
- Wing Mesh OBJ
- Wing Mesh STL

Use:

- `Export selected geometry` to export checked rows, or highlighted rows if nothing is checked.
- `Export ALL geometry` to export every station.

Mesh export requires at least two stations.

## Keyboard Shortcuts

- `Ctrl+N` add airfoil
- `Ctrl+B` blend two checked stations
- `Ctrl+G` generate wing
- `Ctrl+E` export all
- `Ctrl+K` check highlighted rows
- `Ctrl+U` uncheck all rows
- `Ctrl+S` save project
- `Ctrl+O` load project
- `Ctrl+Z` undo
- `Ctrl+Y` redo
- `Delete` delete selected rows
- `Space` toggle focused row checkbox
- `F5` refresh 3D preview
- `F1` show shortcuts

## Standalone App Notes

When packaged, the app stores user settings and favorites in:

```text
%APPDATA%/Airfoil Converter/
```

The bundled app includes `Airfoil_DATA`, `NACA 4 digit`, and `xfoil.exe`.
