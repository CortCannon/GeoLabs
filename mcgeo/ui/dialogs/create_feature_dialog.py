from __future__ import annotations

from PySide6 import QtWidgets, QtCore


class CreateFeatureDialog(QtWidgets.QDialog):
    """Simple user-facing feature picker that opens the correct editor after creation."""
    def __init__(self, parent: QtWidgets.QWidget | None = None, *, show_dev: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Feature")
        self.setModal(True)
        self.resize(520, 380)
        self._show_dev = bool(show_dev)
        self._selected_kind = "paint"

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QtWidgets.QLabel("Create Feature")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        hint = QtWidgets.QLabel(
            "Choose what you want to add. The new feature/layer will be created and the right panel will open directly to its editor."
        )
        hint.setWordWrap(True)
        hint.setObjectName("SubtleHint")
        layout.addWidget(hint)

        self.list = QtWidgets.QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.list, 1)

        self.desc = QtWidgets.QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setObjectName("SubtleHint")
        self.desc.setMinimumHeight(56)
        layout.addWidget(self.desc)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_create = QtWidgets.QPushButton("Create")
        self.btn_create.setObjectName("PrimaryButton")
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_create)
        layout.addLayout(row)

        self._populate()

        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_create.clicked.connect(self.accept)

        if self.list.count():
            self.list.setCurrentRow(0)

    def _populate(self) -> None:
        entries = [
            ("paint", "Paint Layer", "3D painter layer for manual ore/cave/rock touch-up work. Best for artist-style control."),
            ("caves", "Cave Generator Preview", "Non-destructive cave preview layer. Tune shape and density in the layer editor."),
            ("ores", "Ore Generator Preview", "Non-destructive ore placement preview layer. Good for quickly testing distribution."),
            ("caves+ores", "Cave + Ore Preset", "Creates a subtle combined generator preview setup for quick world look-dev."),
        ]
        if self._show_dev:
            entries.append(("box", "Box Replace (Advanced / Dev)", "Internal editing-core test layer (box replace)."))
        for kind, title, desc in entries:
            it = QtWidgets.QListWidgetItem(title)
            it.setData(QtCore.Qt.ItemDataRole.UserRole, kind)
            it.setData(QtCore.Qt.ItemDataRole.UserRole + 1, desc)
            self.list.addItem(it)

    def _on_current_changed(self, cur, _prev) -> None:
        if cur is None:
            self._selected_kind = "paint"
            self.desc.setText("")
            return
        self._selected_kind = str(cur.data(QtCore.Qt.ItemDataRole.UserRole) or "paint")
        self.desc.setText(str(cur.data(QtCore.Qt.ItemDataRole.UserRole + 1) or ""))

    def selected_kind(self) -> str:
        return self._selected_kind

    @classmethod
    def get_feature_kind(cls, parent: QtWidgets.QWidget | None = None, *, show_dev: bool = False) -> str | None:
        dlg = cls(parent, show_dev=show_dev)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dlg.selected_kind()
