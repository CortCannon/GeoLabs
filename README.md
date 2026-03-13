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

WorldGeoLabs is **in active development**.

What works well right now:
- opening Minecraft Java worlds from disk
- selecting a project/edit area
- preloading the selected area before entering the 3D editor
- viewing chunk data in a 3D OpenGL viewport
- block visibility filtering
- layer-based preview workflow
- cave and ore preview generators
- paint-preview layers for non-destructive block edits
- project save/load for working session state
- apply review dialog

What is still incomplete or evolving:
- final safe-write/apply pipeline
- full production-ready paint controls
- deeper renderer/painter cleanup
- broader generator/tool set
- full documentation for every subsystem

This means the app is already useful for **inspection and preview editing**, but some pipelines are still milestone-stage rather than final.

---

## Core workflow

WorldGeoLabs is built around this basic flow:

1. **Open a Minecraft world**
2. **Choose a project area** in the map dialog
3. Wait for the selected area to **preload into the 3D viewport**
4. Use the left-side **Layers / Features** stack to organize work
5. Use the right-side **Scene / Preview** and **Painter** panels to configure tools
6. Preview caves, ores, or painted underground edits in 3D
7. Save the session as a **project file** if needed
8. Use **Apply** to review the current edit session

The editing model is intentionally **layer-first and preview-first**, similar to a composited workflow instead of directly destructively writing to the world on every action.

---

## Main features

### 3D viewport
- OpenGL-based chunk viewport
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
- destination and review UI exist
- final write/apply pipeline is still under development

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

### Painter workflow
Painter is used for non-destructive preview edits.

Current painter workflow includes:
- selecting or creating a paint layer
- choosing an action such as replace/fill/erase-style preview edits
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

At the moment, this is a review-oriented milestone UI rather than the final safe-write implementation.

---

## Repository layout

Main project structure:

```text
mcgeo/
  core/        core app state, logging, and shared logic
  edit/        editing-layer and editing-core systems
  rendering/   OpenGL viewport, streaming, mesh building, materials
  ui/          main window, dialogs, panels, widgets
  world/       world opening, indexing, and Anvil-world access
```

High-level responsibilities:
- `mcgeo/world` handles Minecraft world reading/indexing
- `mcgeo/rendering` handles viewport and preview mesh generation
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

- final apply/write pipeline is not finished yet
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
