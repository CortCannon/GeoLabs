from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

@dataclass
class UIState:
    # World
    world_path: Optional[Path] = None
    world_name: str = ""
    project_path: Optional[Path] = None
    chunk_bounds: Optional[Tuple[int,int,int,int]] = None  # min_cx, max_cx, min_cz, max_cz
    height_range: Optional[Tuple[int,int]] = None          # min_y, max_y
    spawn_chunk: Optional[Tuple[int,int]] = None           # cx, cz
    edit_area_chunk_bounds: Optional[Tuple[int,int,int,int]] = None  # selected project area in chunks
    edit_area_full_world: bool = False

    # View
    view_mode: str = "Surface (fast)"
    visible_materials: set[int] = field(default_factory=set)  # future GPU mask

    # Paint (preview scaffold)
    paint_mode_enabled: bool = False
    active_paint_layer: str = "Paint Layer"

    # Perf
    render_radius_chunks: int = 12
    near_ring: int = 6
    workers: int = 0  # 0=auto
