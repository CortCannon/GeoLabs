# WorldGeoLabs

WorldGeoLabs is a **Windows-first desktop editor for Minecraft Java (Anvil) worlds** with a focus on **underground features**.

It is built around a **preview-first, layer-based workflow**: you open a world, choose a project area, preview changes in a real-time 3D viewport, organize work into layers, and review edits before moving toward final world application.

The project is aimed at underground world design rather than general terrain sculpting. Current tools and preview systems focus on things like:
- caves and cutaways
- ore and material placement
- rock and underground block editing
- subsurface inspection and visibility filtering
- non-destructive paint-style preview layers

---

## Current status

WorldGeoLabs is **in active development**. This package is the **0.17.1 void-border-safe whole-world geology/resource baseline**.

For very large worlds, a compatible Distant Horizons database is used as read-only navigation context. The real editable Anvil chunk area stays pinned until **Move Working Area** (Ctrl+Shift+M) is requested, avoiding chunk-load hitches while flying around the LOD world.

What works well right now:
- opening Minecraft Java worlds from disk, including the Java 26.1/26.2 namespaced dimension layout
- datapack-driven tall-world height detection plus Java 26.1/26.2 `world_gen_settings.dat` discovery for custom WorldPainter-style worlds
- selecting a project/edit area
- preloading the selected area before entering the 3D editor
- viewing chunk data in a 3D OpenGL viewport
- block visibility filtering
- layer-based preview workflow
- cave and ore preview generators
- paint-preview layers for non-destructive block edits
- a persistent free-3D brush cursor/controller for paint interaction
- a dedicated Paint workspace with brush presets, easier block selection, placement controls, and real block-surface previews
- View-tab block transparency / ghost terrain controls for seeing inside mountains while painting
- Axiom-style viewport input profile: LMB camera rotate, RMB use Paint/tool, MMB block pick, Ctrl+RMB pan, and enhanced WASD fly movement
- project save/load for working session state
- incremental export/apply dialog that writes only changed region files
- independent safe-copy export with post-write chunk verification
- non-GUI diagnostics and core round-trip self-tests
- automatic read-only Distant Horizons LOD discovery and whole-world context rendering
- a bounded real-Anvil editable working area over the DH background, with hysteretic recentering to reduce chunk-loading stutter
- zero-byte, short-header, header-only, and absent-chunk void borders are excluded from world bounds, geological analysis, rendering/edit reads, resource population, and export targets

What is still incomplete or evolving:
- heightmap/light recalculation and broader safe-write hardening
- continued production hardening of paint controls and controller/input separation
- deeper renderer/painter cleanup after the first cursor-state extraction
- continued tuning of resource/deposit presets and geological history models
- full documentation for every subsystem

This means the app is already useful for **inspection and preview editing**, but some pipelines are still milestone-stage rather than final.

---

## Core workflow

WorldGeoLabs is built around this basic flow:

1. **Open a Minecraft world**
2. **Choose a project area** in the map dialog
3. Wait for the selected area to **preload into the 3D viewport**
4. Use the left-side **Layers / Features** stack to organize work
5. Use the right-side **Scene / Preview** and **Paint** panels to configure tools
6. Preview caves, ores, or painted underground edits in 3D
7. Save the session as a **project file** if needed
8. Use **Apply** to export visible/enabled Paint layers to a safe copied world or confirmed in-place write

The editing model is intentionally **layer-first and preview-first**, similar to a composited workflow instead of directly destructively writing to the world on every action.

---


### Whole-world geological resources (0.17.1)

The **Geological Analysis** tab now derives structural uplift, sedimentary basins, erosion/exposure, fault/fracture corridors, hydrothermal potential, paleo-organic basin potential, placer potential, orogenic belts, stable deep-crust proxies, and folded-strata displacement.

After analysis, choose **Generate Geological Resources**. The generator reads `config/geology/world_geology_profile.toml` and creates ordinary non-destructive GeoLabs Paint layers for configurable seams, veins, stockworks, pipes, placers, lenses, and blobs. These layers can span the full analyzed world and export through the same safe incremental Anvil writer.

The geology profile is intentionally editable. Deposit population, suitability weights, depth, size, spacing, host blocks, output material, and formation style can all be changed without modifying Python. Vanilla or modded block IDs are accepted.

## Main features

### 3D viewport
- OpenGL-based chunk viewport
- Axiom-style controls and movement profile available by default in **Scene / Preview → Controls**
- selected-area preload before editing begins
- cutaway and inspection controls
- block visibility masking for clearer underground work
- painter gizmo / brush cursor workflow

### Layer-based editing
- paint layers
- generator preview layers
- reorderable layer stack
- visibility toggles per layer
- saved/restored layer state in project files

### Preview tools
- cave preview
- ore preview
- paint preview for block placement / erase-style edits
- non-destructive session preview before final apply

### Project/session handling
- save current session to a project file
- restore preview, view, paint, and layer state later
- restore block visibility and performance settings

### Apply review
- apply dialog summarizes the current session
- default export creates a timestamped copy of the source world
- incremental export rewrites only `.mca` region files touched by visible/enabled Paint layers
- generator preview export and heightmap recalculation are still future passes

---

## Recovery build quick start

On Windows, the simplest path is:

1. Extract WorldGeoLabs to a short path such as `C:\WGL\WorldGeoLabs`.
2. Run `SETUP_WORLDGEOLABS.bat` once.
3. Run `DIAGNOSTICS.bat`.
4. Run `RUN_WORLDGEOLABS.bat`.

For a real-world read check:

```bat
.venv\Scripts\python.exe -m mcgeo.diagnostics --world "C:\path\to\your\MinecraftWorld"
```

Close Minecraft and WorldPainter before applying edits to an exported Minecraft world.

---

## Installation

### Requirements
- **Windows** is the primary target platform right now
- **Python 3**
- A GPU/driver setup that can run the required PySide6/OpenGL path

### Python dependencies
The project currently uses:
- `PySide6`
- `PyOpenGL`
- `numpy`

Install them from `requirements.txt`.

### Setup
From the project root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m mcgeo
```

---

## Windows install note: PySide6 long paths

If `pip install -r requirements.txt` fails on Windows with a long path error inside `.venv\Lib\site-packages\PySide6\qml\...`, do one or both of the following:

- move the project to a shorter path first, for example:

```text
C:\WGL\WorldGeoLabs
```

- enable **Windows long path support**, then reboot

---

## General use

### Opening a world
- Launch the app
- Choose **Open World**
- Select a Minecraft Java world folder
- Wait for indexing to complete

### Selecting the edit area
After opening a world, choose a project area.

The app uses the selected area to:
- define the working bounds
- preload chunk data for editing
- reduce unnecessary rendering and preview work outside the active area

### Navigating the 3D editor
Once the area is loaded, use the viewport to inspect underground blocks and cutaways. The current control model is still evolving, but the general editing concept is:
- inspect the loaded chunk volume in 3D
- use visibility/cutaway tools to reveal underground content
- use the painter for preview block edits

### Creating features
Use **Create Feature** to add things like:
- Paint layers
- Cave preview layers
- Ore preview layers

These appear in the left-side layer stack and can be toggled or reordered.

### Paint workflow
Paint is used for non-destructive preview edits at real X/Y/Z positions.

Current paint workflow includes:
- selecting or creating a paint layer
- choosing a brush preset or custom brush settings
- selecting a target block/material from the improved Paint > Blocks palette, quick-pick tabs, or a typed `minecraft:block_id`
- choosing an action such as replace/fill/erase-style preview edits
- using the free 3D brush cursor inside the selected volume
- moving cursor depth/height with `Alt+Wheel` or `[ / ]`; the range supports very tall worlds and avoids conflicting with Shift camera descent
- optionally enabling surface snap as an assist, not as the main editing mode
- using **Scene / Preview > Inspect / Cutaway > Block transparency** to make terrain blocks ghosted/see-through while editing inside mountains
- previewing the result in the viewport
- keeping the changes as session preview data until apply is finalized in a later milestone

### Saving a project
Use **Save Project** to save the session state to a project file.

This preserves more than just the world path. It can include the working state of:
- view and preview settings
- layer stack and selection
- paint layers and strokes
- block visibility
- performance-related settings

### Apply
Use **Apply** to review the session.

At the moment, this export path applies visible/enabled Paint layers only. Copy mode creates a true independent world copy and verifies changed chunks after writing. Generator previews and heightmap/light recalculation are still future passes.

---

## Repository layout

Main project structure:

```text
mcgeo/
  core/        core app state, logging, and shared logic
  edit/        editing-layer and editing-core systems
  project/     project/session schema helpers and layer normalization
  rendering/   OpenGL viewport, streaming, mesh building, materials
  ui/          main window, dialogs, panels, widgets
  viewport/    viewport tool/cursor interaction state
  world/       world opening, indexing, and Anvil-world access
```

High-level responsibilities:
- `mcgeo/world` handles Minecraft world reading/indexing
- `mcgeo/rendering` handles viewport drawing, streaming, and preview mesh generation
- `mcgeo/viewport` owns interaction/tool state such as the persistent 3D cursor
- `mcgeo/project` owns session/project normalization helpers
- `mcgeo/ui` contains application workflow and user-facing tools
- `mcgeo/edit` contains layer/edit abstractions used by preview systems

---

## Project files

WorldGeoLabs project files are JSON-based session files used to restore work later.

They are intended to preserve:
- the world path
- selected edit area
- current preview/view configuration
- paint layers and preview stroke state
- layer ordering and visibility
- related session settings

This is for **session recovery and workflow continuity**, not final world export.

---

## Performance notes

Current performance-related design choices include:
- selected-area preload before editing
- process-backed chunk/mesh work in the rendering pipeline
- UI-side debounced filtering in large block lists
- cached/streamed rendering behavior for selected areas

Performance is still an active area of work, especially around:
- painter responsiveness
- preview remesh pressure
- viewport interaction at close range
- reducing expensive repeated hover/pick work

---

## Known limitations

- paint-layer apply/write is functional but heightmap/light recalculation and generator export are not finished yet
- some painter behavior is still under active redesign
- some underground editing systems are preview-only milestones
- the app currently targets Minecraft Java Anvil worlds rather than being a full universal Minecraft editor
- Windows is the main development target right now

---

## Troubleshooting

### The app starts but rendering fails
WorldGeoLabs currently expects the strict OpenGL path to work correctly. If initialization fails, verify:
- GPU drivers are installed and working
- your Python/Qt/OpenGL environment is healthy
- the system can create the expected OpenGL context

### I do not see edits in the viewport
Make sure:
- the correct layer is enabled
- the edit area is loaded
- block visibility filters are not hiding the material you are trying to view
- the current feature/layer is actually active in the stack

### Installed packages fail on Windows
See the **PySide6 long path** note above.

---

## Development notes

This repository is still moving through cleanup and modernization passes.

Recent work has focused on:
- UI modernization
- dock/layout improvements
- project/session restoration
- painter and brush-cursor cleanup
- reducing redundant preview/hover work

The current codebase still contains areas that will benefit from deeper cleanup as development continues.

---

## Roadmap direction

Planned or active next-step areas include:
- deeper renderer/painter architecture cleanup
- stronger safe-write/apply pipeline
- more robust underground editing tools
- broader project/session polish
- continued UI cleanup and performance work

---

## License / repository notes

Add your license here if this repository will be public.

You may also want to add:
- screenshots or GIFs
- example worlds or demo media
- contribution guidelines
- issue templates
- roadmap / milestone links

---

## Summary

WorldGeoLabs is a **preview-first underground Minecraft world editor** for **Minecraft Java Anvil worlds**, built around a **3D viewport + layer stack + project workflow**. It is already useful for underground inspection and preview editing, and it is actively evolving toward a fuller safe-apply editing pipeline.

## 0.16.2 block preview surface pass

This pass changes how painted preview blocks are rendered inside terrain.

The terrain mesher still keeps the fast solid-vs-air greedy mesh for normal terrain, but paint/generated preview materials now also emit material-boundary faces. That means ores or replacement blocks painted inside stone/deepslate can appear as real block surfaces in ghost/x-ray terrain view instead of only being represented by the brush/cross overlay.

The Paint > Blocks option **Render painted blocks as real block surfaces** controls this behavior. It is enabled by default. Terrain transparency itself moved to **Scene / Preview > Inspect / Cutaway > Block transparency** in 0.16.3.



## 0.16.4 paint depth unlock hotfix

This build fixes the v0.16.3 regression where the free 3D paint cursor could appear unable to move through depth. In free paint mode, the visible block under the mouse is now used only to initialize or reacquire cursor depth. After that, Alt+Wheel / bracket depth controls move a persistent camera-ray distance directly, so hover updates no longer overwrite the user's depth adjustment.

Use **Exact surface snap** only when you intentionally want surface-locked behavior. Leave it off for ores, caves, and underground replacement painting. Press `\` to reacquire depth from the visible block under the mouse.

## 0.16.3 view transparency + cursor range pass

This pass moves terrain transparency out of Paint and into the View/Inspect workflow. It also improves block selection with quick-pick groups, category filtering, and typed/custom block IDs. Brush depth range was expanded to ±8192 blocks so tall worlds are no longer constrained by the older ±512 block limit.


## v0.16.5 paint cursor hotfix

Free 3D paint mode now uses a stable camera-facing editing plane with Y controlled by Alt+Wheel, `[`, `]`, PageUp, and PageDown. This removes the camera-distance anchor that could clamp the cursor to one side of the edit volume. Press `\` to reset the plane to the visible block under the mouse; exact surface snap remains optional.

## v0.16.6 cleanup + UI pass

This build focuses on cleanup and UI polish rather than another risky 3D paint cursor patch.

Main changes:
- extracted the central viewport/header into `mcgeo/ui/widgets/workspace_shell.py`
- added a centralized Qt theme in `mcgeo/ui/theme.py`
- added clearer package markers for UI, widget, rendering, and world modules
- added a workflow header with status chips and quick buttons for Open World, Project Area, Create Feature, and Paint
- added `View > Reset Window Layout`
- added `Tools > Show Scene / View Tools`
- cleaned up Paint > Placement wording and added `Reset brush controls`

Known paint note: 3D paint placement still needs a deeper interaction rewrite. This pass leaves that issue documented instead of adding another fragile quick fix.


## Controls / movement

WorldGeoLabs now defaults to an **Axiom-style** viewport profile in the Scene / Preview → Controls tab. This is intended to make navigation feel closer to Minecraft Axiom Editor Mode while still preserving WorldGeoLabs’ selected-area, non-destructive preview workflow.

Default Axiom-style bindings in this build:

- **LMB drag**: rotate camera
- **Ctrl + LMB drag**: arcball/focus orbit around the block or brush under the cursor
- **RMB**: use the active Paint/tool action
- **Ctrl + RMB drag**: pan camera
- **MMB**: pick block under cursor into the Paint block selector
- **Ctrl + MMB drag**: adjust brush radius
- **Mouse wheel**: zoom toward cursor
- **W/A/S/D + Space/Shift**: enhanced fly movement through the selected area
- **Flight Speed** slider: controls movement speed in blocks/second

Legacy controls remain available from the same Controls tab.


## v0.16.14 visibility/focus hotfix

Fixes a blank-viewport regression seen after the section-dirty render pass on tall worlds.

- Camera recentering no longer targets the mathematical midpoint of the build height.
  For a -512..2032 world that midpoint is Y=760, which can point the viewport at empty air.
  It now samples local terrain surface height and focuses near the selected area's surface.
- Full-column voxel meshes publish top-height data again so terrain-aware peel/topmap tools keep
  enough surface information for view logic.
- Empty mesh uploads are no longer counted as successful visible uploads in diagnostics.

## v0.16.13 section dirty rendering pass

This build fixes the paint-stroke reload problem by pushing preview settings and dirty bbox together. A stroke now computes touched 16×16×16 render sections and only queues local preview mesh invalidation for the affected chunk columns. It also adds the `RenderSectionKey(cx, sy, cz)` model and section-aware mesh-builder hook that will become the full voxel streaming unit in the next renderer pass.

## v0.16.15 startup mesh visibility hotfix

Fixes a regression where terrain could flash after selected-area preload and then disappear. The renderer now compares stable preview render signatures, so UI/session reset settings that leave previews off no longer drop all voxel meshes. Local paint dirty-region invalidation remains section-aware.

## v0.16.16 stream-key visibility hotfix

This build fixes the remaining "terrain flashes, then disappears" regression after the section-dirty renderer pass. The GL viewport and stream manager used different `ChunkKey` dataclasses with the same `cx/cz` fields. Direct object comparison made every uploaded GL mesh look outside the stream manager working set, so the next stream tick pruned the visible terrain immediately after upload. Pruning now normalizes keys to plain `(cx, cz)` tuples before comparison.

## v0.16.17 x-ray rewrite pass 1

- Added neighbor-aware voxel meshing so internal chunk-edge walls are not emitted when adjacent chunks contain solid terrain.
- Added shell-style x-ray fade to reduce foggy full-volume transparency.
- Surface/navigation LOD draws much fainter in x-ray to reduce visible chunk/tile grid artifacts.
- Transparency modes now alter draw behavior instead of acting as placeholder labels only.



## v0.16.19 layer-scoped undo/redo

- Added first paint-stroke undo/redo system.
- Undo/redo is scoped to the selected paint layer, matching the GIMP-style layer model.
- Ctrl+Z undoes the last stroke on the selected paint layer only.
- Ctrl+Y or Ctrl+Shift+Z redoes the last undone stroke on the selected paint layer only.
- New strokes clear redo history only for that same layer.
- Undo/redo uses local dirty-bbox remeshing instead of full-map refresh where stroke bounds are available.

## v0.16.18 x-ray seam/grid hotfix

This hotfix corrects the first x-ray rewrite pass. The neighbor-aware mesh code existed, but the greedy mesher still skipped neighbor sampling at chunk borders because it only called the lookup helper for local coordinates. That meant transparent x-ray still showed internal chunk walls. This build routes border samples through the neighbor-aware lookup so internal chunk seams are suppressed.

X-ray drawing also now hides surface/navigation LOD meshes entirely while transparency is active, because those low-detail surface tiles were creating the green grid pattern visible in large-area x-ray screenshots.


## WorldPainter paired-source foundation

Use **Open + WorldPainter** to select an exported Minecraft world and either:

- its original `.world` project through WorldPainter's installed `wpscript` launcher; or
- a pre-extracted WorldGeoLabs WorldPainter analysis package (`.wglwp`, `.zip`, or folder).

WorldPainter supplies terrain intent and broad analysis metadata. Minecraft
Anvil data remains authoritative for actual blocks, NBT, edits, and export.
WorldGeoLabs automatically checks the normal Windows WorldPainter install paths. See `tools/worldpainter_bridge/README.md`.


## Geological Analysis

Open a Minecraft world, preferably paired with its WorldPainter project, then
choose **Analyze Geology**.

The first analysis pass creates disk-backed whole-map datasets for height,
slope, drainage, terrain categories, soil depth, host rock, and sampled
16×16×16 sections. Results are cached under:

```text
<world>/.worldgeolabs/analysis/
```

Minecraft 1.21.1 block categories are editable in:

```text
config/geology/minecraft_1_21_1_block_categories.toml
```

This pass analyzes only. It does not yet generate or export caves or ore
deposits.


## Minecraft Java 26.2 storage compatibility

Java 26.1 reorganized world storage and Java 26.2 uses the new layout. WorldGeoLabs 0.16.26 supports both the new and legacy layouts.

Modern Overworld region path:

```text
<world>/dimensions/minecraft/overworld/region/r.X.Z.mca
```

Legacy Overworld region path remains supported:

```text
<world>/region/r.X.Z.mca
```

The same resolver recognizes the new Nether/End namespaced paths and legacy `DIM-1` / `DIM1` folders. World generation metadata is also read from `data/minecraft/world_gen_settings.dat` when present, with a compatibility fallback for server implementations that wrote it inside the Overworld dimension folder.

The `.mca` Anvil container itself is still used. This pass changes dimension/file discovery rather than replacing the existing chunk NBT reader/writer.


## Distant Horizons large-world context (0.16.27)

For very large maps, WorldGeoLabs now separates **navigation context** from **editable terrain**.

When a compatible `DistantHorizons.sqlite` exists for the opened world, GeoLabs opens it **read-only**, validates the `FullData` schema/format/compression, and progressively creates a coarse whole-world background mesh. Real Minecraft Anvil chunks are then streamed only in a bounded editable working area around the camera.

The usual single-player Overworld location is:

```text
<world>/data/DistantHorizons.sqlite
```

GeoLabs also checks dimension-local and historical layouts and performs a bounded recursive search as a fallback. It never writes to the DH database.

The detailed working area is controlled by **Performance → Editable working radius (voxel detail)**. While DH is active, the old **Fallback surface radius** is not used for far terrain. The detailed working area remains anchored while moving inside it and recenters only near its edge, reducing the constant per-chunk churn that caused navigation stalls.

The DH background is hidden beneath the active working area so paint/geology previews and actual Minecraft chunk geometry remain visually authoritative. X-ray mode also hides the DH background.

If no DH database is present, if its schema is unsupported, or if the first tiles cannot be decoded, GeoLabs automatically keeps its existing Anvil surface-LOD streamer. Set `WGL_DISABLE_DH_LOD=1` before launch to force that fallback for troubleshooting.

`DIAGNOSTICS.bat` now includes a synthetic DH SQLite decode/mesh test. Running diagnostics against a real world also reports whether a compatible DH database was found.


## 0.16.28 — Windows DH SQLite lifecycle fix

- Explicitly closes every read-only Distant Horizons SQLite connection.
- Fixes Windows `WinError 32` when the DH self-test removes its temporary database.
- Prevents live DH rendering from leaving stale SQLite file handles open.
- No world or Distant Horizons database is ever modified by the DH renderer.

## 0.16.30 large-world renderer

This build uses a more detailed continuous Distant Horizons heightfield for world navigation, batches DH tiles to reduce Python/OpenGL draw-call overhead, and skips the expensive real-voxel pass while the camera is roaming away from the pinned edit box. Full Anvil columns are still used inside the active manual-edit box; converting that box to vertical section bricks is the next renderer milestone.


## 0.16.31 dual editing workflow

The large-world editor now has two explicit modes:

- **LOD Edit**: Distant Horizons whole-world context, coarse surface/underground edit overlays, and no real voxel streaming.
- **Detailed Edit**: exact block rendering only inside a movable, resizable 3D section box.

Performance > Rendering contains an adjustable Distant Horizons display-cell setting. Performance > Streaming / Build contains independent X/Z and vertical work-box controls. The DH database is always read-only; Apply resolves LOD-mode paint strokes against the real Minecraft Anvil world.
