from __future__ import annotations
from PySide6 import QtCore, QtWidgets

class EditCorePanel(QtWidgets.QWidget):
    preview_requested = QtCore.Signal()
    apply_demo_requested = QtCore.Signal()
    add_box_layer_requested = QtCore.Signal()

    box_params_changed = QtCore.Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._wire()
        self._emit_params()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = QtWidgets.QLabel("Editing Core v1")
        header.setObjectName("SectionTitle")
        root.addWidget(header)

        desc = QtWidgets.QLabel(
            "Non-destructive layer evaluation scaffold. "
            "Use this panel to add/test a Box Replace layer while keeping the existing 3D renderer."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_add_box = QtWidgets.QPushButton("Add Box Replace")
        self.btn_preview = QtWidgets.QPushButton("Preview")
        self.btn_apply_demo = QtWidgets.QPushButton("Apply (demo)")
        btn_row.addWidget(self.btn_add_box)
        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_apply_demo)
        root.addLayout(btn_row)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.name_edit = QtWidgets.QLineEdit("Box Replace A")
        self.enabled_chk = QtWidgets.QCheckBox()
        self.enabled_chk.setChecked(True)
        self.combine_mode = QtWidgets.QComboBox()
        self.combine_mode.addItems(["replace", "subtract"])
        self.target_block = QtWidgets.QLineEdit("minecraft:iron_ore")
        self.repl_blocks = QtWidgets.QLineEdit("minecraft:stone,minecraft:deepslate")

        self.min_x = QtWidgets.QSpinBox(); self.max_x = QtWidgets.QSpinBox()
        self.min_y = QtWidgets.QSpinBox(); self.max_y = QtWidgets.QSpinBox()
        self.min_z = QtWidgets.QSpinBox(); self.max_z = QtWidgets.QSpinBox()
        for sb in (self.min_x, self.max_x, self.min_y, self.max_y, self.min_z, self.max_z):
            sb.setRange(-1000000, 1000000)
        self.min_x.setValue(0); self.max_x.setValue(15)
        self.min_y.setValue(0); self.max_y.setValue(31)
        self.min_z.setValue(0); self.max_z.setValue(15)

        x_row = QtWidgets.QHBoxLayout(); x_row.addWidget(self.min_x); x_row.addWidget(QtWidgets.QLabel("to")); x_row.addWidget(self.max_x)
        y_row = QtWidgets.QHBoxLayout(); y_row.addWidget(self.min_y); y_row.addWidget(QtWidgets.QLabel("to")); y_row.addWidget(self.max_y)
        z_row = QtWidgets.QHBoxLayout(); z_row.addWidget(self.min_z); z_row.addWidget(QtWidgets.QLabel("to")); z_row.addWidget(self.max_z)

        x_w = QtWidgets.QWidget(); x_w.setLayout(x_row)
        y_w = QtWidgets.QWidget(); y_w.setLayout(y_row)
        z_w = QtWidgets.QWidget(); z_w.setLayout(z_row)

        form.addRow("Layer name", self.name_edit)
        form.addRow("Enabled", self.enabled_chk)
        form.addRow("Combine", self.combine_mode)
        form.addRow("Target block", self.target_block)
        form.addRow("Replace blocks", self.repl_blocks)
        form.addRow("X range", x_w)
        form.addRow("Y range", y_w)
        form.addRow("Z range", z_w)

        root.addLayout(form)

        self.stats = QtWidgets.QPlainTextEdit()
        self.stats.setReadOnly(True)
        self.stats.setPlaceholderText("Preview/apply stats will appear here.")
        self.stats.setMaximumBlockCount(500)
        root.addWidget(self.stats, 1)

    def _wire(self) -> None:
        self.btn_add_box.clicked.connect(self.add_box_layer_requested)
        self.btn_preview.clicked.connect(self.preview_requested)
        self.btn_apply_demo.clicked.connect(self.apply_demo_requested)

        widgets = [
            self.name_edit, self.enabled_chk, self.combine_mode,
            self.target_block, self.repl_blocks,
            self.min_x, self.max_x, self.min_y, self.max_y, self.min_z, self.max_z,
        ]
        for w in widgets:
            sig = getattr(w, "editingFinished", None)
            if sig is not None:
                sig.connect(self._emit_params)
            sig = getattr(w, "valueChanged", None)
            if sig is not None:
                sig.connect(lambda *_: self._emit_params())
            sig = getattr(w, "toggled", None)
            if sig is not None:
                sig.connect(lambda *_: self._emit_params())
            sig = getattr(w, "currentTextChanged", None)
            if sig is not None:
                sig.connect(lambda *_: self._emit_params())

    def params(self) -> dict:
        replace_whitelist = tuple(
            s.strip() for s in self.repl_blocks.text().split(",") if s.strip()
        )
        return {
            "name": self.name_edit.text().strip() or "Box Replace",
            "enabled": self.enabled_chk.isChecked(),
            "combine_mode": self.combine_mode.currentText().strip().lower(),
            "target_block": self.target_block.text().strip() or "minecraft:iron_ore",
            "replace_whitelist": replace_whitelist,
            "min_x": int(self.min_x.value()),
            "max_x": int(self.max_x.value()),
            "min_y": int(self.min_y.value()),
            "max_y": int(self.max_y.value()),
            "min_z": int(self.min_z.value()),
            "max_z": int(self.max_z.value()),
        }

    @QtCore.Slot()
    def _emit_params(self) -> None:
        self.box_params_changed.emit(self.params())

    def append_stats(self, line: str) -> None:
        self.stats.appendPlainText(line)

    def set_stats(self, text: str) -> None:
        self.stats.setPlainText(text)
