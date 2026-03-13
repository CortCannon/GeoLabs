# WorldGeoLabs (preview branch, v0.11e cleanup)

Windows-first desktop app for **preview + apply** editing of **Minecraft Java (Anvil)** worlds (**Minecraft 1.21+**) with a focus on **underground features**.

This build is a cleanup pass on top of the 3D renderer + UX workflow reset branch.

## Current highlights
- **OpenGL chunk-streamed viewport** (strict GL mode, no automatic SW fallback)
- **Selected edit area**: full-area voxel preload + cached redraws before the 3D view becomes interactive
- **GPU material visibility mask** for fast block hide/show
- **Inspect-first workflow** (loading a world does **not** auto-enable cave/ore previews)
- **Non-destructive preview generators** (caves / ores)
- **3D painter preview scaffold**
- **Developer editing-core panel hidden by default**

## Quick start (Windows)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m mcgeo
```

## Basic workflow
1. **Open World**
2. Inspect in the 3D viewport (orbit / pan / zoom)
3. Use **Create Feature…** to opt into:
   - Paint Layer
   - Cave Generator Preview
   - Ore Generator Preview
4. Adjust cutaway controls in **Inspect / Cutaway**
5. Use **Apply** (safe-write pipeline UI scaffold)

## Notes
- This is still a milestone build. Some editor/apply features are scaffolds and labeled as such.
- Developer/internal tools can be shown from **Tools → Show Developer Tools**.
- If OpenGL initialization or runtime fails in strict mode, fix the GL path (this branch intentionally does not auto-fallback).

## Cleanup pass changes (v0.11e)
- Removed packaging leftovers (`__pycache__`, overlay/merge helper artifacts) from the distributable.
- Cleared stale Editing Core session state when opening a new world (prevents dev-layer carryover between worlds).
- Simplified default paint layer naming (`Paint Layer`).
- Updated README to match the current UX/reset + strict-GL behavior.


Patch notes (v0.12c): fixed painter LMB interaction in GL viewport so LMB paints when Painter is enabled (Shift+LMB or RMB pans).

## Windows install note (PySide6 long paths)
If `pip install -r requirements.txt` fails on Windows with a `No such file or directory` error inside a very long `.venv\Lib\site-packages\PySide6\qml\...` path, do one (or both):
- Move the project to a shorter path (e.g. `C:\\WGL\\WorldGeoLabs`) before creating the venv
- Enable Windows long path support (Group Policy: **Enable Win32 long paths**, or Registry: `LongPathsEnabled=1`) and reboot



Patch notes (v0.15a modernization pass):
- Added a cleaner workspace shell around the 3D viewport with world / area / tool summary actions.
- Added persistent window geometry + dock layout restore via QSettings.
- Wrapped the right-side editor in a scroll area and set more usable dock minimum sizes.
- Refreshed the dark theme for a more professional, consistent desktop UI.
- Debounced block-list filtering and batched list rebuild/filter updates to reduce UI stalls on large material sets.
- Removed old hidden paint target-mode UI leftovers from the painter panel.
