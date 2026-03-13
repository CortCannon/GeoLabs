from __future__ import annotations

import logging

from PySide6 import QtCore, QtWidgets

log = logging.getLogger("mcgeo.render")


class RendererManager(QtCore.QObject):
    """Strict OpenGL renderer manager (no automatic SW fallback)."""

    materials_changed = QtCore.Signal(object)  # list[str]
    paint_hover_changed = QtCore.Signal(dict)
    paint_stroke_committed = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._world_index = None
        self._mode = "Surface (fast)"
        self._preview_settings: dict = {}
        self._view_settings: dict = {}

        from .gl_viewport import GLViewport

        self._gl = GLViewport()
        self._gl.gl_failed.connect(self._on_gl_failed)
        if hasattr(self._gl, "materials_changed"):
            self._gl.materials_changed.connect(self.materials_changed)
        if hasattr(self._gl, "paint_hover_changed"):
            self._gl.paint_hover_changed.connect(self.paint_hover_changed)
        if hasattr(self._gl, "paint_stroke_committed"):
            self._gl.paint_stroke_committed.connect(self.paint_stroke_committed)

        log.info("Renderer selected: OpenGL (strict mode; no SW fallback)")

    def create_viewport(self) -> QtWidgets.QWidget:
        return self._gl

    def _on_gl_failed(self, reason: str) -> None:
        log.error("OpenGL runtime init failed (strict mode, no fallback): %s", reason)
        try:
            QtWidgets.QMessageBox.critical(None, "OpenGL initialization failed", reason)
        except Exception:
            pass

    def set_world_index(self, world_index) -> None:
        self._world_index = world_index
        if hasattr(self._gl, "set_world_index"):
            self._gl.set_world_index(world_index)

    def set_view_mode(self, mode: str) -> None:
        self._mode = mode
        if hasattr(self._gl, "set_view_mode"):
            self._gl.set_view_mode(mode)

    def set_preview_settings(self, settings: dict) -> None:
        self._preview_settings = dict(settings or {})
        if hasattr(self._gl, "set_preview_settings"):
            self._gl.set_preview_settings(self._preview_settings)

    def set_view_settings(self, settings: dict) -> None:
        self._view_settings = dict(settings or {})
        if hasattr(self._gl, "set_view_settings"):
            self._gl.set_view_settings(self._view_settings)

    def set_paint_settings(self, settings: dict) -> None:
        if hasattr(self._gl, "set_paint_settings"):
            self._gl.set_paint_settings(settings)

    def request_paint_realign(self) -> None:
        if hasattr(self._gl, "request_paint_realign"):
            self._gl.request_paint_realign()

    def set_material_visibility(self, vis: dict[str, bool]) -> None:
        if hasattr(self._gl, "set_material_visibility"):
            self._gl.set_material_visibility(vis)

    def set_edit_area_chunk_bounds(self, bounds) -> None:
        if hasattr(self._gl, "set_edit_area_chunk_bounds"):
            self._gl.set_edit_area_chunk_bounds(bounds)

    def set_loading_paused(self, paused: bool) -> None:
        if hasattr(self._gl, "set_loading_paused"):
            self._gl.set_loading_paused(bool(paused))

    def preload_selected_area_voxel_cache(self, bounds=None, *, progress_cb=None, cancel_check=None) -> dict:
        if hasattr(self._gl, "preload_selected_area_voxel_cache"):
            return self._gl.preload_selected_area_voxel_cache(bounds, progress_cb=progress_cb, cancel_check=cancel_check)
        return {"total": 0, "done": 0, "built": 0, "failed": 0, "cancelled": False}

    def focus_chunk(self, cx: int, cz: int) -> None:
        if hasattr(self._gl, "focus_chunk"):
            self._gl.focus_chunk(cx, cz)

    def apply_performance_settings(self, settings: dict) -> None:
        if hasattr(self._gl, "apply_performance_settings"):
            self._gl.apply_performance_settings(settings)

    def get_performance_settings(self) -> dict:
        if hasattr(self._gl, "get_performance_settings"):
            return self._gl.get_performance_settings()
        return {}

    def get_performance_snapshot(self) -> dict:
        if hasattr(self._gl, "get_performance_snapshot"):
            return self._gl.get_performance_snapshot()
        return {}

    def invalidate_all_meshes(self) -> None:
        """Request a full preview remesh/restream. Safe no-op if viewport lacks API."""
        gl = getattr(self, "_gl", None)
        if gl is None:
            return
        if hasattr(gl, "invalidate_all_meshes"):
            gl.invalidate_all_meshes()
            return
        if hasattr(gl, "_invalidate_all_meshes_for_rebuild"):
            gl._invalidate_all_meshes_for_rebuild()

    def invalidate_preview_chunks(self, chunks) -> None:
        if hasattr(self._gl, "invalidate_preview_chunks"):
            self._gl.invalidate_preview_chunks(chunks)

    def invalidate_preview_block_box(self, bbox, padding_blocks: int = 0) -> None:
        if hasattr(self._gl, "invalidate_preview_block_box"):
            self._gl.invalidate_preview_block_box(bbox, padding_blocks=padding_blocks)
