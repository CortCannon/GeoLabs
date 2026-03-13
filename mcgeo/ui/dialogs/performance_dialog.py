from __future__ import annotations
import os
from PySide6 import QtWidgets, QtCore


class _IntSliderRow(QtWidgets.QWidget):
    value_changed = QtCore.Signal(int)

    def __init__(self, label: str, min_v: int, max_v: int, step: int = 1, suffix: str = "") -> None:
        super().__init__()
        self._min = int(min_v)
        self._max = int(max_v)

        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(8)

        self.label = QtWidgets.QLabel(label)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(self._min, self._max)
        self.slider.setSingleStep(step)

        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(self._min, self._max)
        self.spin.setSingleStep(step)
        if suffix:
            self.spin.setSuffix(suffix)

        lay.addWidget(self.label, 0, 0)
        lay.addWidget(self.slider, 0, 1)
        lay.addWidget(self.spin, 0, 2)

        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def _from_slider(self, v: int) -> None:
        if self.spin.value() != v:
            self.spin.setValue(v)
        self.value_changed.emit(int(v))

    def _from_spin(self, v: int) -> None:
        if self.slider.value() != v:
            self.slider.setValue(v)
        self.value_changed.emit(int(v))

    def setValue(self, v: int) -> None:
        v = max(self._min, min(self._max, int(v)))
        self.spin.setValue(v)

    def value(self) -> int:
        return int(self.spin.value())


class PerformanceDialog(QtWidgets.QDialog):
    """Process-backend performance tuning dialog (no Qt thread fallback)."""

    def __init__(self, parent=None, renderer_mgr=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Performance")
        self.setModal(False)
        self.resize(760, 820)

        self.renderer_mgr = renderer_mgr
        self._updating_ui = False
        self._cpu_count = max(1, os.cpu_count() or 1)

        root = QtWidgets.QVBoxLayout(self)

        # ---------- Presets ----------
        presets_box = QtWidgets.QGroupBox("Presets")
        p_lay = QtWidgets.QGridLayout(presets_box)

        self.presets = QtWidgets.QComboBox()
        self.presets.addItems([
            "Fast navigation",
            "Balanced",
            "High quality preview",
            "CPU saturate (max throughput)",
            "Huge world streaming",
        ])
        self.btn_apply_preset = QtWidgets.QPushButton("Apply preset")
        self.btn_use_all_cores = QtWidgets.QPushButton("Use all logical cores")
        self.chk_live_apply = QtWidgets.QCheckBox("Live apply")
        self.chk_live_apply.setChecked(True)

        p_lay.addWidget(QtWidgets.QLabel("Preset"), 0, 0)
        p_lay.addWidget(self.presets, 0, 1)
        p_lay.addWidget(self.btn_apply_preset, 0, 2)
        p_lay.addWidget(self.btn_use_all_cores, 1, 1)
        p_lay.addWidget(self.chk_live_apply, 1, 2)

        self.lbl_backend = QtWidgets.QLabel("Build backend: <b>Processes</b> (fixed in this build)")
        self.lbl_backend.setWordWrap(True)
        p_lay.addWidget(self.lbl_backend, 2, 0, 1, 3)

        root.addWidget(presets_box)

        # ---------- Streaming / Build ----------
        stream_box = QtWidgets.QGroupBox("Streaming / Build")
        s_lay = QtWidgets.QVBoxLayout(stream_box)

        self.row_workers = _IntSliderRow("Workers", 1, max(2, self._cpu_count * 2), 1)
        self.row_sched = _IntSliderRow("Schedule budget / tick", 1, 4096, 1)
        self.row_stream_tick = _IntSliderRow("Stream tick", 10, 500, 1, " ms")
        self.row_near = _IntSliderRow("Near ring (voxel)", 1, 24, 1, " chunks")
        self.row_uploads = _IntSliderRow("Max GL uploads / frame", 1, 512, 1)
        self.row_base_cache = _IntSliderRow("Base mesh cache", 128, 16384, 64, " chunks")
        self.row_preview_cache = _IntSliderRow("Preview mesh cache", 128, 16384, 64, " entries")

        for w in [
            self.row_workers,
            self.row_sched,
            self.row_stream_tick,
            self.row_near,
            self.row_uploads,
            self.row_base_cache,
            self.row_preview_cache,
        ]:
            s_lay.addWidget(w)

        self._hint = QtWidgets.QLabel(
            "This build uses ProcessPool meshing only (no Qt thread fallback). "
            "Increase Workers + Schedule Budget to push CPU harder. "
            "Larger mesh caches keep previously built terrain in memory so layer preview changes do less rebuilding."
        )
        self._hint.setWordWrap(True)
        s_lay.addWidget(self._hint)
        root.addWidget(stream_box)

        # ---------- Rendering ----------
        render_box = QtWidgets.QGroupBox("Rendering")
        r_lay = QtWidgets.QVBoxLayout(render_box)
        self.row_target_fps = _IntSliderRow("Target redraw FPS", 1, 240, 1)
        self.chk_cull = QtWidgets.QCheckBox("Enable back-face culling (faster; leave off while validating mesh winding)")
        self.chk_cull.setChecked(False)
        r_lay.addWidget(self.row_target_fps)
        r_lay.addWidget(self.chk_cull)
        root.addWidget(render_box)

        # ---------- Live stats ----------
        stats_box = QtWidgets.QGroupBox("Live stats")
        g = QtWidgets.QGridLayout(stats_box)
        self._stats_labels = {}
        labels = [
            ("fps", "FPS"),
            ("draw_ms", "Draw time"),
            ("resident", "Resident chunks"),
            ("inflight", "Inflight builds"),
            ("meshes", "GL meshes"),
            ("pending_uploads", "Pending uploads"),
            ("uploads_last_frame", "Uploads/frame"),
            ("build_backend", "Build backend"),
            ("workers", "Workers"),
            ("schedule_budget", "Schedule budget"),
            ("stream_tick_ms", "Stream tick"),
            ("near_ring", "Near ring"),
            ("cull_faces", "Culling"),
            ("base_cache_entries", "Base cache used"),
            ("base_cache_limit", "Base cache limit"),
            ("preview_cache_entries", "Preview cache used"),
            ("preview_cache_limit", "Preview cache limit"),
            ("base_hits", "Base cache hits"),
            ("base_misses", "Base cache misses"),
            ("preview_hits", "Preview cache hits"),
            ("preview_misses", "Preview cache misses"),
            ("process_cache_hits", "Worker cache hits"),
            ("process_cache_misses", "Worker cache misses"),
        ]
        for row, (key, label) in enumerate(labels):
            g.addWidget(QtWidgets.QLabel(label), row, 0)
            v = QtWidgets.QLabel("—")
            v.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            g.addWidget(v, row, 1)
            self._stats_labels[key] = v
        root.addWidget(stats_box, 1)

        btns = QtWidgets.QHBoxLayout()
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_apply = QtWidgets.QPushButton("Apply")
        self.btn_close = QtWidgets.QPushButton("Close")
        btns.addStretch(1)
        btns.addWidget(self.btn_refresh)
        btns.addWidget(self.btn_apply)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        self.btn_apply_preset.clicked.connect(self._apply_selected_preset)
        self.btn_use_all_cores.clicked.connect(self._on_use_all_cores)
        self.btn_refresh.clicked.connect(self.refresh_from_renderer)
        self.btn_apply.clicked.connect(self.apply_to_renderer)
        self.btn_close.clicked.connect(self.close)

        for row in [
            self.row_workers, self.row_sched, self.row_stream_tick, self.row_near,
            self.row_uploads, self.row_target_fps, self.row_base_cache, self.row_preview_cache
        ]:
            row.value_changed.connect(self._live_apply_maybe)
        self.chk_cull.toggled.connect(self._live_apply_maybe)

        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self.refresh_stats_only)
        self._poll.start(500)

        self.refresh_from_renderer()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_from_renderer()

    @QtCore.Slot()
    def _on_use_all_cores(self) -> None:
        self.row_workers.setValue(self._cpu_count)
        self._live_apply_maybe()

    @QtCore.Slot()
    def _apply_selected_preset(self) -> None:
        preset = self.presets.currentText()
        if preset.startswith("Fast"):
            vals = dict(
                workers=max(1, min(self._cpu_count, 6)),
                schedule_budget=max(64, self._cpu_count * 8),
                stream_tick_ms=33, near_ring=3,
                target_fps=60, max_uploads_per_frame=24,
                cull_faces=False, base_mesh_cache_entries=2048, preview_mesh_cache_entries=1024
            )
        elif preset.startswith("Balanced"):
            vals = dict(
                workers=max(1, self._cpu_count),
                schedule_budget=max(192, self._cpu_count * 24),
                stream_tick_ms=20, near_ring=4,
                target_fps=90, max_uploads_per_frame=64,
                cull_faces=False, base_mesh_cache_entries=4096, preview_mesh_cache_entries=2048
            )
        elif preset.startswith("High quality"):
            vals = dict(
                workers=max(1, self._cpu_count),
                schedule_budget=max(384, self._cpu_count * 32),
                stream_tick_ms=16, near_ring=6,
                target_fps=120, max_uploads_per_frame=128,
                cull_faces=False, base_mesh_cache_entries=6144, preview_mesh_cache_entries=4096
            )
        elif preset.startswith("CPU saturate"):
            vals = dict(
                workers=max(1, self._cpu_count),
                schedule_budget=1024, stream_tick_ms=10,
                near_ring=8, target_fps=144, max_uploads_per_frame=192,
                cull_faces=False, base_mesh_cache_entries=8192, preview_mesh_cache_entries=4096
            )
        else:  # Huge world streaming
            vals = dict(
                workers=max(1, self._cpu_count),
                schedule_budget=768, stream_tick_ms=15,
                near_ring=4, target_fps=90, max_uploads_per_frame=128,
                cull_faces=False, base_mesh_cache_entries=12288, preview_mesh_cache_entries=2048
            )

        self._set_controls(vals)
        self._live_apply_maybe(force=True)

    def _set_controls(self, s: dict) -> None:
        self._updating_ui = True
        try:
            self.row_workers.setValue(int(s.get("workers", self.row_workers.value())))
            self.row_sched.setValue(int(s.get("schedule_budget", self.row_sched.value())))
            self.row_stream_tick.setValue(int(s.get("stream_tick_ms", self.row_stream_tick.value())))
            self.row_near.setValue(int(s.get("near_ring", self.row_near.value())))
            self.row_target_fps.setValue(int(s.get("target_fps", self.row_target_fps.value())))
            self.row_uploads.setValue(int(s.get("max_uploads_per_frame", self.row_uploads.value())))
            self.row_base_cache.setValue(int(s.get("base_mesh_cache_entries", self.row_base_cache.value())))
            self.row_preview_cache.setValue(int(s.get("preview_mesh_cache_entries", self.row_preview_cache.value())))
            self.chk_cull.setChecked(bool(s.get("cull_faces", self.chk_cull.isChecked())))
        finally:
            self._updating_ui = False

    def _collect_settings(self) -> dict:
        return {
            "workers": self.row_workers.value(),
            "schedule_budget": self.row_sched.value(),
            "stream_tick_ms": self.row_stream_tick.value(),
            "near_ring": self.row_near.value(),
            "target_fps": self.row_target_fps.value(),
            "max_uploads_per_frame": self.row_uploads.value(),
            "base_mesh_cache_entries": self.row_base_cache.value(),
            "preview_mesh_cache_entries": self.row_preview_cache.value(),
            "cull_faces": self.chk_cull.isChecked(),
            # Compatibility key; renderer ignores non-process backends in this build.
            "build_backend": "processes",
        }

    @QtCore.Slot()
    def _live_apply_maybe(self, *_, force: bool = False) -> None:
        if self._updating_ui:
            return
        if force or self.chk_live_apply.isChecked():
            self.apply_to_renderer()

    @QtCore.Slot()
    def apply_to_renderer(self) -> None:
        if not self.renderer_mgr:
            return
        self.renderer_mgr.apply_performance_settings(self._collect_settings())
        self.refresh_stats_only()

    @QtCore.Slot()
    def refresh_from_renderer(self) -> None:
        if not self.renderer_mgr:
            return
        settings = self.renderer_mgr.get_performance_settings() or {}
        if settings:
            self._set_controls(settings)
        self.refresh_stats_only()

    @QtCore.Slot()
    def refresh_stats_only(self) -> None:
        if not self.renderer_mgr:
            return
        snap = self.renderer_mgr.get_performance_snapshot() or {}
        for k, lab in self._stats_labels.items():
            v = snap.get(k, "—")
            if isinstance(v, float):
                if k == "fps":
                    text = f"{v:.1f}"
                elif k == "draw_ms":
                    text = f"{v:.2f} ms"
                else:
                    text = f"{v:.2f}"
            else:
                text = str(v)
            lab.setText(text)
