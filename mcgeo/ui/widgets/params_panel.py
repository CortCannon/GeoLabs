from __future__ import annotations
from PySide6 import QtWidgets, QtCore


class ParamsPanel(QtWidgets.QWidget):
    preview_settings_changed = QtCore.Signal(dict)
    view_settings_changed = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ParamsPanel")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Top compact header row ---
        header_row = QtWidgets.QHBoxLayout()
        self._view_mode_label = QtWidgets.QLabel("View mode")
        header_row.addWidget(self._view_mode_label)
        self.view_mode = QtWidgets.QComboBox()
        self.view_mode.addItems(["Surface (fast)"])
        self.view_mode.setMinimumWidth(220)
        header_row.addWidget(self.view_mode, 1)
        # Workflow reset: lock viewport mode to Surface for now (cutaway still available via scene controls)
        self._view_mode_label.setVisible(False)
        self.view_mode.setVisible(False)

        header_row.addWidget(QtWidgets.QLabel("UI"))
        self.ui_mode = QtWidgets.QComboBox()
        self.ui_mode.addItems(["Simple", "Advanced"])
        self.ui_mode.setCurrentText("Simple")
        self.ui_mode.setToolTip("Simple hides rarely used cutaway controls.")
        header_row.addWidget(self.ui_mode)
        layout.addLayout(header_row)

        # --- Main tabs ---
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        # =========================
        # Inspect / Cutaway tab
        # =========================
        inspect_tab = QtWidgets.QWidget()
        inspect_layout = QtWidgets.QVBoxLayout(inspect_tab)
        inspect_layout.setContentsMargins(4, 4, 4, 4)
        inspect_layout.setSpacing(8)

        # Basic cutaway card (minimalist)
        basic_grp = QtWidgets.QGroupBox("Quick cutaway")
        self._basic_grp = basic_grp
        b = QtWidgets.QGridLayout(basic_grp)
        b.setHorizontalSpacing(8)
        b.setVerticalSpacing(6)

        self.cut_enabled = QtWidgets.QCheckBox("Enable cutaway")
        self.cut_enabled.setChecked(True)

        self.terrain_peel = QtWidgets.QCheckBox("Terrain-aware peel")
        self.terrain_peel.setChecked(True)
        self.terrain_peel.setToolTip("Use streamed local top heights when available (better than global top-Y peel).")

        self.peel_enabled = QtWidgets.QCheckBox("Peel from top")
        self.peel_enabled.setChecked(True)
        self.peel_depth = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.peel_depth.setRange(0, 4096)
        self.peel_depth.setValue(96)
        self.peel_depth_spin = QtWidgets.QSpinBox()
        self.peel_depth_spin.setRange(0, 4096)
        self.peel_depth_spin.setValue(96)
        self.peel_depth.setToolTip("Blocks peeled down from terrain top (or global top if terrain-aware off).")
        self.peel_depth_spin.setSuffix(" b")

        self.plane_enabled = QtWidgets.QCheckBox("Cut with plane")
        self.plane_enabled.setChecked(False)
        self.plane_axis = QtWidgets.QComboBox()
        self.plane_axis.addItems(["Y (horizontal)", "X (vertical)", "Z (vertical)"])
        self.plane_axis.setMinimumWidth(130)
        self.plane_follow_camera = QtWidgets.QCheckBox("Follow camera target")
        self.plane_follow_camera.setChecked(True)
        self.plane_position = QtWidgets.QSpinBox()
        self.plane_position.setRange(-1_000_000, 1_000_000)
        self.plane_position.setValue(0)
        self.plane_position.setPrefix("Pos ")
        self.plane_offset = QtWidgets.QSpinBox()
        self.plane_offset.setRange(-4096, 4096)
        self.plane_offset.setValue(0)
        self.plane_offset.setPrefix("Offset ")
        self.plane_offset.setSuffix(" b")
        self.plane_show_gizmo = QtWidgets.QCheckBox("Show gizmo")
        self.plane_show_gizmo.setChecked(True)
        self.plane_keep_positive = QtWidgets.QCheckBox("Keep positive side")
        self.plane_keep_positive.setChecked(False)

        self.btn_cut_preset = QtWidgets.QPushButton("Underground preset")
        self.btn_clear_cut = QtWidgets.QPushButton("Clear")

        row = 0
        b.addWidget(self.cut_enabled, row, 0, 1, 2)
        b.addWidget(self.btn_cut_preset, row, 2)
        b.addWidget(self.btn_clear_cut, row, 3)
        row += 1
        b.addWidget(self.peel_enabled, row, 0)
        b.addWidget(self.terrain_peel, row, 1)
        b.addWidget(QtWidgets.QLabel("Peel depth"), row, 2)
        b.addWidget(self.peel_depth_spin, row, 3)
        row += 1
        b.addWidget(self.peel_depth, row, 0, 1, 4)
        row += 1
        b.addWidget(self.plane_enabled, row, 0)
        b.addWidget(QtWidgets.QLabel("Plane axis"), row, 1)
        b.addWidget(self.plane_axis, row, 2)
        b.addWidget(self.plane_show_gizmo, row, 3)
        row += 1
        b.addWidget(self.plane_follow_camera, row, 0, 1, 2)
        b.addWidget(self.plane_offset, row, 2)
        b.addWidget(self.plane_position, row, 3)
        row += 1
        self._basic_hint = QtWidgets.QLabel(
            "Simple mode shows the essentials: terrain-aware peel + cut plane. "
            "Switch UI to Advanced for Z-slice, clip box, and manual plane side controls."
        )
        self._basic_hint.setWordWrap(True)
        self._basic_hint.setObjectName("SubtleHint")
        b.addWidget(self._basic_hint, row, 0, 1, 4)

        inspect_layout.addWidget(basic_grp)

        # Advanced / expert controls (collapsible)
        self.adv_toggle = QtWidgets.QToolButton()
        self.adv_toggle.setText("Advanced cutaway controls")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setChecked(False)
        self.adv_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.adv_toggle.setArrowType(QtCore.Qt.ArrowType.RightArrow)

        self.adv_panel = QtWidgets.QFrame()
        self.adv_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.adv_panel.setObjectName("AdvancedPanel")
        adv = QtWidgets.QGridLayout(self.adv_panel)
        adv.setContentsMargins(8, 8, 8, 8)
        adv.setHorizontalSpacing(8)
        adv.setVerticalSpacing(6)

        self.zslice_enabled = QtWidgets.QCheckBox("Z slice band")
        self.zslice_enabled.setChecked(False)
        self.zslice_follow_camera = QtWidgets.QCheckBox("Follow camera target Z")
        self.zslice_follow_camera.setChecked(True)
        self.zslice_center = QtWidgets.QSpinBox()
        self.zslice_center.setRange(-1_000_000, 1_000_000)
        self.zslice_center.setValue(0)
        self.zslice_thickness = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.zslice_thickness.setRange(4, 1024)
        self.zslice_thickness.setValue(128)
        self.zslice_thickness_spin = QtWidgets.QSpinBox()
        self.zslice_thickness_spin.setRange(4, 1024)
        self.zslice_thickness_spin.setValue(128)
        self.zslice_thickness_spin.setSuffix(" b")

        self.clipbox_enabled = QtWidgets.QCheckBox("Clip box around camera target")
        self.clipbox_enabled.setChecked(False)
        self.clipbox_size_x = QtWidgets.QSpinBox(); self.clipbox_size_x.setRange(8, 4096); self.clipbox_size_x.setValue(160); self.clipbox_size_x.setSuffix(" b")
        self.clipbox_size_y = QtWidgets.QSpinBox(); self.clipbox_size_y.setRange(8, 4096); self.clipbox_size_y.setValue(192); self.clipbox_size_y.setSuffix(" b")
        self.clipbox_size_z = QtWidgets.QSpinBox(); self.clipbox_size_z.setRange(8, 4096); self.clipbox_size_z.setValue(160); self.clipbox_size_z.setSuffix(" b")

        # Plane expert-only controls still feed existing renderer keys
        self._plane_manual_grp_label = QtWidgets.QLabel("Plane side")
        self._plane_manual_note = QtWidgets.QLabel("Use only when plane clipping is enabled.")
        self._plane_manual_note.setWordWrap(True)
        self._plane_manual_note.setObjectName("SubtleHint")

        row = 0
        adv.addWidget(self.zslice_enabled, row, 0, 1, 2)
        adv.addWidget(self.zslice_follow_camera, row, 2, 1, 2)
        row += 1
        adv.addWidget(QtWidgets.QLabel("Z center"), row, 0)
        adv.addWidget(self.zslice_center, row, 1)
        adv.addWidget(QtWidgets.QLabel("Slice thickness"), row, 2)
        adv.addWidget(self.zslice_thickness_spin, row, 3)
        row += 1
        adv.addWidget(self.zslice_thickness, row, 0, 1, 4)
        row += 1
        adv.addWidget(self.clipbox_enabled, row, 0, 1, 4)
        row += 1
        adv.addWidget(QtWidgets.QLabel("Clip X"), row, 0); adv.addWidget(self.clipbox_size_x, row, 1)
        adv.addWidget(QtWidgets.QLabel("Clip Y"), row, 2); adv.addWidget(self.clipbox_size_y, row, 3)
        row += 1
        adv.addWidget(QtWidgets.QLabel("Clip Z"), row, 0); adv.addWidget(self.clipbox_size_z, row, 1)
        adv.addWidget(self.plane_keep_positive, row, 2, 1, 2)
        row += 1
        adv.addWidget(self._plane_manual_grp_label, row, 0)
        adv.addWidget(self._plane_manual_note, row, 1, 1, 3)

        inspect_layout.addWidget(self.adv_toggle)
        inspect_layout.addWidget(self.adv_panel)

        inspect_hint = QtWidgets.QLabel(
            "Cutaway controls are shader-based and update instantly (no remesh). "
            "Use Underground focus + hide stone/deepslate in Blocks for fast cave/ore inspection."
        )
        inspect_hint.setWordWrap(True)
        inspect_hint.setObjectName("SubtleHint")
        inspect_layout.addWidget(inspect_hint)
        inspect_layout.addStretch(1)

        self.tabs.addTab(inspect_tab, "Inspect / Cutaway")

        # =========================
        # Preview generators tab
        # =========================
        preview_tab = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(4, 4, 4, 4)
        preview_layout.setSpacing(8)

        preview_grp = QtWidgets.QGroupBox("Generator previews (opt-in, non-destructive)")
        self._preview_grp = preview_grp
        g = QtWidgets.QGridLayout(preview_grp)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)

        self.auto_preview = QtWidgets.QCheckBox("Auto update")
        self.auto_preview.setChecked(False)
        self.preview_seed = QtWidgets.QSpinBox()
        self.preview_seed.setRange(0, 2_147_483_647)
        self.preview_seed.setValue(1337)
        self.btn_refresh_preview = QtWidgets.QPushButton("Preview Changes")
        self.btn_preview_showcase = QtWidgets.QPushButton("Create cave + ore preset")
        self.btn_preview_subtle = QtWidgets.QPushButton("Create subtle preset")

        self.caves_enabled = QtWidgets.QCheckBox("Caves")
        self.caves_enabled.setChecked(False)
        self.caves_markers = QtWidgets.QCheckBox("Use cave markers")
        self.caves_markers.setChecked(True)
        self.caves_per_chunk = QtWidgets.QSpinBox()
        self.caves_per_chunk.setRange(0, 16)
        self.caves_per_chunk.setValue(4)
        self.caves_radius = QtWidgets.QSpinBox()
        self.caves_radius.setRange(1, 12)
        self.caves_radius.setValue(4)
        self.caves_min_y = QtWidgets.QSpinBox()
        self.caves_min_y.setRange(-2048, 4096)
        self.caves_min_y.setValue(-64)
        self.caves_max_y = QtWidgets.QSpinBox()
        self.caves_max_y.setRange(-2048, 4096)
        self.caves_max_y.setValue(48)

        self.ores_enabled = QtWidgets.QCheckBox("Ores")
        self.ores_enabled.setChecked(False)
        self.ores_per_chunk = QtWidgets.QSpinBox()
        self.ores_per_chunk.setRange(0, 64)
        self.ores_per_chunk.setValue(14)
        self.ores_radius = QtWidgets.QSpinBox()
        self.ores_radius.setRange(1, 12)
        self.ores_radius.setValue(3)
        self.ores_min_y = QtWidgets.QSpinBox()
        self.ores_min_y.setRange(-2048, 4096)
        self.ores_min_y.setValue(-48)
        self.ores_max_y = QtWidgets.QSpinBox()
        self.ores_max_y.setRange(-2048, 4096)
        self.ores_max_y.setValue(64)

        # compact density row + seed / refresh
        row = 0
        g.addWidget(QtWidgets.QLabel("Seed"), row, 0)
        g.addWidget(self.preview_seed, row, 1)
        g.addWidget(self.auto_preview, row, 2)
        g.addWidget(self.btn_refresh_preview, row, 3)
        row += 1
        g.addWidget(self.btn_preview_showcase, row, 0, 1, 2)
        g.addWidget(self.btn_preview_subtle, row, 2, 1, 2)
        row += 1

        caves_box = QtWidgets.QGroupBox("Cave preview")
        cg = QtWidgets.QGridLayout(caves_box)
        cg.addWidget(self.caves_enabled, 0, 0)
        cg.addWidget(self.caves_markers, 0, 1, 1, 3)
        cg.addWidget(QtWidgets.QLabel("Systems / chunk"), 1, 0)
        cg.addWidget(self.caves_per_chunk, 1, 1)
        cg.addWidget(QtWidgets.QLabel("Radius"), 1, 2)
        cg.addWidget(self.caves_radius, 1, 3)
        cg.addWidget(QtWidgets.QLabel("Min Y"), 2, 0)
        cg.addWidget(self.caves_min_y, 2, 1)
        cg.addWidget(QtWidgets.QLabel("Max Y"), 2, 2)
        cg.addWidget(self.caves_max_y, 2, 3)
        g.addWidget(caves_box, row, 0, 1, 4)
        row += 1

        ores_box = QtWidgets.QGroupBox("Ore preview")
        og = QtWidgets.QGridLayout(ores_box)
        og.addWidget(self.ores_enabled, 0, 0)
        og.addWidget(QtWidgets.QLabel("Bodies / chunk"), 1, 0)
        og.addWidget(self.ores_per_chunk, 1, 1)
        og.addWidget(QtWidgets.QLabel("Radius"), 1, 2)
        og.addWidget(self.ores_radius, 1, 3)
        og.addWidget(QtWidgets.QLabel("Min Y"), 2, 0)
        og.addWidget(self.ores_min_y, 2, 1)
        og.addWidget(QtWidgets.QLabel("Max Y"), 2, 2)
        og.addWidget(self.ores_max_y, 2, 3)
        g.addWidget(ores_box, row, 0, 1, 4)

        preview_layout.addWidget(preview_grp)

        self._generator_state_hint = QtWidgets.QLabel("Generator previews are currently OFF. Use Create Feature or enable Caves/Ores below.")
        self._generator_state_hint.setWordWrap(True)
        self._generator_state_hint.setObjectName("SubtleHint")
        preview_layout.addWidget(self._generator_state_hint)

        self._preview_hint = QtWidgets.QLabel(
            "Nothing is generated on world load. These previews only appear after you enable a generator or use Create Feature."
        )
        self._preview_hint.setWordWrap(True)
        self._preview_hint.setObjectName("SubtleHint")
        preview_layout.addWidget(self._preview_hint)
        preview_layout.addStretch(1)

        self.tabs.addTab(preview_tab, "Generate")

        # Sync sliders/spin boxes
        self.peel_depth.valueChanged.connect(self.peel_depth_spin.setValue)
        self.peel_depth_spin.valueChanged.connect(self.peel_depth.setValue)
        self.zslice_thickness.valueChanged.connect(self.zslice_thickness_spin.setValue)
        self.zslice_thickness_spin.valueChanged.connect(self.zslice_thickness.setValue)

        # Signals (preview)
        preview_widgets = [
            self.preview_seed, self.caves_enabled, self.caves_markers, self.caves_per_chunk, self.caves_radius,
            self.caves_min_y, self.caves_max_y, self.ores_enabled, self.ores_per_chunk, self.ores_radius,
            self.ores_min_y, self.ores_max_y
        ]
        for w in preview_widgets:
            if isinstance(w, QtWidgets.QAbstractButton):
                w.toggled.connect(self._emit_preview_changed_maybe)
            else:
                w.valueChanged.connect(self._emit_preview_changed_maybe)
        self.btn_refresh_preview.clicked.connect(self.emit_preview_settings)
        self.btn_preview_showcase.clicked.connect(self._apply_preview_showcase)
        self.btn_preview_subtle.clicked.connect(self._apply_preview_subtle)
        self._refresh_generator_ui_state()

        # Signals (view / cutaway)
        self.view_mode.currentTextChanged.connect(lambda *_: self.emit_view_settings())
        self.ui_mode.currentTextChanged.connect(lambda *_: self._apply_ui_mode())
        view_widgets = [
            self.cut_enabled, self.peel_enabled, self.peel_depth_spin, self.terrain_peel,
            self.zslice_enabled, self.zslice_follow_camera, self.zslice_center, self.zslice_thickness_spin,
            self.clipbox_enabled, self.clipbox_size_x, self.clipbox_size_y, self.clipbox_size_z,
            self.plane_enabled, self.plane_axis, self.plane_follow_camera, self.plane_position, self.plane_offset,
            self.plane_keep_positive, self.plane_show_gizmo
        ]
        for w in view_widgets:
            if isinstance(w, QtWidgets.QAbstractButton):
                w.toggled.connect(lambda *_: self.emit_view_settings())
            elif isinstance(w, QtWidgets.QComboBox):
                w.currentTextChanged.connect(lambda *_: self.emit_view_settings())
            else:
                w.valueChanged.connect(lambda *_: self.emit_view_settings())

        self.btn_cut_preset.clicked.connect(self._apply_underground_preset)
        self.btn_clear_cut.clicked.connect(self._clear_cutaway)
        self.adv_toggle.toggled.connect(self._on_adv_toggled)

        # Simple declutter: disable inactive controls and hide expert panel in Simple mode
        watch_widgets = [
            self.cut_enabled, self.peel_enabled, self.peel_depth_spin, self.peel_depth,
            self.terrain_peel, self.zslice_enabled, self.zslice_follow_camera, self.zslice_center,
            self.zslice_thickness_spin, self.zslice_thickness, self.clipbox_enabled,
            self.clipbox_size_x, self.clipbox_size_y, self.clipbox_size_z,
            self.plane_enabled, self.plane_axis, self.plane_follow_camera, self.plane_position,
            self.plane_offset, self.plane_keep_positive, self.plane_show_gizmo
        ]
        for w in watch_widgets:
            if isinstance(w, QtWidgets.QAbstractButton):
                w.toggled.connect(self._refresh_cutaway_ui_state)
            elif isinstance(w, QtWidgets.QComboBox):
                w.currentTextChanged.connect(lambda *_: self._refresh_cutaway_ui_state())
            else:
                w.valueChanged.connect(self._refresh_cutaway_ui_state)

        self._apply_ui_mode()
        self._refresh_cutaway_ui_state()

    # ---------------- UI state helpers ----------------
    @QtCore.Slot()
    def _on_adv_toggled(self, checked: bool) -> None:
        self.adv_panel.setVisible(bool(checked))
        self.adv_toggle.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow
        )

    @QtCore.Slot()
    def _apply_ui_mode(self) -> None:
        simple = (self.ui_mode.currentText() == "Simple")
        self.adv_toggle.setVisible(not simple)
        if simple:
            self.adv_toggle.setChecked(False)
            self.adv_panel.setVisible(False)
            self._basic_hint.setVisible(True)
        else:
            self.adv_panel.setVisible(self.adv_toggle.isChecked())
            self._basic_hint.setVisible(False)
        self._refresh_cutaway_ui_state()

    @QtCore.Slot()
    def _refresh_cutaway_ui_state(self, *_):
        cut_on = self.cut_enabled.isChecked()
        peel_on = cut_on and self.peel_enabled.isChecked()
        z_on = cut_on and self.zslice_enabled.isChecked()
        clip_on = cut_on and self.clipbox_enabled.isChecked()
        plane_on = cut_on and self.plane_enabled.isChecked()
        simple = (self.ui_mode.currentText() == "Simple")

        self.peel_enabled.setEnabled(cut_on)
        self.peel_depth.setEnabled(peel_on)
        self.peel_depth_spin.setEnabled(peel_on)
        self.terrain_peel.setEnabled(cut_on and peel_on)

        self.plane_enabled.setEnabled(cut_on)
        self.plane_axis.setEnabled(plane_on)
        self.plane_follow_camera.setEnabled(plane_on)
        self.plane_position.setEnabled(plane_on and (not self.plane_follow_camera.isChecked()))
        self.plane_offset.setEnabled(plane_on)
        self.plane_show_gizmo.setEnabled(plane_on)

        # Advanced controls
        adv_visible = (not simple) and self.adv_toggle.isChecked()
        self.adv_panel.setVisible(adv_visible)
        self.zslice_enabled.setEnabled(cut_on)
        self.zslice_follow_camera.setEnabled(z_on and adv_visible)
        self.zslice_thickness.setEnabled(z_on and adv_visible)
        self.zslice_thickness_spin.setEnabled(z_on and adv_visible)
        self.zslice_center.setEnabled(z_on and adv_visible and (not self.zslice_follow_camera.isChecked()))

        self.clipbox_enabled.setEnabled(cut_on)
        self.clipbox_size_x.setEnabled(clip_on and adv_visible)
        self.clipbox_size_y.setEnabled(clip_on and adv_visible)
        self.clipbox_size_z.setEnabled(clip_on and adv_visible)

        self.plane_keep_positive.setEnabled(plane_on and adv_visible)
        self._plane_manual_grp_label.setEnabled(plane_on and adv_visible)
        self._plane_manual_note.setEnabled(plane_on and adv_visible)


    def _refresh_generator_ui_state(self) -> None:
        enabled = bool(self.caves_enabled.isChecked() or self.ores_enabled.isChecked())
        if hasattr(self, "_generator_state_hint"):
            if enabled:
                parts = []
                if self.caves_enabled.isChecked():
                    parts.append("caves")
                if self.ores_enabled.isChecked():
                    parts.append("ores")
                self._generator_state_hint.setText(
                    "Preview active: " + " + ".join(parts).title() + " (non-destructive)"
                )
            else:
                self._generator_state_hint.setText(
                    "Generator previews are currently OFF. Use Create Feature or enable Caves/Ores below."
                )

    def has_generator_preview_enabled(self) -> bool:
        return bool(self.caves_enabled.isChecked() or self.ores_enabled.isChecked())

    def active_generator_labels(self) -> list[str]:
        labels: list[str] = []
        if self.caves_enabled.isChecked():
            labels.append("caves")
        if self.ores_enabled.isChecked():
            labels.append("ores")
        return labels

    def disable_all_generator_previews(self, emit: bool = True) -> None:
        self.caves_enabled.setChecked(False)
        self.ores_enabled.setChecked(False)
        self._refresh_generator_ui_state()
        if emit:
            self.emit_preview_settings()

    def enable_generator_preview(self, kind: str, subtle: bool = True, emit: bool = True) -> None:
        kind = str(kind).strip().lower()
        if subtle:
            if kind == "caves":
                self.caves_markers.setChecked(True)
                self.caves_per_chunk.setValue(2)
                self.caves_radius.setValue(3)
                self.caves_min_y.setValue(-64)
                self.caves_max_y.setValue(32)
            elif kind == "ores":
                self.ores_per_chunk.setValue(8)
                self.ores_radius.setValue(2)
                self.ores_min_y.setValue(-48)
                self.ores_max_y.setValue(48)
        if kind == "caves":
            self.caves_enabled.setChecked(True)
        elif kind == "ores":
            self.ores_enabled.setChecked(True)
        elif kind in {"caves+ores", "ore+cave", "cave+ore", "both"}:
            self.caves_enabled.setChecked(True)
            self.ores_enabled.setChecked(True)
        self._refresh_generator_ui_state()
        if emit:
            self.emit_preview_settings()

    # ---------------- Public settings API ----------------
    def preview_settings(self) -> dict:
        cmin = int(self.caves_min_y.value())
        cmax = int(self.caves_max_y.value())
        omin = int(self.ores_min_y.value())
        omax = int(self.ores_max_y.value())
        if cmax < cmin:
            cmin, cmax = cmax, cmin
        if omax < omin:
            omin, omax = omax, omin
        return {
            "enabled": bool(self.caves_enabled.isChecked() or self.ores_enabled.isChecked()),
            "seed": int(self.preview_seed.value()),
            "caves_enabled": bool(self.caves_enabled.isChecked()),
            "caves_markers": bool(self.caves_markers.isChecked()),
            "caves_per_chunk": int(self.caves_per_chunk.value()),
            "caves_radius": int(self.caves_radius.value()),
            "caves_min_y": cmin,
            "caves_max_y": cmax,
            "ores_enabled": bool(self.ores_enabled.isChecked()),
            "ores_per_chunk": int(self.ores_per_chunk.value()),
            "ores_radius": int(self.ores_radius.value()),
            "ores_min_y": omin,
            "ores_max_y": omax,
        }

    def view_settings(self) -> dict:
        return {
            "view_mode": self.view_mode.currentText(),
            "cut_enabled": bool(self.cut_enabled.isChecked()),
            "peel_enabled": bool(self.peel_enabled.isChecked()),
            "peel_depth": int(self.peel_depth_spin.value()),
            "terrain_peel": bool(self.terrain_peel.isChecked()),
            "zslice_enabled": bool(self.zslice_enabled.isChecked()),
            "zslice_follow_camera": bool(self.zslice_follow_camera.isChecked()),
            "zslice_center": int(self.zslice_center.value()),
            "zslice_thickness": int(self.zslice_thickness_spin.value()),
            "clipbox_enabled": bool(self.clipbox_enabled.isChecked()),
            "clipbox_size_x": int(self.clipbox_size_x.value()),
            "clipbox_size_y": int(self.clipbox_size_y.value()),
            "clipbox_size_z": int(self.clipbox_size_z.value()),
            "plane_enabled": bool(self.plane_enabled.isChecked()),
            "plane_axis": self.plane_axis.currentText(),
            "plane_follow_camera": bool(self.plane_follow_camera.isChecked()),
            "plane_position": int(self.plane_position.value()),
            "plane_offset": int(self.plane_offset.value()),
            "plane_keep_positive": bool(self.plane_keep_positive.isChecked()),
            "plane_show_gizmo": bool(self.plane_show_gizmo.isChecked()),
        }

    def apply_preview_settings(self, settings: dict, *, emit: bool = True) -> None:
        data = dict(settings or {})
        widgets = [
            self.caves_enabled, self.caves_markers, self.caves_per_chunk, self.caves_radius,
            self.caves_min_y, self.caves_max_y, self.ores_enabled, self.ores_per_chunk,
            self.ores_radius, self.ores_min_y, self.ores_max_y, self.preview_seed,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.preview_seed.setValue(int(data.get("seed", self.preview_seed.value())))
            self.caves_enabled.setChecked(bool(data.get("caves_enabled", self.caves_enabled.isChecked())))
            self.caves_markers.setChecked(bool(data.get("caves_markers", self.caves_markers.isChecked())))
            self.caves_per_chunk.setValue(int(data.get("caves_per_chunk", self.caves_per_chunk.value())))
            self.caves_radius.setValue(int(data.get("caves_radius", self.caves_radius.value())))
            self.caves_min_y.setValue(int(data.get("caves_min_y", self.caves_min_y.value())))
            self.caves_max_y.setValue(int(data.get("caves_max_y", self.caves_max_y.value())))
            self.ores_enabled.setChecked(bool(data.get("ores_enabled", self.ores_enabled.isChecked())))
            self.ores_per_chunk.setValue(int(data.get("ores_per_chunk", self.ores_per_chunk.value())))
            self.ores_radius.setValue(int(data.get("ores_radius", self.ores_radius.value())))
            self.ores_min_y.setValue(int(data.get("ores_min_y", self.ores_min_y.value())))
            self.ores_max_y.setValue(int(data.get("ores_max_y", self.ores_max_y.value())))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._refresh_generator_ui_state()
        if emit:
            self.emit_preview_settings()

    def apply_view_settings(self, settings: dict, *, emit: bool = True) -> None:
        data = dict(settings or {})

        def _set_combo(combo, value):
            text = str(value or "").strip()
            idx = combo.findText(text)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        widgets = [
            self.view_mode, self.cut_enabled, self.peel_enabled, self.peel_depth_spin, self.terrain_peel,
            self.zslice_enabled, self.zslice_follow_camera, self.zslice_center, self.zslice_thickness_spin,
            self.clipbox_enabled, self.clipbox_size_x, self.clipbox_size_y, self.clipbox_size_z,
            self.plane_enabled, self.plane_axis, self.plane_follow_camera, self.plane_position,
            self.plane_offset, self.plane_keep_positive, self.plane_show_gizmo,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            _set_combo(self.view_mode, data.get("view_mode", self.view_mode.currentText()))
            self.cut_enabled.setChecked(bool(data.get("cut_enabled", self.cut_enabled.isChecked())))
            self.peel_enabled.setChecked(bool(data.get("peel_enabled", self.peel_enabled.isChecked())))
            self.peel_depth_spin.setValue(int(data.get("peel_depth", self.peel_depth_spin.value())))
            self.terrain_peel.setChecked(bool(data.get("terrain_peel", self.terrain_peel.isChecked())))
            self.zslice_enabled.setChecked(bool(data.get("zslice_enabled", self.zslice_enabled.isChecked())))
            self.zslice_follow_camera.setChecked(bool(data.get("zslice_follow_camera", self.zslice_follow_camera.isChecked())))
            self.zslice_center.setValue(int(data.get("zslice_center", self.zslice_center.value())))
            self.zslice_thickness_spin.setValue(int(data.get("zslice_thickness", self.zslice_thickness_spin.value())))
            self.clipbox_enabled.setChecked(bool(data.get("clipbox_enabled", self.clipbox_enabled.isChecked())))
            self.clipbox_size_x.setValue(int(data.get("clipbox_size_x", self.clipbox_size_x.value())))
            self.clipbox_size_y.setValue(int(data.get("clipbox_size_y", self.clipbox_size_y.value())))
            self.clipbox_size_z.setValue(int(data.get("clipbox_size_z", self.clipbox_size_z.value())))
            self.plane_enabled.setChecked(bool(data.get("plane_enabled", self.plane_enabled.isChecked())))
            _set_combo(self.plane_axis, data.get("plane_axis", self.plane_axis.currentText()))
            self.plane_follow_camera.setChecked(bool(data.get("plane_follow_camera", self.plane_follow_camera.isChecked())))
            self.plane_position.setValue(int(data.get("plane_position", self.plane_position.value())))
            self.plane_offset.setValue(int(data.get("plane_offset", self.plane_offset.value())))
            self.plane_keep_positive.setChecked(bool(data.get("plane_keep_positive", self.plane_keep_positive.isChecked())))
            self.plane_show_gizmo.setChecked(bool(data.get("plane_show_gizmo", self.plane_show_gizmo.isChecked())))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._refresh_cutaway_ui_state()
        if emit:
            self.emit_view_settings()

    @QtCore.Slot()
    def emit_preview_settings(self) -> None:
        self._refresh_generator_ui_state()
        self.preview_settings_changed.emit(self.preview_settings())

    @QtCore.Slot()
    def emit_view_settings(self) -> None:
        self.view_settings_changed.emit(self.view_settings())

    @QtCore.Slot()
    def _emit_preview_changed_maybe(self, *_):
        self._refresh_generator_ui_state()
        if self.auto_preview.isChecked():
            self.emit_preview_settings()

    # ---------------- Presets ----------------
    @QtCore.Slot()
    def _apply_underground_preset(self) -> None:
        self.cut_enabled.setChecked(True)
        self.peel_enabled.setChecked(True)
        self.terrain_peel.setChecked(True)
        self.peel_depth_spin.setValue(max(96, int(self.peel_depth_spin.value())))
        self.plane_enabled.setChecked(False)
        # Keep advanced off in simple mode; advanced users can enable extras
        self.zslice_enabled.setChecked(False)
        self.clipbox_enabled.setChecked(False)
        self._refresh_cutaway_ui_state()
        self.emit_view_settings()

    @QtCore.Slot()
    def _clear_cutaway(self) -> None:
        self.cut_enabled.setChecked(False)
        self.peel_enabled.setChecked(False)
        self.zslice_enabled.setChecked(False)
        self.clipbox_enabled.setChecked(False)
        self.plane_enabled.setChecked(False)
        self._refresh_cutaway_ui_state()
        self.emit_view_settings()

    @QtCore.Slot()
    def _apply_preview_showcase(self) -> None:
        self.caves_enabled.setChecked(True)
        self.caves_markers.setChecked(True)
        self.caves_per_chunk.setValue(4)
        self.caves_radius.setValue(4)
        self.caves_min_y.setValue(-64)
        self.caves_max_y.setValue(48)
        self.ores_enabled.setChecked(True)
        self.ores_per_chunk.setValue(14)
        self.ores_radius.setValue(3)
        self.ores_min_y.setValue(-48)
        self.ores_max_y.setValue(64)
        self.emit_preview_settings()

    @QtCore.Slot()
    def _apply_preview_subtle(self) -> None:
        self.caves_enabled.setChecked(True)
        self.caves_markers.setChecked(True)
        self.caves_per_chunk.setValue(2)
        self.caves_radius.setValue(3)
        self.caves_min_y.setValue(-64)
        self.caves_max_y.setValue(32)
        self.ores_enabled.setChecked(True)
        self.ores_per_chunk.setValue(8)
        self.ores_radius.setValue(2)
        self.ores_min_y.setValue(-48)
        self.ores_max_y.setValue(48)
        self.emit_preview_settings()
