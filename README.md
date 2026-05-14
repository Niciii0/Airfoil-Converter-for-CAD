# Airfoil Converter V6.2

A Windows desktop tool for browsing airfoil coordinate files, building wing station layouts, transforming airfoil sections in 3D, running XFOIL polar analysis, and exporting geometry for CAD or simulation workflows.

<img width="3814" height="1956" alt="image" src="https://github.com/user-attachments/assets/88d6174a-8404-42ac-b2e6-e6ff372a867f" />


The app is built with Python, Tkinter, NumPy, and Matplotlib. It can use XFOIL for polar analysis when the user provides an XFOIL executable. It includes a local airfoil coordinate database and can also download the UIUC airfoil database.



## Features

- Search and filter airfoils, including NACA-focused filters and favorites.
- Add airfoils as editable wing stations.
- Set chord/size, twist, and X/Y/Z offsets per station.
- Live 3D preview with zoom, grid/axes toggles, and adjustable station table.
- Checkbox-style station selection for batch operations.
- Generate simple wing station layouts.
- Blend two checked airfoil stations and insert intermediate blended sections.
- Analyze airfoil geometry: thickness, camber, trailing edge gap, duplicates, and normalization.
- Cleanup tools: normalize chord, repanel, close trailing edge, flip order, smooth, and remove duplicates.
- Run XFOIL polar analysis for selected or batch stations.
- Export polar CSVs and polar plot PNGs.
- Compare airfoil shapes and polar curves.
- Export geometry as:
  - Plain XYZ
  - SolidWorks curve
  - Fusion CSV
  - OpenVSP DAT
  - XFOIL DAT
  - mirrored left/right XYZ
  - wing mesh OBJ
  - wing mesh STL
- Save/load projects.
- Build a standalone Windows app with PyInstaller.

## Quick Start

### Use The Standalone App

Open:

```text
dist/Airfoil Converter V6.2/Airfoil Converter V6.2.exe
```

Keep the full `dist/Airfoil Converter V6.2` folder together. The executable expects its `_internal` folder to remain next to it.

### Run From Source

Install Python 3.11 or newer, then install dependencies:

```powershell
pip install numpy matplotlib pyinstaller
```

Run:

```powershell
python "Airfoil Converter V6.2.py"
```

## Building The Windows App

From the project folder:

```powershell
.\build_v6_2.ps1
```

The build output is created at:

```text
dist/Airfoil Converter V6.2/
```

The app bundles:

The repository includes `Airfoil_DATA.zip`. Extract it to `Airfoil_DATA/` before running from source.
- Tcl/Tk runtime files
- Python libraries required by the app

XFOIL is not bundled in this repository. Download XFOIL separately and choose the executable in the app via `Actions` -> `Choose XFOIL executable...`.

## Project Structure

```text
Airfoil Converter V6.2.py      Main application
Airfoil Converter V6.2.spec    PyInstaller build specification
build_v6_2.ps1                 Build helper script
pyi_tk_runtime.py              Runtime hook for bundled Tcl/Tk
Airfoil_DATA/                  Airfoil coordinate database
NACA 4 digit/                  Additional NACA coordinate files
exports/                       Default source-mode export folder
dist/                          Built standalone app output
build/                         PyInstaller temporary build output
```

## Notes

- User settings and favorites are stored in AppData when running the standalone app.
- XFOIL is GPL software and is not included in this repository. To use polar analysis, download XFOIL from the official source and select `xfoil.exe` in the app.
- XFOIL can fail for difficult geometries or aggressive alpha ranges. V6.2 retries with safer sweep settings, but some airfoils may still need smaller alpha ranges.
- OBJ/STL mesh export connects station curves into a triangulated surface. For best results, use ordered stations and similar point counts.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
