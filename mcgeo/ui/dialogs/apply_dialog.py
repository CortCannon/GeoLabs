from __future__ import annotations
from pathlib import Path
from PySide6 import QtWidgets, QtCore


class ApplyDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, summary: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apply Changes")
        self.setModal(True)
        self.resize(620, 520)
        self._summary = dict(summary or {})

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Apply review")
        title.setObjectName("PanelTitle")
        subtitle = QtWidgets.QLabel(
            "Review what will be written before the safe-apply pipeline is finished. "
            "This dialog does not write blocks yet; it prepares the destination and seed options."
        )
        subtitle.setObjectName("SubtleHint")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        summary_box = QtWidgets.QGroupBox("Session summary")
        form = QtWidgets.QFormLayout(summary_box)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.lbl_world = QtWidgets.QLabel(str(self._summary.get("world_name") or "No world loaded"))
        self.lbl_area = QtWidgets.QLabel(str(self._summary.get("area_label") or "Area not selected"))
        self.lbl_layers = QtWidgets.QLabel(str(self._summary.get("layer_summary") or "No layers"))
        self.lbl_preview = QtWidgets.QLabel(str(self._summary.get("preview_summary") or "No preview layers active"))
        self.lbl_notes = QtWidgets.QLabel(str(self._summary.get("notes") or ""))
        self.lbl_notes.setWordWrap(True)
        form.addRow("World", self.lbl_world)
        form.addRow("Edit area", self.lbl_area)
        form.addRow("Layers", self.lbl_layers)
        form.addRow("Preview", self.lbl_preview)
        form.addRow("Notes", self.lbl_notes)
        layout.addWidget(summary_box)

        dest_box = QtWidgets.QGroupBox("Destination")
        dlay = QtWidgets.QVBoxLayout(dest_box)
        self.apply_copy = QtWidgets.QRadioButton("Apply to timestamped copy (recommended)")
        self.apply_copy.setChecked(True)
        self.apply_inplace = QtWidgets.QRadioButton("Apply in-place (advanced)")
        dlay.addWidget(self.apply_copy)
        dlay.addWidget(self.apply_inplace)
        self.dest_hint = QtWidgets.QLabel("")
        self.dest_hint.setObjectName("SubtleHint")
        self.dest_hint.setWordWrap(True)
        dlay.addWidget(self.dest_hint)
        layout.addWidget(dest_box)

        options_box = QtWidgets.QGroupBox("Options")
        opt = QtWidgets.QFormLayout(options_box)
        self.use_seed = QtWidgets.QCheckBox("Enable randomness (seeded)")
        self.seed = QtWidgets.QLineEdit()
        self.seed.setPlaceholderText("Seed (integer)")
        self.seed.setEnabled(False)
        self.use_seed.toggled.connect(self.seed.setEnabled)
        opt.addRow(self.use_seed)
        opt.addRow("Seed", self.seed)
        layout.addWidget(options_box)

        self.review = QtWidgets.QPlainTextEdit()
        self.review.setReadOnly(True)
        self.review.setMaximumBlockCount(400)
        self.review.setPlainText(self._build_review_text())
        layout.addWidget(self.review, 1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Close")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.apply_copy.toggled.connect(self._refresh_destination_hint)
        self.apply_inplace.toggled.connect(self._refresh_destination_hint)
        self._refresh_destination_hint()

    def _build_review_text(self) -> str:
        lines = [
            "Apply pipeline status: review-only milestone.",
            "",
            f"World: {self._summary.get('world_path') or '—'}",
            f"Project: {self._summary.get('project_path') or 'Unsaved session'}",
            f"Area: {self._summary.get('area_label') or 'Not selected'}",
            f"Layer stack: {self._summary.get('layer_summary') or 'No layers'}",
            f"Preview: {self._summary.get('preview_summary') or 'No preview layers active'}",
        ]
        warnings = list(self._summary.get('warnings') or [])
        if warnings:
            lines.extend(["", "Warnings:"])
            lines.extend([f"- {w}" for w in warnings])
        lines.extend([
            "",
            "Next milestone:",
            "- write preview deltas to a world copy with journaling / rollback",
            "- verify changed chunk counts before commit",
            "- surface changed destination path before writing",
        ])
        return "\n".join(lines)

    def _refresh_destination_hint(self) -> None:
        world_path = self._summary.get("world_path")
        if not world_path:
            self.dest_hint.setText("Open a world to prepare a destination.")
            return
        world_path = Path(str(world_path))
        if self.apply_copy.isChecked():
            self.dest_hint.setText(
                f"Recommended destination: {world_path.parent / (world_path.name + '_wgl_apply_TIMESTAMP')}"
            )
        else:
            self.dest_hint.setText("Advanced mode would modify the selected world in place once safe apply is implemented.")
