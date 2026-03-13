from __future__ import annotations
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from PySide6 import QtCore, QtGui
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QSurfaceFormat

from OpenGL import GL
import ctypes
import array
from collections import OrderedDict

from .camera import OrbitCamera, perspective, look_at, mat4_mul
from .stream_manager import StreamManager
from .gl_resources import compile_shader, link_program, upload_mesh, delete_mesh, VisibilityMask, GLMesh
from mcgeo.world.anvil_reader import AnvilWorld, ChunkModel
from mcgeo.world.palette import is_air

log = logging.getLogger("mcgeo.render.gl")

@dataclass(frozen=True)
class ChunkKey:
    cx: int
    cz: int

class GLViewport(QOpenGLWidget):
    gl_failed = QtCore.Signal(str)
    materials_changed = QtCore.Signal(object)  # list[str]
    paint_hover_changed = QtCore.Signal(dict)
    paint_stroke_committed = QtCore.Signal(dict)

    def __init__(self) -> None:
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        QSurfaceFormat.setDefaultFormat(fmt)

        super().__init__()
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self._world_index = None
        self._stream: Optional[StreamManager] = None
        self._mode = "Surface (fast)"
        self._gl_ok = False
        self._preview_settings: dict = {}
        self._view_settings: dict = {}
        self._drop_all_meshes_pending = False
        self._drop_voxel_meshes_pending = False
        self._drop_voxel_mesh_keys_pending: set[ChunkKey] = set()

        self.camera = OrbitCamera()
        self._last_mouse = None
        self._panning = False
        self._orbiting = False

        # Painter interaction state (viewport-side preview stroke capture)
        self._paint_settings: dict = {}
        self._paint_enabled = False
        self._painting = False
        self._paint_points: list[tuple[float, float, float]] = []
        self._paint_last_world: tuple[float, float, float] | None = None
        self._paint_hover_world: tuple[float, float, float] | None = None
        self._paint_hover_quantized: tuple[int, int, int] | None = None
        self._paint_hover_normal: tuple[float, float, float] | None = None
        self._paint_hover_resolved_pick: str = "plane"
        self._paint_locked_normal: tuple[float, float, float] | None = None
        self._paint_realign_request = False
        self._paint_last_align_mode: str = ""
        self._paint_last_target_hit: dict | None = None
        self._paint_cursor_distance: float | None = None
        self._paint_last_surface_hit_distance: float | None = None
        self._cursor_pos: tuple[float, float] | None = None
        self._pending_hover_pos: tuple[float, float] | None = None
        self._space_navigate = False
        self._dolly_dragging = False

        self._paint_hover_timer = QtCore.QTimer(self)
        self._paint_hover_timer.setSingleShot(True)
        self._paint_hover_timer.setInterval(16)
        self._paint_hover_timer.timeout.connect(self._flush_pending_paint_hover)

        # Performance-tunable runtime knobs
        self._stream_tick_ms = 33
        self._target_fps = 60
        self._max_uploads_per_frame = 64
        self._cull_faces = False  # off until greedy winding is fully validated
        self._cull_state_dirty = False
        self._loading_paused = False

        # Timers
        self._stream_timer = QtCore.QTimer(self)
        self._stream_timer.timeout.connect(self._tick_stream)
        self._stream_timer.start(self._stream_tick_ms)

        self._redraw_timer = QtCore.QTimer(self)
        self._redraw_timer.timeout.connect(self.update)
        self._redraw_timer.start(int(1000 / max(1, self._target_fps)))

        # GPU-resident meshes (GL thread only)
        self._meshes: Dict[ChunkKey, GLMesh] = {}

        # Pending mesh uploads produced by workers; flushed in paintGL where context is current
        self._bulk_queueing_meshes = False
        self._pending_lock = threading.Lock()
        self._pending_meshdata: Dict[ChunkKey, object] = {}
        self._pending_replace_keys: set[ChunkKey] = set()

        self._last_target_chunk = (None, None)

        self._mask = None
        self._mask_vis = {}  # name -> bool
        self._last_mask_size = 0
        self._mask_dirty = False

        self._program = 0
        self._u_mvp = -1
        self._u_mask = -1
        self._u_cut_enabled = -1
        self._u_use_peel = -1
        self._u_peel_y = -1
        self._u_use_zslice = -1
        self._u_z_center = -1
        self._u_z_half = -1
        self._u_use_clipbox = -1
        self._u_clip_min = -1
        self._u_clip_max = -1
        self._u_use_terrain_peel = -1
        self._u_topmap = -1
        self._u_top_origin = -1
        self._u_top_dims = -1
        self._u_plane_enabled = -1
        self._u_plane_axis = -1
        self._u_plane_pos = -1
        self._u_plane_keep_positive = -1

        self._topmap_tex = 0
        self._topmap_dims = (0, 0)
        self._topmap_origin = (0.0, 0.0)
        self._topmap_dirty = True
        self._chunk_top_heights: Dict[ChunkKey, tuple[int, ...]] = {}
        self._last_topmap_build_target = (None, None)

        self._line_program = 0
        self._line_vao = 0
        self._line_vbo = 0
        self._u_line_mvp = -1
        self._line_vertex_count = 0

        # Stats
        self._resident_chunks = 0
        self._inflight_builds = 0
        self._last_frame_draw_ms = 0.0
        self._fps = 0.0
        self._fps_frames = 0
        self._fps_t0 = time.perf_counter()
        self._uploads_last_frame = 0

        self._gl_error_spam_suppressed = False
        self._world_height_range = (-64, 320)

        # CPU-side chunk cache used for painter ray picking (MVP)
        self._pick_world: AnvilWorld | None = None
        self._pick_chunk_cache: "OrderedDict[tuple[int,int], ChunkModel | None]" = OrderedDict()
        self._pick_chunk_cache_limit = 128
        self._edit_area_chunk_bounds: tuple[int, int, int, int] | None = None

    def set_preview_settings(self, settings: dict) -> None:
        new_settings = dict(settings or {})
        if new_settings == self._preview_settings:
            return
        self._preview_settings = new_settings
        if self._stream is not None:
            try:
                self._stream.set_preview_settings(self._preview_settings)
            except Exception:
                log.exception("Failed to apply preview settings to stream manager")
            self._invalidate_preview_meshes_for_rebuild()
        self.update()

    def _invalidate_all_meshes_for_rebuild(self) -> None:
        with self._pending_lock:
            self._pending_meshdata.clear()
            self._pending_replace_keys.clear()
        self._drop_all_meshes_pending = True
        if self._stream is not None:
            try:
                self._stream.invalidate_all()
            except Exception:
                log.exception("Failed to invalidate stream cache")

    def _invalidate_preview_meshes_for_rebuild(self, affected_chunks: Optional[list[tuple[int, int]] | set[tuple[int, int]]] = None) -> None:
        """Drop only preview-sensitive (voxel) meshes, optionally limited to a chunk set.

        Base meshes remain resident so camera moves stay smooth.
        GL deletions are deferred to paintGL where the context is current.
        """
        chunk_filter = None
        if affected_chunks is not None:
            chunk_filter = set()
            for c in affected_chunks:
                try:
                    cx, cz = c  # type: ignore[misc]
                    chunk_filter.add((int(cx), int(cz)))
                except Exception:
                    continue
            if not chunk_filter:
                return

        with self._pending_lock:
            if chunk_filter is None:
                drop_keys = [k for k, md in self._pending_meshdata.items() if getattr(md, "lod", "") == "voxel"]
            else:
                drop_keys = [
                    k for k, md in self._pending_meshdata.items()
                    if getattr(md, "lod", "") == "voxel" and (k.cx, k.cz) in chunk_filter
                ]
            for k in drop_keys:
                self._pending_meshdata.pop(k, None)
                self._pending_replace_keys.discard(k)

        if chunk_filter is None:
            self._drop_voxel_meshes_pending = True
            self._drop_voxel_mesh_keys_pending.clear()
        else:
            self._drop_voxel_mesh_keys_pending.update(ChunkKey(int(cx), int(cz)) for (cx, cz) in chunk_filter)
        self._topmap_dirty = True
    # ---------------- public API ----------------
    def get_performance_settings(self) -> dict:
        workers = self._stream.workers if self._stream else max(1, (os.cpu_count() or 1))
        near_ring = self._stream.near_ring if self._stream else 4
        budget = self._stream.max_schedule_per_update if self._stream else 128
        base_cache = self._stream.base_mesh_cache_limit if self._stream else 4096
        preview_cache = self._stream.preview_mesh_cache_limit if self._stream else 4096
        return {
            "workers": int(workers),
            "schedule_budget": int(budget),
            "stream_tick_ms": int(self._stream_tick_ms),
            "near_ring": int(near_ring),
            "target_fps": int(self._target_fps),
            "max_uploads_per_frame": int(self._max_uploads_per_frame),
            "cull_faces": bool(self._cull_faces),
            "build_backend": (self._stream.backend if self._stream else "processes"),
            "base_mesh_cache_entries": int(base_cache),
            "preview_mesh_cache_entries": int(preview_cache),
        }

    def apply_performance_settings(self, s: dict) -> None:
        try:
            if "stream_tick_ms" in s:
                self._stream_tick_ms = max(10, int(s["stream_tick_ms"]))
                self._stream_timer.setInterval(self._stream_tick_ms)
            if "target_fps" in s:
                self._target_fps = max(1, int(s["target_fps"]))
                self._redraw_timer.setInterval(max(1, int(1000 / self._target_fps)))
            if "max_uploads_per_frame" in s:
                self._max_uploads_per_frame = max(1, int(s["max_uploads_per_frame"]))
            if "cull_faces" in s:
                c = bool(s["cull_faces"])
                if c != self._cull_faces:
                    self._cull_faces = c
                    self._cull_state_dirty = True
            if self._stream is not None:
                # Process backend is fixed in this build (no Qt thread fallback).
                if "workers" in s:
                    self._stream.set_workers(int(s["workers"]))
                if "schedule_budget" in s:
                    self._stream.set_schedule_budget(int(s["schedule_budget"]))
                if "near_ring" in s:
                    near = int(s.get("near_ring", self._stream.near_ring))
                    self._stream.set_rings(near)
                if "base_mesh_cache_entries" in s or "preview_mesh_cache_entries" in s:
                    self._stream.set_cache_limits(
                        base_mesh_entries=s.get("base_mesh_cache_entries"),
                        preview_mesh_entries=s.get("preview_mesh_cache_entries"),
                    )
            log.info("Applied performance settings: %s", self.get_performance_settings())
        except Exception as e:
            log.exception("Failed applying performance settings: %s", e)
        self.update()

    def set_loading_paused(self, paused: bool) -> None:
        paused = bool(paused)
        if paused == self._loading_paused:
            return
        self._loading_paused = paused
        try:
            if paused:
                self._stream_timer.stop()
                self._redraw_timer.stop()
            else:
                if not self._stream_timer.isActive():
                    self._stream_timer.start(self._stream_tick_ms)
                if not self._redraw_timer.isActive():
                    self._redraw_timer.start(int(1000 / max(1, self._target_fps)))
        except Exception:
            log.exception("Failed to toggle loading pause on viewport")
        if not paused:
            try:
                self.update()
            except Exception:
                pass

    def _ensure_gl_ready_for_blocking_preload(self) -> bool:
        if self._gl_ok:
            return True
        try:
            self.show()
        except Exception:
            pass
        try:
            self.update()
            QtCore.QCoreApplication.processEvents()
        except Exception:
            pass
        try:
            self.makeCurrent()
            try:
                _ = GL.glGetString(GL.GL_VERSION)
            finally:
                self.doneCurrent()
        except Exception:
            log.exception("Failed to initialize GL context before blocking preload")
        try:
            QtCore.QCoreApplication.processEvents()
        except Exception:
            pass
        return bool(self._gl_ok)

    def preload_selected_area_voxel_cache(self, bounds: tuple[int, int, int, int] | None = None, *, progress_cb=None, cancel_check=None) -> dict:
        """Blocking startup preload into caches + GPU uploads for the selected area.

        This ensures the first 3D view opens already populated (no camera movement required to reveal chunks).
        """
        if self._stream is None:
            return {"total": 0, "done": 0, "built": 0, "failed": 0, "cancelled": False}
        use_bounds = bounds if bounds is not None else self._edit_area_chunk_bounds
        try:
            if use_bounds is not None:
                self._stream.set_allowed_chunk_bounds(use_bounds)
                if hasattr(self._stream, "set_render_all_allowed_area"):
                    self._stream.set_render_all_allowed_area(True)
        except Exception:
            log.exception("Failed to apply bounds before startup mesh preload")

        summary = self._stream.preload_chunk_bounds_blocking(use_bounds, lod="voxel", progress_cb=progress_cb, cancel_check=cancel_check)

        # Stage cached chunks into the viewport queue (no GL uploads yet).
        stage = {"total": 0, "done": 0, "emitted": 0, "missing": 0, "cancelled": False}
        if not bool(summary.get("cancelled", False)) and hasattr(self._stream, "emit_cached_chunk_bounds"):
            try:
                self._bulk_queueing_meshes = True
                stage = self._stream.emit_cached_chunk_bounds(use_bounds, lod="voxel", progress_cb=progress_cb, cancel_check=cancel_check)
            except Exception:
                log.exception("Failed to stage cached selected-area meshes for display")
            finally:
                self._bulk_queueing_meshes = False

        # Upload staged meshes to the GPU while still in the startup loading phase.
        self._ensure_gl_ready_for_blocking_preload()
        upload = self._flush_pending_mesh_uploads_blocking(progress_cb=progress_cb, cancel_check=cancel_check)

        try:
            self._stream.update()  # keep stream stats/current desired set coherent after preload+staging
        except Exception:
            log.exception("Failed to prime visible set after startup preload")

        self._topmap_dirty = True
        self.update()

        try:
            summary["staged"] = stage
            summary["gpu_upload"] = upload
        except Exception:
            pass
        return summary

    def _flush_pending_mesh_uploads_blocking(self, *, progress_cb=None, cancel_check=None) -> dict:
        """Flush all pending mesh uploads immediately (startup preload reveal path)."""
        if not self._gl_ok and not self._ensure_gl_ready_for_blocking_preload():
            return {"total": 0, "uploaded": 0, "cancelled": False, "reason": "gl_not_ready"}

        with self._pending_lock:
            total = len(self._pending_meshdata)
        if total <= 0:
            return {"total": 0, "uploaded": 0, "cancelled": False}

        def _emit(done: int, total_count: int, msg: str) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb(int(done), int(total_count), str(msg))
            except Exception:
                pass

        cancelled = False
        uploaded = 0
        old_limit = int(self._max_uploads_per_frame)

        try:
            self.makeCurrent()
        except Exception:
            log.exception("Failed to make GL context current for blocking startup uploads")
            return {"total": int(total), "uploaded": 0, "cancelled": False, "reason": "makeCurrent_failed"}

        try:
            _emit(0, total, f"Uploading preloaded chunks to GPU… 0/{total}")
            while True:
                if cancel_check is not None:
                    try:
                        if bool(cancel_check()):
                            cancelled = True
                            break
                    except Exception:
                        pass

                with self._pending_lock:
                    remaining = len(self._pending_meshdata)
                if remaining <= 0:
                    break

                # Use a large temporary batch so startup reveal finishes before interactive mode begins.
                self._max_uploads_per_frame = max(old_limit, remaining)
                self._flush_pending_mesh_uploads()
                uploaded += int(self._uploads_last_frame)
                _emit(uploaded, total, f"Uploading preloaded chunks to GPU… {uploaded}/{total}")

                try:
                    QtCore.QCoreApplication.processEvents()
                except Exception:
                    pass

            try:
                GL.glFinish()
            except Exception:
                pass
        finally:
            self._max_uploads_per_frame = old_limit
            try:
                self.doneCurrent()
            except Exception:
                pass

        self._topmap_dirty = True
        return {"total": int(total), "uploaded": int(uploaded), "cancelled": bool(cancelled)}

    def get_performance_snapshot(self) -> dict:
        with self._pending_lock:
            pending_count = len(self._pending_meshdata)
        snap = self.get_performance_settings()
        cache_stats = {}
        try:
            if self._stream is not None:
                cache_stats = self._stream.get_cache_stats()
        except Exception:
            cache_stats = {}
        snap.update({
            "fps": float(self._fps),
            "draw_ms": float(self._last_frame_draw_ms),
            "resident": int(self._resident_chunks),
            "inflight": int(self._inflight_builds),
            "meshes": int(len(self._meshes)),
            "pending_uploads": int(pending_count),
            "uploads_last_frame": int(self._uploads_last_frame),
            "dirty_voxel_chunks_pending_drop": int(len(self._drop_voxel_mesh_keys_pending)),
            "build_backend": (self._stream.backend.title() if self._stream else "Processes"),
            "cull_faces": "On" if self._cull_faces else "Off",
            "preview_layers": "On" if bool(self._preview_settings.get("enabled")) else "Off",
            "cutaway": "On" if bool((self._view_settings or {}).get("cut_enabled")) else "Off",
            **cache_stats,
        })
        return snap

    def set_world_index(self, world_index) -> None:
        self._world_index = world_index
        try:
            self._pick_world = AnvilWorld(world_index.world_path)
        except Exception:
            self._pick_world = None
        self._pick_chunk_cache.clear()
        try:
            self._world_height_range = tuple(world_index.height_range)
            self._chunk_top_heights.clear()
            self._topmap_dirty = True
            self._last_topmap_build_target = (None, None)
        except Exception:
            self._world_height_range = (-64, 320)
        try:
            sx, sy, sz = world_index.spawn_block
        except Exception:
            sx, sy, sz = (world_index.spawn_chunk[0] * 16 + 8, 80, world_index.spawn_chunk[1] * 16 + 8)
        self.camera.target = (float(sx), float(sy), float(sz))
        self.camera.distance = 140.0
        self.update()

        self._stream = StreamManager(world_index.world_path, near_ring=4, workers=0, preview_settings=self._preview_settings)
        try:
            # Aggressive default for process backend to saturate CPU during initial streaming.
            self._stream.max_schedule_per_update = max(256, self._stream.workers * 48)
            self._stream.set_cache_limits(base_mesh_entries=4096, preview_mesh_entries=4096)
        except Exception:
            pass
        log.info(
            "Stream manager initialized (near_ring=%d voxel, workers=%d, schedule_budget=%d)",
            self._stream.near_ring, self._stream.workers, self._stream.max_schedule_per_update
        )
        self._stream.mesh_ready.connect(self._on_mesh_ready)
        self._stream.stats.connect(self._on_stream_stats)
        self._stream.materials_changed.connect(self._on_materials_changed)
        self._stream.set_target_chunk(world_index.spawn_chunk[0], world_index.spawn_chunk[1])
        try:
            if self._edit_area_chunk_bounds is not None and hasattr(self._stream, "set_allowed_chunk_bounds"):
                self._stream.set_allowed_chunk_bounds(self._edit_area_chunk_bounds)
            if hasattr(self._stream, "set_render_all_allowed_area"):
                self._stream.set_render_all_allowed_area(True)
        except Exception:
            log.exception("Failed to reapply edit-area bounds after stream init")


    def set_edit_area_chunk_bounds(self, bounds: tuple[int, int, int, int] | None) -> None:
        self._edit_area_chunk_bounds = None if bounds is None else tuple(int(v) for v in bounds)
        if self._stream is not None and hasattr(self._stream, "set_allowed_chunk_bounds"):
            try:
                self._stream.set_allowed_chunk_bounds(self._edit_area_chunk_bounds)
                if hasattr(self._stream, "set_render_all_allowed_area"):
                    self._stream.set_render_all_allowed_area(True)
            except Exception:
                log.exception("Failed to set edit-area bounds on stream manager")
        # Drop out-of-bounds resident meshes on the GL side without forcing a full rebuild.
        if self._edit_area_chunk_bounds is not None:
            min_cx, max_cx, min_cz, max_cz = self._edit_area_chunk_bounds
            drop = []
            for k in list(self._meshes.keys()):
                if not (min_cx <= k.cx <= max_cx and min_cz <= k.cz <= max_cz):
                    drop.append(k)
            for k in drop:
                try:
                    delete_mesh(self._meshes.pop(k))
                except Exception:
                    pass
            if drop:
                self._topmap_dirty = True
        self.update()

    def focus_chunk(self, cx: int, cz: int) -> None:
        """Move camera target to the center of a chunk (keeps current camera distance/orbit)."""
        x = float(int(cx) * 16 + 8)
        z = float(int(cz) * 16 + 8)
        y = float(self.camera.target[1]) if hasattr(self, 'camera') else 80.0
        try:
            if self._world_height_range:
                y = float((self._world_height_range[0] + self._world_height_range[1]) * 0.5)
        except Exception:
            pass
        self.camera.target = (x, y, z)
        if self._stream is not None:
            try:
                self._stream.set_target_chunk(int(cx), int(cz))
            except Exception:
                pass
        self.update()

    def set_view_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_view_settings(self, settings: dict) -> None:
        self._view_settings = dict(settings or {})
        self._topmap_dirty = True
        self.update()

    def set_material_visibility(self, vis: dict[str, bool]) -> None:
        self._mask_vis = dict(vis)
        self._mask_dirty = True
        self.update()

    def invalidate_preview_chunks(self, chunks: object) -> None:
        """Invalidate voxel preview meshes for a local chunk set (dirty-region remesh)."""
        normalized: list[tuple[int, int]] = []
        try:
            iterable = chunks if isinstance(chunks, (list, tuple, set)) else list(chunks)  # type: ignore[arg-type]
        except Exception:
            iterable = []
        for c in iterable:
            try:
                if isinstance(c, ChunkKey):
                    normalized.append((int(c.cx), int(c.cz)))
                else:
                    cx, cz = c  # type: ignore[misc]
                    normalized.append((int(cx), int(cz)))
            except Exception:
                continue
        if not normalized:
            return
        if self._stream is not None:
            try:
                self._stream.invalidate_preview_only(normalized)
            except Exception:
                log.exception("Failed to invalidate preview chunk subset in stream manager")
        self._invalidate_preview_meshes_for_rebuild(set(normalized))
        log.info("Queued dirty-region preview remesh for %d chunk(s)", len(set(normalized)))
        self.update()

    def invalidate_preview_block_box(self, bbox: object, padding_blocks: int = 0) -> None:
        """Invalidate voxel preview meshes overlapping an axis-aligned block bbox."""
        try:
            vals = [int(v) for v in list(bbox)]  # type: ignore[arg-type]
            if len(vals) != 6:
                return
            x0, y0, z0, x1, y1, z1 = vals
        except Exception:
            return
        p = max(0, int(padding_blocks))
        mnx, mxx = sorted((x0, x1))
        mnz, mxz = sorted((z0, z1))
        mnx -= p; mxx += p
        mnz -= p; mxz += p
        cminx = math.floor(mnx / 16.0)
        cmaxx = math.floor(mxx / 16.0)
        cminz = math.floor(mnz / 16.0)
        cmaxz = math.floor(mxz / 16.0)
        chunks = [(cx, cz) for cz in range(cminz, cmaxz + 1) for cx in range(cminx, cmaxx + 1)]
        self.invalidate_preview_chunks(chunks)


    def set_paint_settings(self, settings: dict) -> None:
        # Preserve viewport-local quick adjustments when caller sends stale UI settings
        # within the same interaction burst; explicit UI changes still overwrite naturally.
        incoming = dict(settings or {})
        try:
            if self._paint_settings and incoming.get("enabled", None) == self._paint_settings.get("enabled", None):
                if int(incoming.get("size_blocks", 0)) == int(self._paint_settings.get("size_blocks", 0)):
                    incoming["size_blocks"] = int(self._paint_settings.get("size_blocks", incoming.get("size_blocks", 1)))
                for key, cast, default in (("brush_offset_blocks", float, 0.0), ("brush_roll_deg", float, 0.0)):
                    try:
                        if cast(incoming.get(key, default)) == cast(self._paint_settings.get(key, default)):
                            incoming[key] = cast(self._paint_settings.get(key, incoming.get(key, default)))
                    except Exception:
                        pass
        except Exception:
            pass
        self._paint_settings = incoming
        self._paint_enabled = bool(self._paint_settings.get("enabled", False))
        try:
            cur_mode = str(self._paint_settings.get("align_mode", "Follow hit normal (auto)"))
        except Exception:
            cur_mode = ""
        # Reset locked normal when leaving lock mode
        if self._paint_last_align_mode and self._paint_last_align_mode != cur_mode:
            if not cur_mode.lower().startswith("lock"):
                self._paint_locked_normal = None
                self._paint_realign_request = False
        self._paint_last_align_mode = cur_mode
        # If paint was disabled mid-stroke, cancel stroke cleanly.
        if not self._paint_enabled and self._painting:
            self._painting = False
            self._paint_points.clear()
            self._paint_last_world = None
        if not self._paint_enabled:
            self._paint_hover_world = None
            self._paint_hover_quantized = None
            self._paint_hover_normal = None
            self._paint_hover_resolved_pick = "plane"
            self._paint_cursor_distance = None
            self._paint_last_surface_hit_distance = None
            self._pending_hover_pos = None
            self._paint_hover_timer.stop()
        self.update()


    # ---------------- painter interaction ----------------
    def _camera_basis(self) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
        eye = self.camera.eye()
        tx, ty, tz = self.camera.target
        fx, fy, fz = (tx - eye[0], ty - eye[1], tz - eye[2])
        fl = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
        fwd = (fx / fl, fy / fl, fz / fl)

        # right = normalize(cross(fwd, up))
        rx = fwd[1] * 0.0 - fwd[2] * 1.0
        ry = fwd[2] * 0.0 - fwd[0] * 0.0
        rz = fwd[0] * 1.0 - fwd[1] * 0.0
        rl = math.sqrt(rx * rx + ry * ry + rz * rz)
        if rl < 1e-6:
            right = (1.0, 0.0, 0.0)
        else:
            right = (rx / rl, ry / rl, rz / rl)

        # up = normalize(cross(right, fwd))
        ux = right[1] * fwd[2] - right[2] * fwd[1]
        uy = right[2] * fwd[0] - right[0] * fwd[2]
        uz = right[0] * fwd[1] - right[1] * fwd[0]
        ul = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
        up = (ux / ul, uy / ul, uz / ul)
        return fwd, right, up

    def _screen_ray(self, sx: float, sy: float) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        w = max(1, self.width())
        h = max(1, self.height())
        # NDC in [-1,1], y positive up
        ndc_x = (2.0 * float(sx) / float(w)) - 1.0
        ndc_y = 1.0 - (2.0 * float(sy) / float(h))
        fov_y = math.radians(55.0)
        tan_half = math.tan(fov_y * 0.5)
        aspect = float(w) / float(h)

        fwd, right, up = self._camera_basis()
        dx = fwd[0] + right[0] * (ndc_x * aspect * tan_half) + up[0] * (ndc_y * tan_half)
        dy = fwd[1] + right[1] * (ndc_x * aspect * tan_half) + up[1] * (ndc_y * tan_half)
        dz = fwd[2] + right[2] * (ndc_x * aspect * tan_half) + up[2] * (ndc_y * tan_half)
        dl = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        return self.camera.eye(), (dx / dl, dy / dl, dz / dl)

    def _intersect_axis_plane(self, sx: float, sy: float, axis: int, plane_pos: float) -> tuple[float, float, float] | None:
        ray = self._screen_ray(sx, sy)
        if not ray:
            return None
        (ox, oy, oz), (dx, dy, dz) = ray
        if axis == 0:
            denom = dx
            if abs(denom) < 1e-6:
                return None
            t = (plane_pos - ox) / denom
        elif axis == 1:
            denom = dy
            if abs(denom) < 1e-6:
                return None
            t = (plane_pos - oy) / denom
        else:
            denom = dz
            if abs(denom) < 1e-6:
                return None
            t = (plane_pos - oz) / denom
        if t <= 0.0:
            return None
        return (ox + dx * t, oy + dy * t, oz + dz * t)

    def _intersect_plane(self, sx: float, sy: float, point: tuple[float, float, float], normal: tuple[float, float, float]) -> tuple[float, float, float] | None:
        ray = self._screen_ray(sx, sy)
        if not ray:
            return None
        (ox, oy, oz), (dx, dy, dz) = ray
        nx, ny, nz = self._vec_normalize(normal, fallback=(0.0, 1.0, 0.0))
        denom = (dx * nx) + (dy * ny) + (dz * nz)
        if abs(denom) < 1e-6:
            return None
        px, py, pz = float(point[0]), float(point[1]), float(point[2])
        t = (((px - ox) * nx) + ((py - oy) * ny) + ((pz - oz) * nz)) / denom
        if t <= 0.0:
            return None
        return (ox + dx * t, oy + dy * t, oz + dz * t)

    def _clamp_paint_point_to_edit_area(self, p: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = float(p[0]), float(p[1]), float(p[2])
        if self._edit_area_chunk_bounds is not None:
            min_cx, max_cx, min_cz, max_cz = self._edit_area_chunk_bounds
            min_x = float(min_cx * 16)
            max_x = float((max_cx + 1) * 16) - 1.0
            min_z = float(min_cz * 16)
            max_z = float((max_cz + 1) * 16) - 1.0
            x = max(min_x, min(max_x, x))
            z = max(min_z, min(max_z, z))
        ymin, ymax = self._world_height_range
        y = max(float(ymin), min(float(ymax), y))
        return (x, y, z)

    def _paint_free_anchor_point(self) -> tuple[float, float, float] | None:
        candidates = (
            self._paint_hover_world,
            self._paint_last_world,
            None if self._paint_last_target_hit is None else self._paint_last_target_hit.get('point'),
        )
        for p in candidates:
            if p is None:
                continue
            try:
                return self._clamp_paint_point_to_edit_area((float(p[0]), float(p[1]), float(p[2])))
            except Exception:
                continue
        return None

    def _distance_eye_to_point(self, p: tuple[float, float, float]) -> float:
        eye = self.camera.eye()
        return self._dist3((float(eye[0]), float(eye[1]), float(eye[2])), (float(p[0]), float(p[1]), float(p[2])))

    def _ray_point_at_distance(self, sx: float, sy: float, distance: float) -> tuple[float, float, float] | None:
        ray = self._screen_ray(sx, sy)
        if not ray:
            return None
        eye, direction = ray
        dist = max(1.0, min(8192.0, float(distance)))
        return (
            float(eye[0]) + float(direction[0]) * dist,
            float(eye[1]) + float(direction[1]) * dist,
            float(eye[2]) + float(direction[2]) * dist,
        )

    def _paint_current_cursor_distance(self) -> float:
        if self._paint_cursor_distance is not None:
            return max(1.0, min(8192.0, float(self._paint_cursor_distance)))
        anchor = self._paint_free_anchor_point()
        if anchor is not None:
            return max(1.0, min(8192.0, self._distance_eye_to_point(anchor)))
        return max(8.0, min(4096.0, float(self.camera.distance)))

    def _paint_free_hit(self, sx: float, sy: float) -> dict | None:
        p = self._ray_point_at_distance(sx, sy, self._paint_current_cursor_distance())
        if p is None:
            return None
        p = self._clamp_paint_point_to_edit_area(p)
        normal = self._paint_hover_normal if self._paint_hover_normal is not None else (0.0, 1.0, 0.0)
        return {'point': p, 'normal': normal, 'resolved_pick': 'free'}

    def _vec_normalize(self, v: tuple[float, float, float], fallback: tuple[float, float, float] = (0.0, 1.0, 0.0)) -> tuple[float, float, float]:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        l = math.sqrt(x * x + y * y + z * z)
        if l < 1e-8:
            return fallback
        return (x / l, y / l, z / l)

    def _vec_rotate_about_axis(self, v: tuple[float, float, float], axis: tuple[float, float, float], degrees: float) -> tuple[float, float, float]:
        ax, ay, az = self._vec_normalize(axis, fallback=(0.0, 1.0, 0.0))
        vx, vy, vz = float(v[0]), float(v[1]), float(v[2])
        th = math.radians(float(degrees))
        ct = math.cos(th)
        st = math.sin(th)
        dot = vx * ax + vy * ay + vz * az
        cx = ay * vz - az * vy
        cy = az * vx - ax * vz
        cz = ax * vy - ay * vx
        rx = vx * ct + cx * st + ax * dot * (1.0 - ct)
        ry = vy * ct + cy * st + ay * dot * (1.0 - ct)
        rz = vz * ct + cz * st + az * dot * (1.0 - ct)
        return (float(rx), float(ry), float(rz))

    def _surface_normal_at(self, x: int, z: int) -> tuple[float, float, float]:
        c = self._pick_surface_column(int(x), int(z))
        if c is None:
            return (0.0, 1.0, 0.0)
        yc = int(c[0])
        hx0 = self._pick_surface_column(int(x) - 1, int(z))
        hx1 = self._pick_surface_column(int(x) + 1, int(z))
        hz0 = self._pick_surface_column(int(x), int(z) - 1)
        hz1 = self._pick_surface_column(int(x), int(z) + 1)
        hxl = int(hx0[0]) if hx0 is not None else yc
        hxr = int(hx1[0]) if hx1 is not None else yc
        hzd = int(hz0[0]) if hz0 is not None else yc
        hzu = int(hz1[0]) if hz1 is not None else yc
        dxh = float(hxr - hxl) * 0.5
        dzh = float(hzu - hzd) * 0.5
        return self._vec_normalize((-dxh, 2.0, -dzh))

    def _pick_cache_get_chunk(self, cx: int, cz: int) -> ChunkModel | None:
        if self._pick_world is None:
            return None
        key = (int(cx), int(cz))
        if key in self._pick_chunk_cache:
            ch = self._pick_chunk_cache.pop(key)
            self._pick_chunk_cache[key] = ch
            return ch
        try:
            ch = self._pick_world.read_chunk(int(cx), int(cz))
        except Exception:
            ch = None
        self._pick_chunk_cache[key] = ch
        while len(self._pick_chunk_cache) > int(self._pick_chunk_cache_limit):
            self._pick_chunk_cache.popitem(last=False)
        return ch

    def _pick_block_name(self, x: int, y: int, z: int) -> str:
        ymin, ymax = self._world_height_range
        if y < int(ymin) or y > int(ymax):
            return "minecraft:air"
        cx = math.floor(x / 16.0)
        cz = math.floor(z / 16.0)
        ch = self._pick_cache_get_chunk(int(cx), int(cz))
        if ch is None:
            return "minecraft:air"
        return ch.get_block(int(x) & 15, int(y), int(z) & 15)

    def _pick_surface_column(self, x: int, z: int) -> tuple[int, str] | None:
        cx = math.floor(x / 16.0)
        cz = math.floor(z / 16.0)
        ch = self._pick_cache_get_chunk(int(cx), int(cz))
        if ch is None:
            return None
        y, name = ch.find_surface_block(int(x) & 15, int(z) & 15)
        return (int(y), str(name))

    def _nearest_block_center_coord(self, v: float) -> int:
        return int(math.floor(float(v) + 0.5))

    def _surface_top_hit_in_column(self, bx: int, bz: int, ray: tuple[tuple[float, float, float], tuple[float, float, float]],
                                   t_enter: float, t_exit: float, max_distance: float) -> dict | None:
        col = self._pick_surface_column(int(bx), int(bz))
        if col is None:
            return None
        sy0, name = col
        if is_air(name):
            return None
        (ox, oy, oz), (dx, dy, dz) = ray
        if abs(dy) < 1e-6:
            return None
        top_y = float(sy0) + 1.0
        t_hit = (top_y - float(oy)) / float(dy)
        if t_hit < max(0.0, float(t_enter)) or t_hit > min(float(max_distance), float(t_exit)):
            return None
        px = float(ox) + float(dx) * t_hit
        pz = float(oz) + float(dz) * t_hit
        if not (float(bx) - 0.5001 <= px <= float(bx) + 0.5001 and float(bz) - 0.5001 <= pz <= float(bz) + 0.5001):
            return None
        return {
            'point': (float(px), float(top_y), float(pz)),
            'normal': self._surface_normal_at(int(bx), int(bz)),
            'resolved_pick': 'surface',
        }

    def _ray_pick_voxel_hit(self, sx: float, sy: float, max_distance: float | None = None) -> dict | None:
        ray = self._screen_ray(sx, sy)
        if not ray:
            return None
        (ox, oy, oz), (dx, dy, dz) = ray
        if max_distance is None:
            max_distance = max(256.0, min(4096.0, float(self.camera.distance) * 8.0))
        eps = 1e-4
        ox += dx * eps
        oy += dy * eps
        oz += dz * eps

        x = math.floor(ox)
        y = math.floor(oy)
        z = math.floor(oz)
        step_x = 1 if dx > 0 else (-1 if dx < 0 else 0)
        step_y = 1 if dy > 0 else (-1 if dy < 0 else 0)
        step_z = 1 if dz > 0 else (-1 if dz < 0 else 0)
        inf = float('inf')
        t_delta_x = abs(1.0 / dx) if abs(dx) > 1e-12 else inf
        t_delta_y = abs(1.0 / dy) if abs(dy) > 1e-12 else inf
        t_delta_z = abs(1.0 / dz) if abs(dz) > 1e-12 else inf

        def _next_boundary(o: float, d: float, cell: int, step: int) -> float:
            if step > 0:
                return (float(cell + 1) - o) / d
            if step < 0:
                return (o - float(cell)) / (-d)
            return inf

        t_max_x = _next_boundary(ox, dx, x, step_x)
        t_max_y = _next_boundary(oy, dy, y, step_y)
        t_max_z = _next_boundary(oz, dz, z, step_z)

        ymin, ymax = self._world_height_range
        t = 0.0
        last_step_axis = -1
        last_step_sign = 0
        for _ in range(20000):
            if t > float(max_distance):
                break
            if int(ymin) <= y <= int(ymax):
                name = self._pick_block_name(int(x), int(y), int(z))
                if not is_air(str(name)):
                    if last_step_axis == 0:
                        normal = (-float(last_step_sign), 0.0, 0.0)
                    elif last_step_axis == 1:
                        normal = (0.0, -float(last_step_sign), 0.0)
                    elif last_step_axis == 2:
                        normal = (0.0, 0.0, -float(last_step_sign))
                    else:
                        normal = self._vec_normalize((-dx, -dy, -dz))
                    return {
                        'point': (float(x) + 0.5, float(y) + 0.5, float(z) + 0.5),
                        'normal': normal,
                        'resolved_pick': 'volume',
                    }
            if t_max_x <= t_max_y and t_max_x <= t_max_z:
                x += step_x
                t = t_max_x
                t_max_x += t_delta_x
                last_step_axis = 0
                last_step_sign = step_x
            elif t_max_y <= t_max_x and t_max_y <= t_max_z:
                y += step_y
                t = t_max_y
                t_max_y += t_delta_y
                last_step_axis = 1
                last_step_sign = step_y
            else:
                z += step_z
                t = t_max_z
                t_max_z += t_delta_z
                last_step_axis = 2
                last_step_sign = step_z
        return None

    def _ray_pick_voxel_world(self, sx: float, sy: float, max_distance: float | None = None) -> tuple[float, float, float] | None:
        hit = self._ray_pick_voxel_hit(sx, sy, max_distance=max_distance)
        if hit is None:
            return None
        return hit.get('point')

    def _ray_pick_surface_hit(self, sx: float, sy: float) -> dict | None:
        ray = self._screen_ray(sx, sy)
        if not ray:
            return None
        (ox, oy, oz), (dx, dy, dz) = ray
        max_distance = max(256.0, min(4096.0, float(self.camera.distance) * 10.0))

        # Traverse surface columns in X/Z using a 2D DDA instead of brute stepping the full 3D ray.
        # This removes a large amount of per-mouse-move work in Visible surface mode and returns
        # an exact top-face intersection so the gizmo projects closer to the cursor.
        ux = float(ox) + 0.5
        uz = float(oz) + 0.5
        bx = int(math.floor(ux))
        bz = int(math.floor(uz))
        step_x = 1 if dx > 1e-9 else (-1 if dx < -1e-9 else 0)
        step_z = 1 if dz > 1e-9 else (-1 if dz < -1e-9 else 0)
        inf = float('inf')
        t_delta_x = abs(1.0 / float(dx)) if abs(dx) > 1e-9 else inf
        t_delta_z = abs(1.0 / float(dz)) if abs(dz) > 1e-9 else inf

        if step_x > 0:
            next_x = float(bx + 1)
            t_max_x = (next_x - ux) / float(dx)
        elif step_x < 0:
            next_x = float(bx)
            t_max_x = (ux - next_x) / (-float(dx))
        else:
            t_max_x = inf

        if step_z > 0:
            next_z = float(bz + 1)
            t_max_z = (next_z - uz) / float(dz)
        elif step_z < 0:
            next_z = float(bz)
            t_max_z = (uz - next_z) / (-float(dz))
        else:
            t_max_z = inf

        t_enter = 0.0
        steps = 0
        max_steps = int(max_distance * 2.0) + 8
        while t_enter <= float(max_distance) and steps < max_steps:
            t_exit = min(t_max_x, t_max_z, float(max_distance))
            hit = self._surface_top_hit_in_column(int(bx), int(bz), ray, t_enter, t_exit, max_distance)
            if hit is not None:
                return hit
            if t_max_x <= t_max_z:
                bx += step_x
                t_enter = t_max_x
                t_max_x += t_delta_x
            else:
                bz += step_z
                t_enter = t_max_z
                t_max_z += t_delta_z
            steps += 1

        hit = self._ray_pick_voxel_hit(sx, sy, max_distance=max_distance)
        if hit is not None:
            px, py, pz = hit.get('point', (0.0, 0.0, 0.0))
            bx = self._nearest_block_center_coord(float(px))
            bz = self._nearest_block_center_coord(float(pz))
            col = self._pick_surface_column(int(bx), int(bz))
            if col is not None and not is_air(col[1]):
                top_y = float(col[0]) + 1.0
                p2 = self._intersect_axis_plane(sx, sy, 1, top_y)
                if p2 is not None:
                    x2, y2, z2 = p2
                    if float(bx) - 0.5001 <= float(x2) <= float(bx) + 0.5001 and float(bz) - 0.5001 <= float(z2) <= float(bz) + 0.5001:
                        return {
                            'point': (float(x2), float(y2), float(z2)),
                            'normal': self._surface_normal_at(int(bx), int(bz)),
                            'resolved_pick': 'surface',
                        }
                return {
                    'point': (float(bx), top_y, float(bz)),
                    'normal': self._surface_normal_at(int(bx), int(bz)),
                    'resolved_pick': 'surface',
                }
            return hit
        return None

    def _ray_pick_surface_world(self, sx: float, sy: float) -> tuple[float, float, float] | None:
        hit = self._ray_pick_surface_hit(sx, sy)
        if hit is None:
            return None
        return hit.get('point')

    def _paint_target_mode_id(self) -> str:
        return "volume"

    def _paint_target_hit(self, sx: float, sy: float) -> dict | None:
        try:
            brush_offset = float(self._paint_settings.get("brush_offset_blocks", 0.0))
        except Exception:
            brush_offset = 0.0

        surface_hit = self._ray_pick_voxel_hit(sx, sy)
        if surface_hit is not None:
            surface_dist = self._distance_eye_to_point(tuple(surface_hit.get('point', (0.0, 0.0, 0.0))))
            self._paint_last_surface_hit_distance = surface_dist
            if abs(brush_offset) <= 1e-6:
                hit = dict(surface_hit)
                hit['point'] = self._clamp_paint_point_to_edit_area(tuple(hit.get('point', (0.0, 0.0, 0.0))))
                hit['resolved_pick'] = str(hit.get('resolved_pick', 'volume'))
                self._paint_cursor_distance = surface_dist
                self._paint_last_target_hit = hit
                return hit
            cursor_dist = max(1.0, min(8192.0, surface_dist - float(brush_offset)))
            self._paint_cursor_distance = cursor_dist
            free_point = self._ray_point_at_distance(sx, sy, cursor_dist)
            if free_point is not None:
                hit = {
                    'point': self._clamp_paint_point_to_edit_area(free_point),
                    'normal': tuple(surface_hit.get('normal', (0.0, 1.0, 0.0))),
                    'resolved_pick': 'free',
                }
                self._paint_last_target_hit = hit
                return hit

        hit = self._paint_free_hit(sx, sy)
        if hit is not None:
            self._paint_last_target_hit = hit
            return hit
        p = self._intersect_plane(sx, sy, tuple(self.camera.target), self._camera_basis()[0])
        if p is None:
            self._paint_last_target_hit = None
            return None
        p = self._clamp_paint_point_to_edit_area(p)
        hit = {'point': p, 'normal': (0.0, 1.0, 0.0), 'resolved_pick': 'free'}
        self._paint_cursor_distance = self._distance_eye_to_point(p)
        self._paint_last_target_hit = hit
        return hit

    def _paint_apply_offset_to_hit(self, hit: dict, sx: float, sy: float) -> dict:
        out = dict(hit or {})
        try:
            offset = float(self._paint_settings.get("brush_offset_blocks", 0.0))
        except Exception:
            offset = 0.0
        if abs(offset) < 1e-6:
            return out
        p = out.get('point')
        if p is None:
            return out
        eye = self.camera.eye()
        d = self._vec_normalize((float(p[0]) - float(eye[0]), float(p[1]) - float(eye[1]), float(p[2]) - float(eye[2])), fallback=(0.0, 0.0, -1.0))
        # Positive = move gizmo toward camera; negative = push it farther away.
        out['point'] = (float(p[0]) - d[0] * offset, float(p[1]) - d[1] * offset, float(p[2]) - d[2] * offset)
        return out

    def _paint_finalize_hit(self, hit: dict | None, sx: float, sy: float) -> dict | None:
        if hit is None:
            self._paint_last_target_hit = None
            return None
        hit2 = self._paint_apply_offset_to_hit(hit, sx, sy)
        self._paint_last_target_hit = hit2
        return hit2

    def _paint_target_world(self, sx: float, sy: float) -> tuple[float, float, float] | None:
        hit = self._paint_target_hit(sx, sy)
        if hit is None:
            return None
        return hit.get('point')

    def _quantize_paint_point(self, p: tuple[float, float, float]) -> tuple[int, int, int]:
        x, y, z = p
        ymin, ymax = self._world_height_range
        yi = int(round(y))
        yi = max(int(ymin), min(int(ymax), yi))
        return (int(round(x)), yi, int(round(z)))

    def _paint_spacing_blocks(self) -> float:
        size_b = max(1, int(self._paint_settings.get("size_blocks", 1)))
        spacing_pct = max(1, int(self._paint_settings.get("spacing_pct_radius", 25)))
        return max(1.0, (size_b * 0.5) * (spacing_pct / 100.0))

    def _dist3(self, a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        dz = a[2] - b[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def _schedule_paint_hover(self, sx: float, sy: float, *, immediate: bool = False) -> None:
        if not self._paint_enabled:
            return
        self._pending_hover_pos = (float(sx), float(sy))
        if immediate:
            self._paint_hover_timer.stop()
            self._flush_pending_paint_hover()
            return
        if not self._paint_hover_timer.isActive():
            self._paint_hover_timer.start()

    def _flush_pending_paint_hover(self) -> None:
        if not self._paint_enabled:
            return
        pos = self._pending_hover_pos or self._cursor_pos
        self._pending_hover_pos = None
        if pos is None or self._painting or self._orbiting or self._panning or self._dolly_dragging:
            return
        self._emit_paint_hover(float(pos[0]), float(pos[1]))

    def _emit_paint_hover(self, sx: float, sy: float) -> None:
        if not self._paint_enabled:
            return
        hit = self._paint_target_hit(sx, sy)
        p = None if hit is None else hit.get('point')
        if p is None:
            self._paint_hover_world = None
            self._paint_hover_quantized = None
            self._paint_hover_normal = None
            self._paint_hover_resolved_pick = "plane"
            self.paint_hover_changed.emit({"valid": False})
            self.update()
            return
        q = self._quantize_paint_point(p)
        self._paint_hover_world = p
        self._paint_hover_quantized = q
        self._paint_hover_normal = tuple(hit.get('normal', (0.0, 1.0, 0.0))) if hit is not None else None
        self._paint_hover_resolved_pick = str(hit.get('resolved_pick', 'plane')) if hit is not None else 'plane'
        # Lock-normal mode: capture the hit normal once and keep it stable until re-align is requested.
        try:
            am = str(self._paint_settings.get("align_mode", ""))
        except Exception:
            am = ""
        am_l = am.lower()
        if am_l.startswith("lock") and self._paint_hover_normal is not None and self._paint_hover_resolved_pick in ("surface", "volume"):
            if (self._paint_locked_normal is None) or self._paint_realign_request:
                self._paint_locked_normal = tuple(self._paint_hover_normal)
                self._paint_realign_request = False
        elif not am_l.startswith("lock"):
            self._paint_locked_normal = None
        self.paint_hover_changed.emit({
            "valid": True,
            "x": q[0], "y": q[1], "z": q[2],
            "target_mode": "volume",
            "resolved_pick": self._paint_hover_resolved_pick,
            "normal": list(self._paint_hover_normal) if self._paint_hover_normal is not None else None,
            "brush_size": int(self._paint_settings.get("size_blocks", 1)),
            "brush_roll_deg": float(self._paint_settings.get("brush_roll_deg", 0.0)),
            "brush_offset_blocks": float(self._paint_settings.get("brush_offset_blocks", 0.0)),
            "align_mode": str(self._paint_settings.get("align_mode", "Auto align to surface hit")),
        })
        self.update()

    def _paint_begin(self, sx: float, sy: float) -> bool:
        hit = self._paint_target_hit(sx, sy)
        p = None if hit is None else hit.get('point')
        if p is None:
            self.paint_hover_changed.emit({"valid": False})
            return False
        self._painting = True
        self._paint_points = []
        self._paint_last_world = None
        self._paint_add_sample(p, normal=(None if hit is None else hit.get('normal')), resolved_pick=(None if hit is None else hit.get('resolved_pick')))
        return True

    def _paint_add_sample(self, world_p: tuple[float, float, float], normal: tuple[float, float, float] | None = None, resolved_pick: str | None = None) -> None:
        if self._paint_last_world is not None:
            if self._dist3(world_p, self._paint_last_world) < self._paint_spacing_blocks():
                return
        q = self._quantize_paint_point(world_p)
        fp = (float(world_p[0]), float(world_p[1]), float(world_p[2]))
        self._paint_points.append(fp)
        self._paint_last_world = fp
        self._paint_hover_world = world_p
        self._paint_hover_quantized = q
        self._paint_hover_normal = tuple(normal) if normal is not None else self._paint_hover_normal
        if resolved_pick is not None:
            self._paint_hover_resolved_pick = str(resolved_pick)
        # Keep locked normal stable during strokes
        try:
            am = str(self._paint_settings.get("align_mode", ""))
        except Exception:
            am = ""
        am_l = am.lower()
        if am_l.startswith("lock") and self._paint_hover_normal is not None and self._paint_hover_resolved_pick in ("surface", "volume"):
            if (self._paint_locked_normal is None) or self._paint_realign_request:
                self._paint_locked_normal = tuple(self._paint_hover_normal)
                self._paint_realign_request = False
        elif not am_l.startswith("lock"):
            self._paint_locked_normal = None
        self.paint_hover_changed.emit({
            "valid": True,
            "x": q[0], "y": q[1], "z": q[2],
            "target_mode": "volume",
            "resolved_pick": self._paint_hover_resolved_pick,
            "normal": list(self._paint_hover_normal) if self._paint_hover_normal is not None else None,
            "brush_roll_deg": float(self._paint_settings.get("brush_roll_deg", 0.0)),
            "brush_offset_blocks": float(self._paint_settings.get("brush_offset_blocks", 0.0)),
            "align_mode": str(self._paint_settings.get("align_mode", "Auto align to surface hit")),
        })

    def _paint_update(self, sx: float, sy: float) -> None:
        hit = self._paint_target_hit(sx, sy)
        p = None if hit is None else hit.get('point')
        if p is None:
            return
        self._paint_add_sample(p, normal=(None if hit is None else hit.get('normal')), resolved_pick=(None if hit is None else hit.get('resolved_pick')))

    def _paint_end(self) -> None:
        if not self._painting:
            return
        pts = list(self._paint_points)
        self._painting = False
        self._paint_last_world = None
        self._paint_points = []
        if not pts:
            return
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        zs = [float(p[2]) for p in pts]
        info = {
            "active_layer": str(self._paint_settings.get("active_layer", "Paint Layer")),
            "action": str(self._paint_settings.get("action", "Replace blocks")),
            "material": str(self._paint_settings.get("material", "minecraft:stone")),
            "size_blocks": int(self._paint_settings.get("size_blocks", 1)),
            "shape": str(self._paint_settings.get("shape", "Sphere")),
            "strength_pct": int(self._paint_settings.get("strength_pct", 100)),
            "axis_lock": str(self._paint_settings.get("axis_lock", "None")),
            "mirror": str(self._paint_settings.get("mirror", "None")),
            "host_only": bool(self._paint_settings.get("host_only", False)),
            "protect_surface": bool(self._paint_settings.get("protect_surface", False)),
            "surface_margin": int(self._paint_settings.get("surface_margin", 6)),
            "point_count": int(len(pts)),
            "bbox": [int(math.floor(min(xs))), int(math.floor(min(ys))), int(math.floor(min(zs))), int(math.ceil(max(xs))), int(math.ceil(max(ys))), int(math.ceil(max(zs)))],
            "target_mode": "volume",
            "points": [[float(p[0]), float(p[1]), float(p[2])] for p in pts[:2048]],
        }
        self.paint_stroke_committed.emit(info)

    def _paint_target_plane_axis(self) -> int:
        return 1

    def _is_temp_navigate_mods(self, mods: QtCore.Qt.KeyboardModifiers) -> bool:
        return bool(self._space_navigate or (mods & QtCore.Qt.KeyboardModifier.AltModifier))

    def _camera_dolly_basic(self, steps: float) -> None:
        scale = (0.90 ** float(steps))
        self.camera.distance *= scale
        self.camera.clamp()

    def _camera_dolly_to_point(self, steps: float, point: tuple[float, float, float] | None) -> None:
        if point is None:
            self._camera_dolly_basic(steps)
            return
        scale = (0.90 ** float(steps))
        tx, ty, tz = self.camera.target
        px, py, pz = point
        alpha = max(-0.85, min(0.85, 1.0 - scale))
        self.camera.target = (
            float(tx + (px - tx) * alpha),
            float(ty + (py - ty) * alpha),
            float(tz + (pz - tz) * alpha),
        )
        self.camera.distance *= scale
        self.camera.clamp()

    def _adjust_paint_brush_size(self, step_delta: int) -> None:
        if not self._paint_enabled:
            return
        try:
            cur = int(self._paint_settings.get("size_blocks", 8))
        except Exception:
            cur = 8
        new_size = max(1, min(64, cur + int(step_delta)))
        if new_size == cur:
            return
        self._paint_settings["size_blocks"] = new_size
        try:
            q = self._paint_hover_quantized
            payload = {"valid": bool(q)}
            if q:
                payload.update({
                    "x": q[0], "y": q[1], "z": q[2],
                    "target_mode": "volume",
                    "brush_size": new_size,
                })
            self.paint_hover_changed.emit(payload)
        except Exception:
            pass
        self.update()

    def _paint_brush_offset_step_blocks(self) -> float:
        try:
            size_blocks = max(1.0, float(self._paint_settings.get("size_blocks", 1)))
        except Exception:
            size_blocks = 1.0
        dist = self._paint_cursor_distance
        if dist is None:
            dist = self._paint_last_surface_hit_distance
        if dist is None:
            dist = float(self.camera.distance)
        # Stable camera-relative distance step: large enough to feel responsive,
        # but not so large that the brush jumps uncontrollably near the camera.
        return max(size_blocks * 0.35, min(24.0, max(1.0, float(dist) * 0.05)))

    def _adjust_paint_brush_offset(self, step_delta: int) -> None:
        if not self._paint_enabled or not step_delta:
            return
        try:
            cur = float(self._paint_settings.get("brush_offset_blocks", 0.0))
        except Exception:
            cur = 0.0
        step_blocks = self._paint_brush_offset_step_blocks()
        new_v = max(-512.0, min(512.0, cur + (float(step_delta) * float(step_blocks))))
        if abs(new_v - cur) < 1e-6:
            return
        self._paint_settings["brush_offset_blocks"] = float(new_v)
        base_dist = self._paint_last_surface_hit_distance
        if base_dist is not None:
            self._paint_cursor_distance = max(1.0, min(8192.0, float(base_dist) - float(new_v)))
        else:
            cur_dist = self._paint_current_cursor_distance()
            self._paint_cursor_distance = max(1.0, min(8192.0, cur_dist - (float(step_delta) * float(step_blocks))))
        self._emit_hover_with_current_cursor()
        self.update()

    def _adjust_paint_brush_roll(self, step_delta: int) -> None:
        if not self._paint_enabled or not step_delta:
            return
        try:
            cur = float(self._paint_settings.get("brush_roll_deg", 0.0))
        except Exception:
            cur = 0.0
        new_v = float(cur + (float(step_delta) * 5.0))
        while new_v > 180.0:
            new_v -= 360.0
        while new_v < -180.0:
            new_v += 360.0
        if abs(new_v - cur) < 1e-6:
            return
        self._paint_settings["brush_roll_deg"] = float(new_v)
        self._emit_hover_with_current_cursor()
        self.update()

    def _emit_hover_with_current_cursor(self) -> None:
        if self._paint_enabled and self._cursor_pos is not None and not self._painting:
            try:
                self._schedule_paint_hover(self._cursor_pos[0], self._cursor_pos[1], immediate=True)
            except Exception:
                pass

    def request_paint_realign(self) -> None:
        self._paint_realign_request = True
        self._emit_hover_with_current_cursor()
        self.update()

    def _focus_under_cursor(self) -> None:
        p = self._paint_hover_world
        if p is None and self._cursor_pos is not None:
            p = self._paint_target_world(self._cursor_pos[0], self._cursor_pos[1])
        if p is None:
            return
        self.camera.target = (float(p[0]), float(p[1]), float(p[2]))
        self._update_target_chunk()
        self.update()

    # ---------------- camera controls ----------------
    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        x = e.position().x(); y = e.position().y()
        self._last_mouse = (x, y)
        self._cursor_pos = (x, y)
        mods = e.modifiers()
        nav_override = self._is_temp_navigate_mods(mods)

        if self._paint_enabled:
            # Paint mode keeps the normal camera controls available without modifier churn.
            # LMB paints; RMB/MMB pan; Alt/Space temporarily switches to navigation.
            if e.button() == QtCore.Qt.MouseButton.LeftButton and not nav_override and not (mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
                if self._paint_begin(x, y):
                    e.accept()
                    return
            if nav_override and e.button() == QtCore.Qt.MouseButton.LeftButton:
                self._orbiting = True
                e.accept()
                return
            if nav_override and e.button() == QtCore.Qt.MouseButton.RightButton:
                self._dolly_dragging = True
                e.accept()
                return
            if e.button() == QtCore.Qt.MouseButton.RightButton or e.button() == QtCore.Qt.MouseButton.MiddleButton or (
                e.button() == QtCore.Qt.MouseButton.LeftButton and (mods & QtCore.Qt.KeyboardModifier.ShiftModifier)
            ):
                self._panning = True
                e.accept()
                return

        # Default navigation (inspect mode / painter disabled)
        if e.button() == QtCore.Qt.MouseButton.LeftButton and not (mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
            self._orbiting = True
        elif e.button() == QtCore.Qt.MouseButton.RightButton or e.button() == QtCore.Qt.MouseButton.MiddleButton or (
            e.button() == QtCore.Qt.MouseButton.LeftButton and (mods & QtCore.Qt.KeyboardModifier.ShiftModifier)
        ):
            self._panning = True
        e.accept()

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent) -> None:
        if self._painting and e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._paint_end()
        if e.button() == QtCore.Qt.MouseButton.RightButton:
            self._dolly_dragging = False
        self._orbiting = False
        self._panning = False
        self._last_mouse = None
        e.accept()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent) -> None:
        x, y = e.position().x(), e.position().y()
        self._cursor_pos = (x, y)

        # Hover updates in painter mode even when not dragging.
        if self._paint_enabled and not self._painting and not self._orbiting and not self._panning and not self._dolly_dragging:
            self._schedule_paint_hover(x, y)

        if not self._last_mouse:
            self._last_mouse = (x, y)
            return
        lx, ly = self._last_mouse
        dx = x - lx
        dy = y - ly
        self._last_mouse = (x, y)

        if self._painting:
            self._paint_update(x, y)
            self.update()
            return

        if self._orbiting:
            self.camera.yaw += dx * 0.3
            self.camera.pitch -= dy * 0.3
        elif self._dolly_dragging:
            self._camera_dolly_basic(dy * 0.08)
        elif self._panning:
            self.camera.pan(dx, dy)

        self._update_target_chunk()
        if self._paint_enabled and not self._painting:
            self._schedule_paint_hover(x, y, immediate=True)
        self.update()

    def wheelEvent(self, e: QtGui.QWheelEvent) -> None:
        delta_steps = e.angleDelta().y() / 120.0
        mods = e.modifiers()
        step_dir = 1 if delta_steps > 0 else (-1 if delta_steps < 0 else 0)

        if self._paint_enabled and (mods & QtCore.Qt.KeyboardModifier.ControlModifier):
            # Ctrl+Wheel = brush size.
            self._adjust_paint_brush_size(step_dir)
            e.accept()
            return
        if self._paint_enabled and (mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
            # Shift+Wheel = move the brush gizmo toward / away from the camera.
            x = e.position().x(); y = e.position().y()
            self._cursor_pos = (x, y)
            self._adjust_paint_brush_offset(step_dir)
            try:
                self._schedule_paint_hover(x, y, immediate=True)
            except Exception:
                pass
            e.accept()
            return

        target_point = None
        if self._paint_enabled:
            x = e.position().x(); y = e.position().y()
            self._cursor_pos = (x, y)
            target_point = self._paint_target_world(x, y)
        self._camera_dolly_to_point(delta_steps, target_point)
        self._update_target_chunk()
        self._emit_hover_with_current_cursor()
        self.update()
        e.accept()

    def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
        if e.key() == QtCore.Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space_navigate = True
            self.update()
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_F:
            self._focus_under_cursor()
            e.accept()
            return
        if e.key() in (QtCore.Qt.Key.Key_BracketLeft, QtCore.Qt.Key.Key_PageUp):
            self._adjust_paint_brush_offset(1)
            e.accept()
            return
        if e.key() in (QtCore.Qt.Key.Key_BracketRight, QtCore.Qt.Key.Key_PageDown):
            self._adjust_paint_brush_offset(-1)
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_Minus:
            self._adjust_paint_brush_size(-1)
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_Equal:
            self._adjust_paint_brush_size(1)
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_Q:
            self._adjust_paint_brush_roll(-1)
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_E:
            self._adjust_paint_brush_roll(1)
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_0:
            self._paint_settings["brush_roll_deg"] = 0.0
            self._emit_hover_with_current_cursor()
            self.update()
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_Backslash:
            self._paint_settings["brush_offset_blocks"] = 0.0
            if self._paint_last_surface_hit_distance is not None:
                self._paint_cursor_distance = float(self._paint_last_surface_hit_distance)
            self._emit_hover_with_current_cursor()
            self.update()
            e.accept()
            return
        if e.key() == QtCore.Qt.Key.Key_R:
            # Re-align locked normal to current hover hit when in lock mode
            try:
                am = str(self._paint_settings.get("align_mode", ""))
            except Exception:
                am = ""
            if am.lower().startswith("lock"):
                self.request_paint_realign()
                e.accept()
                return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QtGui.QKeyEvent) -> None:
        if e.key() == QtCore.Qt.Key.Key_Space and not e.isAutoRepeat():
            self._space_navigate = False
            self._orbiting = False
            self._panning = False
            self._dolly_dragging = False
            self.update()
            e.accept()
            return
        super().keyReleaseEvent(e)

    def _update_target_chunk(self) -> None:
        if not self._stream:
            return
        tx, _, tz = self.camera.target
        cx = int(math.floor(tx / 16.0))
        cz = int(math.floor(tz / 16.0))
        if (cx, cz) != self._last_target_chunk:
            self._last_target_chunk = (cx, cz)
            self._topmap_dirty = True
            self._stream.set_target_chunk(cx, cz)

    # ---------------- streaming ----------------
    def _tick_stream(self) -> None:
        if self._loading_paused:
            return
        if self._stream:
            self._stream.update()

    @QtCore.Slot(int, int, object)
    def _on_mesh_ready(self, cx: int, cz: int, meshdata) -> None:
        key = ChunkKey(cx, cz)
        tops = tuple(getattr(meshdata, "top_heights", ()) or ())
        if len(tops) == 256:
            self._chunk_top_heights[key] = tops
        else:
            self._chunk_top_heights.pop(key, None)
        self._topmap_dirty = True
        with self._pending_lock:
            self._pending_meshdata[key] = meshdata
            self._pending_replace_keys.add(key)
        if not self._bulk_queueing_meshes:
            self.update()

    @QtCore.Slot(int, int)
    def _on_stream_stats(self, resident: int, inflight: int) -> None:
        self._resident_chunks = resident
        self._inflight_builds = inflight

    @QtCore.Slot(object)
    def _on_materials_changed(self, names) -> None:
        self.materials_changed.emit(names)
        self._mask_dirty = True
        self.update()

    # ---------------- cutaway (shader-side, no remesh) ----------------
    def _effective_cutaway_uniforms(self) -> dict:
        s = dict(self._view_settings or {})
        mode = str(self._mode)
        if mode == "Surface (fast)":
            return {
                "cut_enabled": False,
                "use_peel": False,
                "peel_y": 0.0,
                "use_zslice": False,
                "z_center": 0.0,
                "z_half": 1.0,
                "use_clipbox": False,
                "clip_min": (0.0, 0.0, 0.0),
                "clip_max": (0.0, 0.0, 0.0),
            }

        # Base user controls
        cut_enabled = bool(s.get("cut_enabled", False))
        peel_enabled = bool(s.get("peel_enabled", False)) and cut_enabled
        peel_depth = max(0, int(s.get("peel_depth", 0)))
        zslice_enabled = bool(s.get("zslice_enabled", False)) and cut_enabled
        zslice_follow = bool(s.get("zslice_follow_camera", True))
        zslice_center = float(self.camera.target[2] if zslice_follow else float(s.get("zslice_center", 0)))
        z_thickness = max(1.0, float(s.get("zslice_thickness", 64)))
        z_half = max(0.5, z_thickness * 0.5)

        clipbox_enabled = bool(s.get("clipbox_enabled", False)) and cut_enabled
        sx = max(2.0, float(s.get("clipbox_size_x", 160)))
        sy = max(2.0, float(s.get("clipbox_size_y", 192)))
        sz = max(2.0, float(s.get("clipbox_size_z", 160)))
        tx, ty, tz = self.camera.target
        clip_min = (float(tx - sx * 0.5), float(ty - sy * 0.5), float(tz - sz * 0.5))
        clip_max = (float(tx + sx * 0.5), float(ty + sy * 0.5), float(tz + sz * 0.5))

        # Underground focus can auto-enable useful cuts unless the user already enabled something.
        if mode == "Underground focus (preview)" and not (peel_enabled or zslice_enabled or clipbox_enabled):
            cut_enabled = True
            peel_enabled = True
            zslice_enabled = True
            peel_depth = max(96, peel_depth)
            z_thickness = max(96.0, z_thickness)
            z_half = z_thickness * 0.5

        y_top = 320.0
        try:
            _ymin, _ymax = self._world_height_range
            y_top = float(_ymax)
        except Exception:
            pass
        peel_y = y_top - float(peel_depth)

        terrain_peel = bool(s.get("terrain_peel", True))
        plane_enabled = bool(s.get("plane_enabled", False))
        plane_axis_text = str(s.get("plane_axis", "Y (horizontal)"))
        plane_axis = 1
        if plane_axis_text.startswith("X"):
            plane_axis = 0
        elif plane_axis_text.startswith("Z"):
            plane_axis = 2
        plane_follow = bool(s.get("plane_follow_camera", True))
        plane_position = float(s.get("plane_position", 0.0))
        plane_offset = float(s.get("plane_offset", 0.0))
        if plane_follow:
            tx, ty, tz = self.camera.target
            if plane_axis == 0:
                plane_position = float(tx + plane_offset)
            elif plane_axis == 1:
                plane_position = float(ty + plane_offset)
            else:
                plane_position = float(tz + plane_offset)
        else:
            plane_position = float(plane_position + plane_offset)
        plane_keep_positive = bool(s.get("plane_keep_positive", False))
        plane_show_gizmo = bool(s.get("plane_show_gizmo", True))

        return {
            "cut_enabled": bool(cut_enabled and (peel_enabled or zslice_enabled or clipbox_enabled or plane_enabled)),
            "use_peel": bool(peel_enabled),
            "use_terrain_peel": bool(peel_enabled and terrain_peel),
            "peel_y": float(peel_y),
            "peel_depth": float(peel_depth),
            "use_zslice": bool(zslice_enabled),
            "z_center": float(zslice_center),
            "z_half": float(z_half),
            "use_clipbox": bool(clipbox_enabled),
            "clip_min": clip_min,
            "clip_max": clip_max,
            "plane_enabled": bool(plane_enabled),
            "plane_axis": int(plane_axis),
            "plane_pos": float(plane_position),
            "plane_keep_positive": bool(plane_keep_positive),
            "plane_show_gizmo": bool(plane_show_gizmo),
        }

    # ---------------- OpenGL ----------------
    def initializeGL(self) -> None:
        try:
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glClearDepth(1.0)

            vendor = GL.glGetString(GL.GL_VENDOR)
            renderer = GL.glGetString(GL.GL_RENDERER)
            version = GL.glGetString(GL.GL_VERSION)
            log.info(
                "OpenGL context: vendor=%s renderer=%s version=%s",
                vendor.decode(errors="ignore") if vendor else vendor,
                renderer.decode(errors="ignore") if renderer else renderer,
                version.decode(errors="ignore") if version else version,
            )

            vs_src = """#version 330 core
            layout(location=0) in vec3 aPos;
            layout(location=1) in vec3 aColor;
            layout(location=2) in float aMatId;
            uniform mat4 uMVP;
            out vec3 vColor;
            out float vMatId;
            out vec3 vWorldPos;
            void main(){
                vColor = aColor;
                vMatId = aMatId;
                vWorldPos = aPos;
                gl_Position = uMVP * vec4(aPos, 1.0);
            }
            """

            fs_src = """#version 330 core
            in vec3 vColor;
            in float vMatId;
            in vec3 vWorldPos;
            uniform sampler1D uMask;
            uniform int uCutEnabled;
            uniform int uUsePeel;
            uniform int uUseTerrainPeel;
            uniform float uPeelY;
            uniform sampler2D uTopMap;
            uniform vec2 uTopOrigin;
            uniform ivec2 uTopDims;
            uniform int uUseZSlice;
            uniform float uZCenter;
            uniform float uZHalf;
            uniform int uUseClipBox;
            uniform vec3 uClipMin;
            uniform vec3 uClipMax;
            uniform int uPlaneEnabled;
            uniform int uPlaneAxis;
            uniform float uPlanePos;
            uniform int uPlaneKeepPositive;
            out vec4 FragColor;
            void main(){
                int mid = int(vMatId + 0.5);
                float vis = texelFetch(uMask, mid, 0).r;
                if (vis < 0.5) discard;

                if (uCutEnabled == 1) {
                    float peelCut = uPeelY;
                    if (uUsePeel == 1 && uUseTerrainPeel == 1 && uTopDims.x > 0 && uTopDims.y > 0) {
                        ivec2 tp = ivec2(floor(vWorldPos.x - uTopOrigin.x), floor(vWorldPos.z - uTopOrigin.y));
                        if (tp.x >= 0 && tp.y >= 0 && tp.x < uTopDims.x && tp.y < uTopDims.y) {
                            peelCut = texelFetch(uTopMap, tp, 0).r;
                        }
                    }
                    if (uUsePeel == 1 && vWorldPos.y > peelCut) discard;
                    if (uUseZSlice == 1 && abs(vWorldPos.z - uZCenter) > uZHalf) discard;
                    if (uUseClipBox == 1) {
                        if (vWorldPos.x < uClipMin.x || vWorldPos.y < uClipMin.y || vWorldPos.z < uClipMin.z) discard;
                        if (vWorldPos.x > uClipMax.x || vWorldPos.y > uClipMax.y || vWorldPos.z > uClipMax.z) discard;
                    }
                    if (uPlaneEnabled == 1) {
                        float d = 0.0;
                        if (uPlaneAxis == 0) d = vWorldPos.x - uPlanePos;
                        else if (uPlaneAxis == 1) d = vWorldPos.y - uPlanePos;
                        else d = vWorldPos.z - uPlanePos;
                        if (uPlaneKeepPositive == 1) {
                            if (d < 0.0) discard;
                        } else {
                            if (d > 0.0) discard;
                        }
                    }
                }

                FragColor = vec4(vColor, 1.0);
            }
            """

            vs = compile_shader(vs_src, GL.GL_VERTEX_SHADER)
            fs = compile_shader(fs_src, GL.GL_FRAGMENT_SHADER)
            self._program = link_program(vs, fs)
            GL.glDeleteShader(vs)
            GL.glDeleteShader(fs)

            self._u_mvp = GL.glGetUniformLocation(self._program, "uMVP")
            self._u_mask = GL.glGetUniformLocation(self._program, "uMask")
            self._u_cut_enabled = GL.glGetUniformLocation(self._program, "uCutEnabled")
            self._u_use_peel = GL.glGetUniformLocation(self._program, "uUsePeel")
            self._u_peel_y = GL.glGetUniformLocation(self._program, "uPeelY")
            self._u_use_zslice = GL.glGetUniformLocation(self._program, "uUseZSlice")
            self._u_z_center = GL.glGetUniformLocation(self._program, "uZCenter")
            self._u_z_half = GL.glGetUniformLocation(self._program, "uZHalf")
            self._u_use_clipbox = GL.glGetUniformLocation(self._program, "uUseClipBox")
            self._u_clip_min = GL.glGetUniformLocation(self._program, "uClipMin")
            self._u_clip_max = GL.glGetUniformLocation(self._program, "uClipMax")
            self._u_use_terrain_peel = GL.glGetUniformLocation(self._program, "uUseTerrainPeel")
            self._u_topmap = GL.glGetUniformLocation(self._program, "uTopMap")
            self._u_top_origin = GL.glGetUniformLocation(self._program, "uTopOrigin")
            self._u_top_dims = GL.glGetUniformLocation(self._program, "uTopDims")
            self._u_plane_enabled = GL.glGetUniformLocation(self._program, "uPlaneEnabled")
            self._u_plane_axis = GL.glGetUniformLocation(self._program, "uPlaneAxis")
            self._u_plane_pos = GL.glGetUniformLocation(self._program, "uPlanePos")
            self._u_plane_keep_positive = GL.glGetUniformLocation(self._program, "uPlaneKeepPositive")

            self._mask = VisibilityMask()
            self._mask.ensure_size(256)
            self._last_mask_size = 256
            self._mask_dirty = True

            self._topmap_tex = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._topmap_tex)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            self._topmap_dirty = True

            line_vs_src = """#version 330 core
            layout(location=0) in vec3 aPos;
            layout(location=1) in vec3 aColor;
            uniform mat4 uMVP;
            out vec3 vColor;
            void main(){ vColor=aColor; gl_Position = uMVP * vec4(aPos,1.0); }
            """
            line_fs_src = """#version 330 core
            in vec3 vColor;
            out vec4 FragColor;
            void main(){ FragColor = vec4(vColor, 0.95); }
            """
            lvs = compile_shader(line_vs_src, GL.GL_VERTEX_SHADER)
            lfs = compile_shader(line_fs_src, GL.GL_FRAGMENT_SHADER)
            self._line_program = link_program(lvs, lfs)
            GL.glDeleteShader(lvs)
            GL.glDeleteShader(lfs)
            self._u_line_mvp = GL.glGetUniformLocation(self._line_program, "uMVP")
            self._line_vao = GL.glGenVertexArrays(1)
            self._line_vbo = GL.glGenBuffers(1)
            GL.glBindVertexArray(self._line_vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._line_vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, 0, None, GL.GL_DYNAMIC_DRAW)
            stride = 6 * 4
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, stride, ctypes.c_void_p(0))
            GL.glEnableVertexAttribArray(1)
            GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, False, stride, ctypes.c_void_p(12))
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            GL.glBindVertexArray(0)

            self._cull_state_dirty = True
            self._gl_ok = True
        except Exception as e:
            self._gl_ok = False
            self.gl_failed.emit(str(e))

    def _apply_cull_state(self) -> None:
        if not self._gl_ok:
            return
        if self._cull_faces:
            GL.glEnable(GL.GL_CULL_FACE)
            GL.glCullFace(GL.GL_BACK)
        else:
            GL.glDisable(GL.GL_CULL_FACE)
        self._cull_state_dirty = False

    def resizeGL(self, w: int, h: int) -> None:
        if not self._gl_ok:
            return
        GL.glViewport(0, 0, max(1, w), max(1, h))

    def _flush_pending_mesh_uploads(self) -> None:
        if not self._gl_ok:
            return
        try:
            self.makeCurrent()
        except Exception:
            pass
        with self._pending_lock:
            if not self._pending_meshdata:
                self._uploads_last_frame = 0
                return
            items = list(self._pending_meshdata.items())

            # Prioritize smaller batch to keep frame responsive; process up to max uploads this frame.
            to_take = min(len(items), self._max_uploads_per_frame)
            taken = items[:to_take]
            remain = items[to_take:]

            pending_replace_for_taken = set(k for k, _ in taken)
            for k in pending_replace_for_taken:
                self._pending_replace_keys.discard(k)

            self._pending_meshdata = dict(remain)

        # Delete/re-upload only for chunks taken this frame
        self._uploads_last_frame = 0
        for key, meshdata in taken:
            old = self._meshes.pop(key, None)
            if old is not None:
                try:
                    delete_mesh(old)
                except Exception as e:
                    log.debug("delete_mesh failed for %s: %s", key, e)

            try:
                m = upload_mesh(meshdata.vertices, meshdata.vertex_count, meshdata.lod)
                if m is not None:
                    self._meshes[key] = m
                self._uploads_last_frame += 1
            except Exception as e:
                log.exception("GL mesh upload failed for chunk (%d,%d) lod=%s: %s", key.cx, key.cz, getattr(meshdata, "lod", "?"), e)

    def _update_mask_texture(self) -> None:
        if not self._gl_ok or not self._stream or not self._mask:
            return
        n = self._stream.registry.size() + 1
        if n > self._last_mask_size:
            self._mask.ensure_size(n)
            self._last_mask_size = n

        vis = [255] * self._last_mask_size
        for name, is_vis in self._mask_vis.items():
            mid = self._stream.registry.get_or_create(name)
            if 0 <= mid < len(vis):
                vis[mid] = 255 if is_vis else 0

        data = array.array('B', vis).tobytes()
        self._mask.update(data)
        self._mask_dirty = False

    def paintGL(self) -> None:
        if not self._gl_ok:
            return
        try:
            # Ensure context is current for all PyOpenGL calls.
            self.makeCurrent()
        except Exception:
            pass
        if self._loading_paused:
            try:
                GL.glClearColor(0.10, 0.10, 0.10, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            except Exception:
                pass
            return
        t0 = time.perf_counter()
        try:
            if self._cull_state_dirty:
                self._apply_cull_state()

            if self._drop_all_meshes_pending:
                for _k, _m in list(self._meshes.items()):
                    try:
                        delete_mesh(_m)
                    except Exception:
                        pass
                self._meshes.clear()
                self._drop_all_meshes_pending = False
            elif self._drop_voxel_meshes_pending:
                for _k, _m in list(self._meshes.items()):
                    if getattr(_m, "lod", "") != "voxel":
                        continue
                    try:
                        delete_mesh(_m)
                    except Exception:
                        pass
                    self._meshes.pop(_k, None)
                    self._chunk_top_heights.pop(_k, None)
                self._drop_voxel_meshes_pending = False
                self._drop_voxel_mesh_keys_pending.clear()
            elif self._drop_voxel_mesh_keys_pending:
                dirty = {(int(k.cx), int(k.cz)) for k in list(self._drop_voxel_mesh_keys_pending)}
                for _k, _m in list(self._meshes.items()):
                    if getattr(_m, "lod", "") != "voxel":
                        continue
                    if (_k.cx, _k.cz) not in dirty:
                        continue
                    try:
                        delete_mesh(_m)
                    except Exception:
                        pass
                    self._meshes.pop(_k, None)
                    self._chunk_top_heights.pop(_k, None)
                self._drop_voxel_mesh_keys_pending.clear()

            self._flush_pending_mesh_uploads()
            if self._mask_dirty:
                self._update_mask_texture()

            cut = self._effective_cutaway_uniforms()
            self._update_topmap_texture(cut)

            GL.glClearColor(0.10, 0.10, 0.12, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

            w = max(1, self.width())
            h = max(1, self.height())
            proj = perspective(55.0, w / float(h), 0.1, 10000.0)
            eye = self.camera.eye()
            view = look_at(eye, self.camera.target)
            mvp = mat4_mul(proj, view)

            GL.glUseProgram(self._program)
            GL.glUniformMatrix4fv(self._u_mvp, 1, False, (ctypes.c_float * 16)(*mvp))

            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_1D, self._mask.tex)
            GL.glUniform1i(self._u_mask, 0)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, int(self._topmap_tex) if self._topmap_tex else 0)
            GL.glUniform1i(self._u_topmap, 1)

            GL.glUniform1i(self._u_cut_enabled, 1 if cut.get("cut_enabled") else 0)
            GL.glUniform1i(self._u_use_peel, 1 if cut.get("use_peel") else 0)
            GL.glUniform1i(self._u_use_terrain_peel, 1 if (cut.get("use_terrain_peel") and self._topmap_dims[0] > 0 and self._topmap_dims[1] > 0) else 0)
            GL.glUniform1f(self._u_peel_y, float(cut.get("peel_y", 0.0)))
            GL.glUniform2f(self._u_top_origin, float(self._topmap_origin[0]), float(self._topmap_origin[1]))
            GL.glUniform2i(self._u_top_dims, int(self._topmap_dims[0]), int(self._topmap_dims[1]))
            GL.glUniform1i(self._u_use_zslice, 1 if cut.get("use_zslice") else 0)
            GL.glUniform1f(self._u_z_center, float(cut.get("z_center", 0.0)))
            GL.glUniform1f(self._u_z_half, float(cut.get("z_half", 1.0)))
            GL.glUniform1i(self._u_use_clipbox, 1 if cut.get("use_clipbox") else 0)
            cmin = cut.get("clip_min", (0.0, 0.0, 0.0))
            cmax = cut.get("clip_max", (0.0, 0.0, 0.0))
            GL.glUniform3f(self._u_clip_min, float(cmin[0]), float(cmin[1]), float(cmin[2]))
            GL.glUniform3f(self._u_clip_max, float(cmax[0]), float(cmax[1]), float(cmax[2]))
            GL.glUniform1i(self._u_plane_enabled, 1 if cut.get("plane_enabled") else 0)
            GL.glUniform1i(self._u_plane_axis, int(cut.get("plane_axis", 1)))
            GL.glUniform1f(self._u_plane_pos, float(cut.get("plane_pos", 0.0)))
            GL.glUniform1i(self._u_plane_keep_positive, 1 if cut.get("plane_keep_positive") else 0)
            GL.glActiveTexture(GL.GL_TEXTURE0)

            # Clear any stale GL errors before drawing meshes.
            try:
                while True:
                    err = GL.glGetError()
                    if err == GL.GL_NO_ERROR:
                        break
            except Exception:
                pass

            bad_keys = []
            for key, m in list(self._meshes.items()):
                try:
                    GL.glBindVertexArray(int(m.vao))
                    GL.glDrawArrays(GL.GL_TRIANGLES, 0, int(m.vertex_count))
                except Exception as e:
                    if not self._gl_error_spam_suppressed:
                        log.exception("Draw failed for chunk (%d,%d); dropping invalid mesh: %s", key.cx, key.cz, e)
                        self._gl_error_spam_suppressed = True
                    bad_keys.append(key)

            for key in bad_keys:
                m = self._meshes.pop(key, None)
                if m is not None:
                    try:
                        delete_mesh(m)
                    except Exception:
                        pass

            self._draw_plane_gizmo(mvp, cut)
            self._draw_paint_brush_gizmo(mvp, cut)

            GL.glBindVertexArray(0)
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_1D, 0)
            GL.glUseProgram(0)
        except Exception as e:
            if not self._gl_error_spam_suppressed:
                self._gl_error_spam_suppressed = True
                log.exception("paintGL failed (suppressing repeats): %s", e)
        finally:
            dt = (time.perf_counter() - t0) * 1000.0
            self._last_frame_draw_ms = dt
            self._fps_frames += 1
            t_now = time.perf_counter()
            if t_now - self._fps_t0 >= 0.5:
                self._fps = self._fps_frames / (t_now - self._fps_t0)
                self._fps_frames = 0
                self._fps_t0 = t_now


    def _draw_paint_brush_gizmo(self, mvp, cut: dict) -> None:
        if not self._gl_ok or not self._line_program:
            return
        if not self._paint_enabled:
            return
        if not bool(self._paint_settings.get("show_overlay", True)):
            return
        center = self._paint_hover_world
        if center is None and self._paint_hover_quantized is not None:
            q = self._paint_hover_quantized
            center = (float(q[0]), float(q[1]), float(q[2]))
        if center is None:
            return

        shape = str(self._paint_settings.get("shape", "Sphere"))
        align_mode = str(self._paint_settings.get("align_mode", "Follow hit normal (auto)"))
        am = align_mode.lower()
        follow_align = am.startswith("follow") or am.startswith("auto")
        lock_align = am.startswith("lock")
        manual_align = (not follow_align) and (not lock_align)
        size_blocks = max(1.0, float(self._paint_settings.get("size_blocks", 1)))
        r = max(0.5, size_blocks * 0.5)
        x, y, z = float(center[0]), float(center[1]), float(center[2])

        # Color cues: cyan hover, greener while actively painting.
        if self._painting:
            c = (0.35, 1.0, 0.55)
        else:
            c = (0.35, 0.85, 1.0)

        verts: list[float] = []
        def add(a, b):
            verts.extend([float(a[0]), float(a[1]), float(a[2]), c[0], c[1], c[2], float(b[0]), float(b[1]), float(b[2]), c[0], c[1], c[2]])
        def add_circle(center_pt, axis: int, radius: float, segs: int = 32):
            cx, cy, cz = center_pt
            segs2 = max(12, int(segs))
            pts = []
            for i in range(segs2):
                t = (i / float(segs2)) * math.tau
                ct = math.cos(t) * radius
                st = math.sin(t) * radius
                if axis == 0:      # YZ plane (normal +X)
                    pts.append((cx, cy + ct, cz + st))
                elif axis == 1:    # XZ plane (normal +Y)
                    pts.append((cx + ct, cy, cz + st))
                else:              # XY plane (normal +Z)
                    pts.append((cx + ct, cy + st, cz))
            for i in range(len(pts)):
                add(pts[i], pts[(i + 1) % len(pts)])

        def add_circle_normal(center_pt, normal_v, radius: float, segs: int = 32, roll_deg: float = 0.0):
            nx, ny, nz = self._vec_normalize(tuple(normal_v), fallback=(0.0, 1.0, 0.0))
            ax = (0.0, 1.0, 0.0) if abs(ny) < 0.95 else (1.0, 0.0, 0.0)
            tx = ny * ax[2] - nz * ax[1]
            ty = nz * ax[0] - nx * ax[2]
            tz = nx * ax[1] - ny * ax[0]
            tl = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
            tx, ty, tz = tx / tl, ty / tl, tz / tl
            bx = ny * tz - nz * ty
            by = nz * tx - nx * tz
            bz = nx * ty - ny * tx
            bl = math.sqrt(bx * bx + by * by + bz * bz) or 1.0
            bx, by, bz = bx / bl, by / bl, bz / bl
            if abs(float(roll_deg)) > 1e-6:
                tx, ty, tz = self._vec_rotate_about_axis((tx, ty, tz), (nx, ny, nz), float(roll_deg))
                bx, by, bz = self._vec_rotate_about_axis((bx, by, bz), (nx, ny, nz), float(roll_deg))
            cx, cy, cz = center_pt
            segs2 = max(12, int(segs))
            pts = []
            for i in range(segs2):
                t = (i / float(segs2)) * math.tau
                ct = math.cos(t) * radius
                st = math.sin(t) * radius
                pts.append((cx + tx * ct + bx * st, cy + ty * ct + by * st, cz + tz * ct + bz * st))
            for i in range(len(pts)):
                add(pts[i], pts[(i + 1) % len(pts)])
            return (tx, ty, tz), (bx, by, bz), (nx, ny, nz)

        hover_n = tuple(self._paint_hover_normal) if self._paint_hover_normal is not None else None
        if lock_align and self._paint_locked_normal is not None:
            effective_n = tuple(self._paint_locked_normal)
        else:
            effective_n = hover_n
        brush_roll_deg = float(self._paint_settings.get("brush_roll_deg", 0.0))

        is_flat = shape.lower().startswith("disc")
        if is_flat:
            if (follow_align or lock_align) and hover_n is not None and self._paint_hover_resolved_pick in ("surface", "volume"):
                tvec, bvec, nvec = add_circle_normal((x, y, z), effective_n, r, segs=40, roll_deg=brush_roll_deg)
                add((x - tvec[0]*r, y - tvec[1]*r, z - tvec[2]*r), (x + tvec[0]*r, y + tvec[1]*r, z + tvec[2]*r))
                add((x - bvec[0]*r, y - bvec[1]*r, z - bvec[2]*r), (x + bvec[0]*r, y + bvec[1]*r, z + bvec[2]*r))
                nn = max(0.75, min(2.0, r * 0.6))
                add((x, y, z), (x + nvec[0]*nn, y + nvec[1]*nn, z + nvec[2]*nn))
            else:
                plane_axis = self._paint_target_plane_axis()
                add_circle((x, y, z), plane_axis, r, segs=40)
                # Crosshair on the plane
                if plane_axis == 1:
                    add((x-r, y, z), (x+r, y, z)); add((x, y, z-r), (x, y, z+r))
                elif plane_axis == 0:
                    add((x, y-r, z), (x, y+r, z)); add((x, y, z-r), (x, y, z+r))
                else:
                    add((x-r, y, z), (x+r, y, z)); add((x, y-r, z), (x, y+r, z))
        elif shape.lower().startswith("box"):
            x0, x1 = x-r, x+r
            y0, y1 = y-r, y+r
            z0, z1 = z-r, z+r
            p000=(x0,y0,z0); p100=(x1,y0,z0); p110=(x1,y1,z0); p010=(x0,y1,z0)
            p001=(x0,y0,z1); p101=(x1,y0,z1); p111=(x1,y1,z1); p011=(x0,y1,z1)
            for a,b in [(p000,p100),(p100,p110),(p110,p010),(p010,p000),
                        (p001,p101),(p101,p111),(p111,p011),(p011,p001),
                        (p000,p001),(p100,p101),(p110,p111),(p010,p011)]:
                add(a,b)
        else:
            # 3D preview brush model: tri-orthogonal circles (sphere-ish) + optional tunnel axis
            add_circle((x, y, z), 0, r, segs=28)
            add_circle((x, y, z), 1, r, segs=28)
            add_circle((x, y, z), 2, r, segs=28)
            if (follow_align or lock_align) and hover_n is not None and self._paint_hover_resolved_pick in ("surface", "volume"):
                nn = self._vec_normalize(effective_n)
                nlen = max(0.75, min(2.5, r * 0.85))
                add((x, y, z), (x + nn[0]*nlen, y + nn[1]*nlen, z + nn[2]*nlen))
            if shape.lower().startswith("tunnel"):
                if (follow_align or lock_align) and hover_n is not None and self._paint_hover_resolved_pick in ("surface", "volume"):
                    axis_v = self._vec_normalize(effective_n)
                else:
                    _eye, _fwd, _right = self._camera_basis()
                    axis_v = _fwd
                half_len = max(r * 1.5, 1.0)
                a = (x - axis_v[0]*half_len, y - axis_v[1]*half_len, z - axis_v[2]*half_len)
                b = (x + axis_v[0]*half_len, y + axis_v[1]*half_len, z + axis_v[2]*half_len)
                add(a, b)
                _fwd, tbase, _ubase = self._camera_basis()
                fin = self._vec_rotate_about_axis(tbase, axis_v, brush_roll_deg)
                flen = max(0.5, r * 0.6)
                add((x, y, z), (x + fin[0]*flen, y + fin[1]*flen, z + fin[2]*flen))

        # While painting, show the current stroke polyline as feedback.
        if self._painting and self._paint_points:
            ps = self._paint_points[-256:]
            c2 = (1.0, 0.75, 0.25)
            for i in range(1, len(ps)):
                ax, ay, az = ps[i-1]
                bx, by, bz = ps[i]
                verts.extend([float(ax), float(ay), float(az), c2[0], c2[1], c2[2], float(bx), float(by), float(bz), c2[0], c2[1], c2[2]])

        if not verts:
            return
        data = array.array('f', verts).tobytes()
        count = len(verts) // 6

        GL.glUseProgram(self._line_program)
        GL.glUniformMatrix4fv(self._u_line_mvp, 1, False, (ctypes.c_float * 16)(*mvp))
        GL.glBindVertexArray(int(self._line_vao))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, int(self._line_vbo))
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(data), data, GL.GL_DYNAMIC_DRAW)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_DEPTH_TEST)
        try:
            GL.glLineWidth(1.0)
        except Exception:
            pass
        GL.glDrawArrays(GL.GL_LINES, 0, int(count))
        if self._cull_faces:
            GL.glEnable(GL.GL_CULL_FACE)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)
        GL.glUseProgram(self._program)

    def _update_topmap_texture(self, cut: dict | None = None) -> None:
        if not self._gl_ok or not self._topmap_tex:
            return
        if cut is None:
            cut = self._effective_cutaway_uniforms()
        if (not self._topmap_dirty) and (self._last_topmap_build_target == self._last_target_chunk):
            return

        try:
            tx, _ty, tz = self.camera.target
            tcx = int(math.floor(tx / 16.0))
            tcz = int(math.floor(tz / 16.0))
        except Exception:
            tcx, tcz = 0, 0

        radius_chunks = 6
        if self._stream is not None:
            try:
                radius_chunks = max(2, int(getattr(self._stream, 'near_ring', 4)) + 2)
            except Exception:
                radius_chunks = 6
        radius_chunks = min(radius_chunks, 24)

        min_cx = tcx - radius_chunks
        min_cz = tcz - radius_chunks
        w = (radius_chunks * 2 + 1) * 16
        h = (radius_chunks * 2 + 1) * 16
        if w <= 0 or h <= 0:
            self._topmap_dims = (0, 0)
            return

        peel_depth = float(cut.get('peel_depth', 0.0))
        global_peel_y = float(cut.get('peel_y', 0.0))
        vals = [global_peel_y] * (w * h)

        for cz in range(min_cz, min_cz + (2 * radius_chunks + 1)):
            for cx in range(min_cx, min_cx + (2 * radius_chunks + 1)):
                tops = self._chunk_top_heights.get(ChunkKey(cx, cz))
                if not tops or len(tops) != 256:
                    continue
                bx0 = (cx - min_cx) * 16
                bz0 = (cz - min_cz) * 16
                for lz in range(16):
                    row = (bz0 + lz) * w + bx0
                    off = lz * 16
                    for lx in range(16):
                        top_y = float(tops[off + lx])
                        vals[row + lx] = (top_y + 1.0) - peel_depth

        data = array.array('f', vals).tobytes()
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._topmap_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_R32F, w, h, 0, GL.GL_RED, GL.GL_FLOAT, data)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        self._topmap_dims = (w, h)
        self._topmap_origin = (float(min_cx * 16), float(min_cz * 16))
        self._topmap_dirty = False
        self._last_topmap_build_target = (tcx, tcz)

    def _draw_plane_gizmo(self, mvp, cut: dict) -> None:
        if not self._gl_ok or not self._line_program or not cut.get('plane_enabled') or not cut.get('plane_show_gizmo'):
            return
        axis = int(cut.get('plane_axis', 1))
        pos = float(cut.get('plane_pos', 0.0))
        tx, ty, tz = self.camera.target

        try:
            if cut.get('use_clipbox'):
                cmin = cut.get('clip_min', (tx - 80.0, ty - 96.0, tz - 80.0))
                cmax = cut.get('clip_max', (tx + 80.0, ty + 96.0, tz + 80.0))
                sx = max(16.0, float(cmax[0] - cmin[0]))
                sy = max(16.0, float(cmax[1] - cmin[1]))
                sz = max(16.0, float(cmax[2] - cmin[2]))
            else:
                sx = sz = max(96.0, float(cut.get('z_half', 64.0)) * 2.0)
                try:
                    ymin, ymax = self._world_height_range
                    sy = max(32.0, float(ymax - ymin))
                except Exception:
                    sy = 384.0
        except Exception:
            sx, sy, sz = 160.0, 256.0, 160.0

        x0, x1 = float(tx - sx * 0.5), float(tx + sx * 0.5)
        y0, y1 = float(ty - sy * 0.5), float(ty + sy * 0.5)
        z0, z1 = float(tz - sz * 0.5), float(tz + sz * 0.5)
        c = (1.0, 0.85, 0.2)
        verts = []

        def add(a, b):
            verts.extend([a[0], a[1], a[2], c[0], c[1], c[2], b[0], b[1], b[2], c[0], c[1], c[2]])

        if axis == 1:  # horizontal Y plane
            y = pos
            p00=(x0,y,z0); p10=(x1,y,z0); p11=(x1,y,z1); p01=(x0,y,z1)
            add(p00,p10); add(p10,p11); add(p11,p01); add(p01,p00)
            add(((x0+x1)*0.5,y,z0), ((x0+x1)*0.5,y,z1))
            add((x0,y,(z0+z1)*0.5), (x1,y,(z0+z1)*0.5))
        elif axis == 0:  # vertical X plane
            x = pos
            p00=(x,y0,z0); p10=(x,y1,z0); p11=(x,y1,z1); p01=(x,y0,z1)
            add(p00,p10); add(p10,p11); add(p11,p01); add(p01,p00)
            add((x,(y0+y1)*0.5,z0), (x,(y0+y1)*0.5,z1))
            add((x,y0,(z0+z1)*0.5), (x,y1,(z0+z1)*0.5))
        else:  # vertical Z plane
            z = pos
            p00=(x0,y0,z); p10=(x1,y0,z); p11=(x1,y1,z); p01=(x0,y1,z)
            add(p00,p10); add(p10,p11); add(p11,p01); add(p01,p00)
            add(((x0+x1)*0.5,y0,z), ((x0+x1)*0.5,y1,z))
            add((x0,(y0+y1)*0.5,z), (x1,(y0+y1)*0.5,z))

        if not verts:
            return
        data = array.array('f', verts).tobytes()
        self._line_vertex_count = len(verts) // 6

        GL.glUseProgram(self._line_program)
        GL.glUniformMatrix4fv(self._u_line_mvp, 1, False, (ctypes.c_float * 16)(*mvp))
        GL.glBindVertexArray(int(self._line_vao))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, int(self._line_vbo))
        GL.glBufferData(GL.GL_ARRAY_BUFFER, len(data), data, GL.GL_DYNAMIC_DRAW)
        GL.glDisable(GL.GL_CULL_FACE)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glLineWidth(1.0)
        GL.glDrawArrays(GL.GL_LINES, 0, int(self._line_vertex_count))
        GL.glLineWidth(1.0)
        if self._cull_faces:
            GL.glEnable(GL.GL_CULL_FACE)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        GL.glBindVertexArray(0)
        GL.glUseProgram(self._program)
