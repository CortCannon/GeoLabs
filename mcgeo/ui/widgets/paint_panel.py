from __future__ import annotations
from PySide6 import QtWidgets, QtCore


class PaintPanel(QtWidgets.QWidget):
    paint_settings_changed = QtCore.Signal(dict)
    add_layer_requested = QtCore.Signal(str)
    import_model_requested = QtCore.Signal()
    focus_paint_requested = QtCore.Signal()
    realign_requested = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("PaintPanel")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("3D Painter (preview)")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Paint strokes now build real non-destructive preview edits in the 3D world. "
            "Apply-to-world is still a later milestone."
        )
        subtitle.setObjectName("SubtleHint")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ----- quick row -----
        quick = QtWidgets.QGroupBox("Quick controls")
        qg = QtWidgets.QGridLayout(quick)
        qg.setHorizontalSpacing(8)
        qg.setVerticalSpacing(6)

        self.paint_enabled = QtWidgets.QCheckBox("Enable paint mode")
        self.paint_enabled.setChecked(False)
        self.btn_focus = QtWidgets.QPushButton("Use Painter")
        self.btn_add_layer = QtWidgets.QPushButton("Add layer")

        self.active_layer = QtWidgets.QComboBox()
        self.active_layer.setEditable(True)
        self.active_layer.addItems([
            "Paint: Ore pass A",
            "Paint: Cave carve A",
        ])
        self.active_layer.setEditText("Paint: Ore pass A")

        qg.addWidget(self.paint_enabled, 0, 0, 1, 2)
        qg.addWidget(self.btn_focus, 0, 2)
        qg.addWidget(self.btn_add_layer, 0, 3)
        qg.addWidget(QtWidgets.QLabel("Active layer"), 1, 0)
        qg.addWidget(self.active_layer, 1, 1, 1, 3)
        layout.addWidget(quick)

        # ----- brush card -----
        brush = QtWidgets.QGroupBox("Brush")
        bg = QtWidgets.QGridLayout(brush)
        bg.setHorizontalSpacing(8)
        bg.setVerticalSpacing(6)

        self.action = QtWidgets.QComboBox()
        self.action.addItems([
            "Replace blocks",
            "Fill material",
            "Erase blocks",
            "Carve cave (preview)",
            "Paint ore mask",
            "Stamp blueprint (preview)",
        ])

        self.material = QtWidgets.QComboBox()
        self.material.setEditable(True)
        self.material.addItems([
            "minecraft:iron_ore",
            "minecraft:deepslate_iron_ore",
            "minecraft:stone",
            "minecraft:deepslate",
            "minecraft:air",
        ])
        self.material.setCurrentText("minecraft:iron_ore")

        self.shape = QtWidgets.QComboBox()
        self.shape.addItems(["Sphere", "Blob", "Disc", "Tunnel brush", "Box"])

        self.size = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.size.setRange(1, 64)
        self.size.setValue(8)
        self.size_spin = QtWidgets.QSpinBox()
        self.size_spin.setRange(1, 64)
        self.size_spin.setValue(8)
        self.size_spin.setSuffix(" b")

        self.strength = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.strength.setRange(1, 100)
        self.strength.setValue(100)
        self.strength_spin = QtWidgets.QSpinBox()
        self.strength_spin.setRange(1, 100)
        self.strength_spin.setValue(100)
        self.strength_spin.setSuffix(" %")

        self.spacing = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.spacing.setRange(1, 200)
        self.spacing.setValue(25)
        self.spacing_spin = QtWidgets.QSpinBox()
        self.spacing_spin.setRange(1, 200)
        self.spacing_spin.setValue(25)
        self.spacing_spin.setSuffix(" % radius")

        self.falloff = QtWidgets.QComboBox()
        self.falloff.addItems(["Constant", "Linear", "Smoothstep", "Noise edge"])

        bg.addWidget(QtWidgets.QLabel("Action"), 0, 0)
        bg.addWidget(self.action, 0, 1)
        bg.addWidget(QtWidgets.QLabel("Material"), 0, 2)
        bg.addWidget(self.material, 0, 3)
        bg.addWidget(QtWidgets.QLabel("Shape"), 1, 0)
        bg.addWidget(self.shape, 1, 1)
        bg.addWidget(QtWidgets.QLabel("Falloff"), 1, 2)
        bg.addWidget(self.falloff, 1, 3)
        bg.addWidget(QtWidgets.QLabel("Brush size"), 2, 0)
        bg.addWidget(self.size, 2, 1, 1, 2)
        bg.addWidget(self.size_spin, 2, 3)
        bg.addWidget(QtWidgets.QLabel("Strength"), 3, 0)
        bg.addWidget(self.strength, 3, 1, 1, 2)
        bg.addWidget(self.strength_spin, 3, 3)
        bg.addWidget(QtWidgets.QLabel("Stroke spacing"), 4, 0)
        bg.addWidget(self.spacing, 4, 1, 1, 2)
        bg.addWidget(self.spacing_spin, 4, 3)

        layout.addWidget(brush)

        # ----- targeting / constraints -----
        target = QtWidgets.QGroupBox("Brush placement / constraints")
        tg = QtWidgets.QGridLayout(target)
        tg.setHorizontalSpacing(8)
        tg.setVerticalSpacing(6)

        self.target_help = QtWidgets.QLabel(
            "Brush cursor is automatic: it snaps to solid blocks under the cursor when available, and otherwise stays at the current 3D brush depth so you can paint anywhere inside the selected area."
        )
        self.target_help.setObjectName("SubtleHint")
        self.target_help.setWordWrap(True)
        self.axis_lock = QtWidgets.QComboBox()
        self.axis_lock.addItems(["None", "X", "Y", "Z"])
        self.mirror = QtWidgets.QComboBox()
        self.mirror.addItems(["None", "Mirror X", "Mirror Z", "Mirror X+Z"])
        self.host_only = QtWidgets.QCheckBox("Host-rock aware filter (preview)")
        self.host_only.setChecked(True)
        self.protect_surface = QtWidgets.QCheckBox("Protect surface / topsoil")
        self.protect_surface.setChecked(True)
        self.surface_margin = QtWidgets.QSpinBox()
        self.surface_margin.setRange(0, 128)
        self.surface_margin.setValue(6)
        self.surface_margin.setSuffix(" b")
        self.live_overlay = QtWidgets.QCheckBox("Show brush overlay")
        self.live_overlay.setChecked(True)
        self.align_mode = QtWidgets.QComboBox()
        self.align_mode.addItems(["Follow hit normal (auto)", "Lock normal (re-align)", "Manual (no auto align)"])
        self.btn_realign = QtWidgets.QPushButton("Re-align now")
        self.btn_realign.setToolTip("In lock-normal mode, capture the current surface normal again.")
        self.brush_roll = QtWidgets.QSpinBox()
        self.brush_roll.setRange(-180, 180)
        self.brush_roll.setValue(0)
        self.brush_roll.setSuffix("°")
        self.brush_offset = QtWidgets.QDoubleSpinBox()
        self.btn_offset_closer = QtWidgets.QToolButton()
        self.btn_offset_closer.setText("Closer")
        self.btn_offset_closer.setToolTip("Move the 3D brush cursor closer to the camera.")
        self.btn_offset_closer.setAutoRepeat(True)
        self.btn_offset_farther = QtWidgets.QToolButton()
        self.btn_offset_farther.setText("Farther")
        self.btn_offset_farther.setToolTip("Move the 3D brush cursor farther away from the camera.")
        self.btn_offset_farther.setAutoRepeat(True)
        self.brush_offset.setRange(-512.0, 512.0)
        self.brush_offset.setDecimals(1)
        self.brush_offset.setSingleStep(1.0)
        self.brush_offset.setValue(0.0)
        self.brush_offset.setSuffix(" b")

        tg.addWidget(QtWidgets.QLabel("Brush target"), 0, 0)
        tg.addWidget(QtWidgets.QLabel("Solid block under cursor"), 0, 1)
        tg.addWidget(self.target_help, 1, 1, 1, 3)

        tg.addWidget(QtWidgets.QLabel("Axis lock"), 2, 0)
        tg.addWidget(self.axis_lock, 2, 1)
        tg.addWidget(QtWidgets.QLabel("Symmetry"), 2, 2)
        tg.addWidget(self.mirror, 2, 3)

        tg.addWidget(self.host_only, 3, 0, 1, 2)
        tg.addWidget(self.protect_surface, 3, 2)
        tg.addWidget(self.surface_margin, 3, 3)

        tg.addWidget(self.live_overlay, 4, 0, 1, 2)

        offset_tools = QtWidgets.QWidget()
        offset_lay = QtWidgets.QHBoxLayout(offset_tools)
        offset_lay.setContentsMargins(0, 0, 0, 0)
        offset_lay.setSpacing(6)
        offset_lay.addWidget(self.brush_offset, 1)
        offset_lay.addWidget(self.btn_offset_closer)
        offset_lay.addWidget(self.btn_offset_farther)

        tg.addWidget(QtWidgets.QLabel("Brush align"), 5, 0)
        tg.addWidget(self.align_mode, 5, 1)
        tg.addWidget(QtWidgets.QLabel("Brush roll"), 5, 2)
        tg.addWidget(self.brush_roll, 5, 3)

        tg.addWidget(QtWidgets.QLabel("Lock normal"), 6, 0)
        tg.addWidget(self.btn_realign, 6, 1)
        tg.addWidget(QtWidgets.QLabel("Gizmo distance"), 6, 2)
        tg.addWidget(offset_tools, 6, 3)

        tg.addWidget(QtWidgets.QLabel("Quick keys"), 7, 0)
        tg.addWidget(QtWidgets.QLabel("Shift+Wheel or [ / ] = move brush cursor depth  •  Ctrl+Wheel or - / = change size  •  Q/E = roll  •  0 = reset roll  •  \\ = snap back to surface  •  R = re-align"), 7, 1, 1, 3)

        layout.addWidget(target)

        # ----- model import / stamps -----
        stamps = QtWidgets.QGroupBox("Models / stamps (next)")
        sg = QtWidgets.QHBoxLayout(stamps)
        self.btn_import_model = QtWidgets.QPushButton("Import 3D model (OBJ/GLB)")
        self.btn_library = QtWidgets.QPushButton("Stamp library")
        self.btn_import_model.setToolTip("UI stub for upcoming voxelized model stamps.")
        self.btn_library.setToolTip("Future reusable stamp/brush library.")
        sg.addWidget(self.btn_import_model)
        sg.addWidget(self.btn_library)
        layout.addWidget(stamps)

        # ----- live info -----
        info = QtWidgets.QGroupBox("Live paint info")
        ig = QtWidgets.QGridLayout(info)
        self.hover_label = QtWidgets.QLabel("Hover: --")
        self.stroke_label = QtWidgets.QLabel("Last stroke: none")
        self.shortcut_label = QtWidgets.QLabel(
            "Shortcuts: LMB paint | RMB/MMB/Shift+LMB pan | Wheel dolly | Shift+Wheel or [ / ] move brush depth | Ctrl+Wheel or - / = size | Q/E roll | Alt+LMB or Space+LMB orbit | Alt+RMB dolly drag | \\ snap back to surface | R re-align | F focus under cursor"
        )
        self.shortcut_label.setWordWrap(True)
        self.shortcut_label.setObjectName("SubtleHint")
        ig.addWidget(self.hover_label, 0, 0, 1, 2)
        ig.addWidget(self.stroke_label, 1, 0, 1, 2)
        ig.addWidget(self.shortcut_label, 2, 0, 1, 2)
        layout.addWidget(info)
        layout.addStretch(1)

        # sync widgets
        self.size.valueChanged.connect(self.size_spin.setValue)
        self.size_spin.valueChanged.connect(self.size.setValue)
        self.strength.valueChanged.connect(self.strength_spin.setValue)
        self.strength_spin.valueChanged.connect(self.strength.setValue)
        self.spacing.valueChanged.connect(self.spacing_spin.setValue)
        self.spacing_spin.valueChanged.connect(self.spacing.setValue)

        # signals
        for w in [
            self.paint_enabled, self.active_layer, self.action, self.material, self.shape,
            self.size_spin, self.strength_spin, self.spacing_spin, self.falloff,
            self.axis_lock, self.mirror, self.host_only,
            self.protect_surface, self.surface_margin, self.live_overlay, self.align_mode, self.brush_roll, self.brush_offset
        ]:
            if isinstance(w, QtWidgets.QAbstractButton):
                w.toggled.connect(self.emit_paint_settings)
            elif isinstance(w, QtWidgets.QComboBox):
                if w.isEditable():
                    w.lineEdit().editingFinished.connect(self.emit_paint_settings)
                w.currentTextChanged.connect(lambda *_: self.emit_paint_settings())
            else:
                w.valueChanged.connect(lambda *_: self.emit_paint_settings())

        self.btn_add_layer.clicked.connect(self._on_add_layer)
        self.btn_focus.clicked.connect(self.focus_paint_requested)
        self.btn_import_model.clicked.connect(self.import_model_requested)
        self.btn_library.clicked.connect(lambda: QtWidgets.QToolTip.showText(self.mapToGlobal(self.rect().center()), "Stamp library is a future milestone.", self))
        self.btn_realign.clicked.connect(self.realign_requested.emit)
        self.btn_offset_closer.clicked.connect(lambda: self._nudge_brush_offset(+1.0))
        self.btn_offset_farther.clicked.connect(lambda: self._nudge_brush_offset(-1.0))

        # enable/disable follow-on controls
        self.action.currentTextChanged.connect(self._refresh_ui)
        self.protect_surface.toggled.connect(self._refresh_ui)
        self.paint_enabled.toggled.connect(self._refresh_ui)
        self.align_mode.currentTextChanged.connect(self._refresh_ui)
        self._refresh_ui()

    def settings(self) -> dict:
        return {
            "enabled": bool(self.paint_enabled.isChecked()),
            "active_layer": self.active_layer.currentText().strip() or "Paint Layer",
            "action": self.action.currentText(),
            "material": self.material.currentText().strip() or "minecraft:stone",
            "shape": self.shape.currentText(),
            "size_blocks": int(self.size_spin.value()),
            "strength_pct": int(self.strength_spin.value()),
            "spacing_pct_radius": int(self.spacing_spin.value()),
            "falloff": self.falloff.currentText(),
            "target_mode": "volume",
            "axis_lock": self.axis_lock.currentText(),
            "mirror": self.mirror.currentText(),
            "host_only": bool(self.host_only.isChecked()),
            "protect_surface": bool(self.protect_surface.isChecked()),
            "surface_margin": int(self.surface_margin.value()),
            "show_overlay": bool(self.live_overlay.isChecked()),
            "align_mode": self.align_mode.currentText(),
            "brush_roll_deg": int(self.brush_roll.value()),
            "brush_offset_blocks": float(self.brush_offset.value()),
        }

    @QtCore.Slot()
    def emit_paint_settings(self) -> None:
        self.paint_settings_changed.emit(self.settings())

    @QtCore.Slot()
    def _on_add_layer(self) -> None:
        name = (self.active_layer.currentText() or "").strip()
        if not name:
            name = "Paint Layer"
            self.active_layer.setEditText(name)
        # keep combo list fresh near top
        if self.active_layer.findText(name) < 0:
            self.active_layer.insertItem(0, name)
            self.active_layer.setCurrentIndex(0)
        self.add_layer_requested.emit(name)
        self.emit_paint_settings()

    def _nudge_brush_offset(self, delta: float) -> None:
        try:
            cur = float(self.brush_offset.value())
        except Exception:
            cur = 0.0
        self.brush_offset.setValue(max(self.brush_offset.minimum(), min(self.brush_offset.maximum(), cur + float(delta))))

    @QtCore.Slot()
    def _refresh_ui(self) -> None:
        act = self.action.currentText().lower()
        needs_material = ("carve" not in act)
        self.material.setEnabled(needs_material)
        self.surface_margin.setEnabled(self.protect_surface.isChecked())
        self.host_only.setEnabled(("ore" in act) or ("replace" in act))
        lock_mode = self.align_mode.currentText().lower().startswith("lock")
        self.btn_realign.setEnabled(lock_mode and self.paint_enabled.isChecked())
        self.target_help.setText("Brush cursor is automatic: it snaps to solid blocks under the cursor when available, and otherwise stays at the current 3D brush depth so you can paint anywhere inside the selected area.")
        if "stamp" in act:
            self.btn_import_model.setDefault(True)
        else:
            self.btn_import_model.setDefault(False)


    def select_or_create_layer(self, name: str, select_only: bool = False) -> None:
        name = (name or "Paint Layer").strip() or "Paint Layer"
        idx = self.active_layer.findText(name)
        if idx < 0:
            self.active_layer.insertItem(0, name)
            idx = self.active_layer.findText(name)
        if idx >= 0:
            self.active_layer.setCurrentIndex(idx)
        else:
            self.active_layer.setEditText(name)
        if not select_only:
            self.emit_paint_settings()

    def rename_layer_entry(self, old_name: str, new_name: str) -> None:
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip() or "Paint Layer"
        if not old_name:
            self.select_or_create_layer(new_name, select_only=False)
            return
        idx = self.active_layer.findText(old_name)
        if idx >= 0:
            self.active_layer.setItemText(idx, new_name)
            self.active_layer.setCurrentIndex(idx)
        elif self.active_layer.currentText().strip() == old_name:
            self.active_layer.setEditText(new_name)
        else:
            self.select_or_create_layer(new_name, select_only=False)
            return
        self.emit_paint_settings()

    def apply_settings(self, settings: dict, *, emit: bool = True) -> None:
        data = dict(settings or {})

        def _set_combo(combo: QtWidgets.QComboBox, value: object) -> None:
            text = str(value or "").strip()
            if combo.isEditable() and combo.findText(text) < 0 and text:
                combo.insertItem(0, text)
            idx = combo.findText(text)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            elif combo.isEditable():
                combo.setEditText(text)

        widgets = [
            self.paint_enabled, self.active_layer, self.action, self.material, self.shape,
            self.size_spin, self.strength_spin, self.spacing_spin, self.falloff,
            self.axis_lock, self.mirror, self.host_only,
            self.protect_surface, self.surface_margin, self.live_overlay,
            self.align_mode, self.brush_roll, self.brush_offset,
        ]
        for w in widgets:
            w.blockSignals(True)
        try:
            self.paint_enabled.setChecked(bool(data.get("enabled", self.paint_enabled.isChecked())))
            _set_combo(self.active_layer, data.get("active_layer", self.active_layer.currentText()))
            _set_combo(self.action, data.get("action", self.action.currentText()))
            _set_combo(self.material, data.get("material", self.material.currentText()))
            _set_combo(self.shape, data.get("shape", self.shape.currentText()))
            self.size_spin.setValue(max(self.size_spin.minimum(), min(self.size_spin.maximum(), int(data.get("size_blocks", self.size_spin.value())))))
            self.size.setValue(self.size_spin.value())
            self.strength_spin.setValue(max(self.strength_spin.minimum(), min(self.strength_spin.maximum(), int(data.get("strength_pct", self.strength_spin.value())))))
            self.strength.setValue(self.strength_spin.value())
            self.spacing_spin.setValue(max(self.spacing_spin.minimum(), min(self.spacing_spin.maximum(), int(data.get("spacing_pct_radius", self.spacing_spin.value())))))
            self.spacing.setValue(self.spacing_spin.value())
            _set_combo(self.falloff, data.get("falloff", self.falloff.currentText()))
            _set_combo(self.axis_lock, data.get("axis_lock", self.axis_lock.currentText()))
            _set_combo(self.mirror, data.get("mirror", self.mirror.currentText()))
            self.host_only.setChecked(bool(data.get("host_only", self.host_only.isChecked())))
            self.protect_surface.setChecked(bool(data.get("protect_surface", self.protect_surface.isChecked())))
            self.surface_margin.setValue(max(self.surface_margin.minimum(), min(self.surface_margin.maximum(), int(data.get("surface_margin", self.surface_margin.value())))))
            self.live_overlay.setChecked(bool(data.get("show_overlay", self.live_overlay.isChecked())))
            _set_combo(self.align_mode, data.get("align_mode", self.align_mode.currentText()))
            self.brush_roll.setValue(max(self.brush_roll.minimum(), min(self.brush_roll.maximum(), int(round(float(data.get("brush_roll_deg", self.brush_roll.value())))))))
            self.brush_offset.setValue(max(self.brush_offset.minimum(), min(self.brush_offset.maximum(), float(data.get("brush_offset_blocks", self.brush_offset.value())))))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._refresh_ui()
        if emit:
            self.emit_paint_settings()

    def set_hover_info(self, info: dict | None) -> None:
        if not info or not info.get("valid"):
            self.hover_label.setText("Hover: --")
            return
        x = info.get("x"); y = info.get("y"); z = info.get("z")
        mode = "Solid block under cursor"
        resolved = info.get("resolved_pick")
        if resolved and str(resolved) == "free":
            mode = "3D brush depth"
        elif resolved and str(resolved) == "surface":
            mode = "Surface hit"
        bsz = info.get("brush_size")
        roll = info.get("brush_roll_deg")
        offset = info.get("brush_offset_blocks")
        align_mode = info.get("align_mode")
        if bsz is not None:
            try:
                bsv = int(bsz)
                if self.size_spin.value() != bsv:
                    self.size_spin.blockSignals(True); self.size.blockSignals(True)
                    self.size_spin.setValue(max(self.size_spin.minimum(), min(self.size_spin.maximum(), bsv)))
                    self.size.setValue(self.size_spin.value())
                    self.size.blockSignals(False); self.size_spin.blockSignals(False)
            except Exception:
                pass
        try:
            if roll is not None and self.brush_roll.value() != int(round(float(roll))):
                self.brush_roll.blockSignals(True)
                self.brush_roll.setValue(max(self.brush_roll.minimum(), min(self.brush_roll.maximum(), int(round(float(roll))))))
                self.brush_roll.blockSignals(False)
        except Exception:
            pass
        try:
            if offset is not None and abs(self.brush_offset.value() - float(offset)) > 1e-6:
                self.brush_offset.blockSignals(True)
                self.brush_offset.setValue(max(self.brush_offset.minimum(), min(self.brush_offset.maximum(), float(offset))))
                self.brush_offset.blockSignals(False)
        except Exception:
            pass
        extra = []
        if bsz is not None:
            extra.append(f"brush={int(bsz)}b")
        if offset is not None:
            extra.append(f"gizmo={float(offset):.1f}b")
        if roll is not None:
            extra.append(f"roll={int(round(float(roll)))}°")
        am = str(align_mode or "manual").lower()
        if am.startswith("follow") or am.startswith("auto"):
            extra.append("align=follow")
        elif am.startswith("lock"):
            extra.append("align=lock")
        else:
            extra.append("align=manual")
        suffix = ("  " + "  ".join(extra)) if extra else ""
        self.hover_label.setText(f"Hover: ({x}, {y}, {z})  [{mode}]" + suffix)

    def set_stroke_info(self, info: dict | None) -> None:
        if not info:
            self.stroke_label.setText("Last stroke: none")
            return
        n = int(info.get("point_count", 0))
        layer = str(info.get("active_layer", "Paint Layer"))
        bbox = info.get("bbox")
        if bbox and len(bbox) == 6:
            self.stroke_label.setText(
                f"Last stroke: {n} samples on '{layer}'  bbox=({bbox[0]},{bbox[1]},{bbox[2]})→({bbox[3]},{bbox[4]},{bbox[5]})"
            )
        else:
            self.stroke_label.setText(f"Last stroke: {n} samples on '{layer}'")
