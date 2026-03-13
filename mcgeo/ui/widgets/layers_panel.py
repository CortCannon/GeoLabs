from __future__ import annotations
from PySide6 import QtWidgets, QtCore, QtGui


class LayersPanel(QtWidgets.QWidget):
    create_feature_requested = QtCore.Signal()
    quick_feature_requested = QtCore.Signal(str)

    # object payloads are dict metadata for the selected layer item
    layer_selected = QtCore.Signal(object)
    layer_edit_requested = QtCore.Signal(object)
    layer_remove_requested = QtCore.Signal(object)
    layer_duplicate_requested = QtCore.Signal(object)
    layer_renamed = QtCore.Signal(object, str)
    layer_visibility_changed = QtCore.Signal(object, bool)
    layer_reordered = QtCore.Signal()

    ROLE_META = int(QtCore.Qt.ItemDataRole.UserRole)

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Features / Layers")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "GIMP-style workflow: select one layer to work on, then use the right panel to edit it."
        )
        subtitle.setObjectName("SubtleHint")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Primary entry point (user-friendly)
        self.btn_create_feature = QtWidgets.QPushButton("Create Feature…")
        self.btn_create_feature.setMinimumHeight(34)
        self.btn_create_feature.setObjectName("PrimaryButton")
        layout.addWidget(self.btn_create_feature)

        quick_row = QtWidgets.QHBoxLayout()
        self.btn_quick_paint = QtWidgets.QPushButton("Paint")
        self.btn_quick_caves = QtWidgets.QPushButton("Caves")
        self.btn_quick_ores = QtWidgets.QPushButton("Ores")
        for b in (self.btn_quick_paint, self.btn_quick_caves, self.btn_quick_ores):
            b.setToolTip("Create and preview this feature type")
            quick_row.addWidget(b)
        layout.addLayout(quick_row)

        self.empty_state = QtWidgets.QLabel(
            "No edits yet. Create a feature to start a non-destructive layer stack."
        )
        self.empty_state.setWordWrap(True)
        self.empty_state.setObjectName("SubtleHint")
        layout.addWidget(self.empty_state)

        self.list = QtWidgets.QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.list, 1)

        self.active_hint = QtWidgets.QLabel("Active layer: none")
        self.active_hint.setObjectName("SubtleHint")
        self.active_hint.setWordWrap(True)
        layout.addWidget(self.active_hint)

        btns = QtWidgets.QGridLayout()
        self.btn_add = QtWidgets.QPushButton("Create")
        self.btn_remove = QtWidgets.QPushButton("Delete")
        self.btn_move_up = QtWidgets.QPushButton("Move up")
        self.btn_move_down = QtWidgets.QPushButton("Move down")
        self.btn_edit = QtWidgets.QPushButton("Edit Selected")
        self.btn_duplicate = QtWidgets.QPushButton("Duplicate")
        btns.addWidget(self.btn_add, 0, 0)
        btns.addWidget(self.btn_edit, 0, 1)
        btns.addWidget(self.btn_remove, 1, 0)
        btns.addWidget(self.btn_duplicate, 1, 1)
        btns.addWidget(self.btn_move_up, 2, 0)
        btns.addWidget(self.btn_move_down, 2, 1)
        layout.addLayout(btns)

        self.note = QtWidgets.QLabel(
            "Tip: Uncheck a layer to hide its preview. Double-click a layer to rename it."
        )
        self.note.setObjectName("SubtleHint")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        # Wiring
        self.btn_create_feature.clicked.connect(self.create_feature_requested.emit)
        self.btn_quick_paint.clicked.connect(lambda: self.quick_feature_requested.emit("paint"))
        self.btn_quick_caves.clicked.connect(lambda: self.quick_feature_requested.emit("caves"))
        self.btn_quick_ores.clicked.connect(lambda: self.quick_feature_requested.emit("ores"))

        self.btn_add.clicked.connect(self.create_feature_requested.emit)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_edit.clicked.connect(self._edit_selected)
        self.btn_duplicate.clicked.connect(self._duplicate_selected)
        self.btn_move_up.clicked.connect(lambda: self._move_selected(-1))
        self.btn_move_down.clicked.connect(lambda: self._move_selected(+1))

        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemDoubleClicked.connect(lambda _it: self._edit_selected())
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        self.list.model().rowsMoved.connect(lambda *_: self.layer_reordered.emit())

        self._rename_guard = False
        self._check_guard = False
        self._last_labels_by_key: dict[str, str] = {}

        self.refresh_empty_state()
        self._refresh_buttons()

    # ---------- internal helpers ----------
    def _item_meta(self, item: QtWidgets.QListWidgetItem | None) -> dict:
        if item is None:
            return {}
        raw = item.data(self.ROLE_META)
        if isinstance(raw, dict):
            d = dict(raw)
        else:
            d = {}
        d.setdefault("label", item.text())
        d.setdefault("kind", "generic")
        d.setdefault("key", item.text())
        d.setdefault("checked", item.checkState() == QtCore.Qt.CheckState.Checked)
        return d

    def _set_item_meta(self, item: QtWidgets.QListWidgetItem, meta: dict) -> None:
        item.setData(self.ROLE_META, dict(meta or {}))

    def _selected_item(self) -> QtWidgets.QListWidgetItem | None:
        row = self.list.currentRow()
        return self.list.item(row) if row >= 0 else None

    def _selected_meta(self) -> dict:
        return self._item_meta(self._selected_item())

    def _make_check_item(self, label: str, checked: bool = True, meta: dict | None = None) -> QtWidgets.QListWidgetItem:
        it = QtWidgets.QListWidgetItem(label)
        flags = it.flags()
        flags |= QtCore.Qt.ItemFlag.ItemIsUserCheckable
        flags |= QtCore.Qt.ItemFlag.ItemIsEnabled
        flags |= QtCore.Qt.ItemFlag.ItemIsSelectable
        flags |= QtCore.Qt.ItemFlag.ItemIsDragEnabled
        flags |= QtCore.Qt.ItemFlag.ItemIsEditable
        it.setFlags(flags)
        self._check_guard = True
        try:
            it.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
        finally:
            self._check_guard = False
        self._set_item_meta(it, meta or {"kind": "generic", "key": label, "label": label})
        return it

    def _find_item_by_key(self, key: str) -> QtWidgets.QListWidgetItem | None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            meta = self._item_meta(it)
            if str(meta.get("key")) == str(key):
                return it
        return None

    def _select_item(self, item: QtWidgets.QListWidgetItem | None) -> None:
        if item is None:
            return
        row = self.list.row(item)
        if row >= 0:
            self.list.setCurrentRow(row)
            self.list.scrollToItem(item)

    def _refresh_buttons(self) -> None:
        has_sel = self._selected_item() is not None
        self.btn_edit.setEnabled(has_sel)
        self.btn_remove.setEnabled(has_sel)
        self.btn_duplicate.setEnabled(has_sel)
        self.btn_move_up.setEnabled(has_sel and self.list.currentRow() > 0)
        self.btn_move_down.setEnabled(has_sel and self.list.currentRow() < self.list.count() - 1)

    def _emit_selected(self) -> None:
        meta = self._selected_meta()
        if meta:
            self.layer_selected.emit(meta)

    # ---------- UI callbacks ----------
    @QtCore.Slot()
    def _on_selection_changed(self) -> None:
        meta = self._selected_meta()
        if not meta:
            self.active_hint.setText("Active layer: none")
        else:
            kind = str(meta.get("kind", "layer")).replace("_", " ").title()
            self.active_hint.setText(f"Active layer: {meta.get('label', '--')}  ({kind})")
        self._refresh_buttons()
        self.layer_selected.emit(meta)

    @QtCore.Slot(QtWidgets.QListWidgetItem)
    def _on_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        if item is None:
            return
        meta = self._item_meta(item)
        key = str(meta.get("key", item.text()))

        prev_label = self._last_labels_by_key.get(key)
        current_label = item.text().strip() or str(meta.get("label") or "Layer")
        if prev_label is None:
            self._last_labels_by_key[key] = current_label

        # Rename detection
        if prev_label is not None and current_label != prev_label and not self._rename_guard:
            meta["label"] = current_label
            self._set_item_meta(item, meta)
            self._last_labels_by_key[key] = current_label
            self.layer_renamed.emit(meta, current_label)
        else:
            meta["label"] = current_label
            self._set_item_meta(item, meta)
            self._last_labels_by_key[key] = current_label

        # Visibility toggle detection
        checked = item.checkState() == QtCore.Qt.CheckState.Checked
        if bool(meta.get("checked", checked)) != checked and not self._check_guard:
            meta["checked"] = checked
            self._set_item_meta(item, meta)
            self.layer_visibility_changed.emit(meta, checked)
        else:
            meta["checked"] = checked
            self._set_item_meta(item, meta)

        self.refresh_empty_state()
        self._refresh_buttons()

    @QtCore.Slot(QtCore.QPoint)
    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        item = self.list.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        if item is None:
            menu.addAction("Create Feature…", self.create_feature_requested.emit)
            menu.exec(self.list.mapToGlobal(pos))
            return

        self._select_item(item)
        meta = self._item_meta(item)
        a_edit = menu.addAction("Edit / Focus")
        a_rename = menu.addAction("Rename")
        a_dup = menu.addAction("Duplicate")
        a_del = menu.addAction("Delete")
        menu.addSeparator()
        a_up = menu.addAction("Move Up")
        a_dn = menu.addAction("Move Down")
        menu.addSeparator()
        a_toggle = menu.addAction("Hide Preview" if item.checkState() == QtCore.Qt.CheckState.Checked else "Show Preview")

        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == a_edit:
            self.layer_edit_requested.emit(meta)
        elif chosen == a_rename:
            self.list.editItem(item)
        elif chosen == a_dup:
            self.layer_duplicate_requested.emit(meta)
        elif chosen == a_del:
            self.layer_remove_requested.emit(meta)
            row = self.list.row(item)
            if row >= 0:
                self.list.takeItem(row)
            self.refresh_empty_state()
            self._refresh_buttons()
        elif chosen == a_up:
            self._move_selected(-1)
        elif chosen == a_dn:
            self._move_selected(+1)
        elif chosen == a_toggle:
            self._check_guard = True
            try:
                item.setCheckState(
                    QtCore.Qt.CheckState.Unchecked
                    if item.checkState() == QtCore.Qt.CheckState.Checked
                    else QtCore.Qt.CheckState.Checked
                )
            finally:
                self._check_guard = False
            self._on_item_changed(item)

    @QtCore.Slot()
    def _edit_selected(self) -> None:
        meta = self._selected_meta()
        if meta:
            self.layer_edit_requested.emit(meta)

    @QtCore.Slot()
    def _duplicate_selected(self) -> None:
        meta = self._selected_meta()
        if meta:
            self.layer_duplicate_requested.emit(meta)

    @QtCore.Slot()
    def _remove_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        meta = self._item_meta(item)
        self.layer_remove_requested.emit(meta)
        row = self.list.row(item)
        if row >= 0:
            self.list.takeItem(row)
        self.refresh_empty_state()
        self._refresh_buttons()

    def _move_selected(self, delta: int) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        new_row = row + int(delta)
        if new_row < 0 or new_row >= self.list.count():
            return
        it = self.list.takeItem(row)
        self.list.insertItem(new_row, it)
        self.list.setCurrentRow(new_row)
        self.layer_reordered.emit()
        self._refresh_buttons()

    # ---------- public runtime helpers ----------
    def refresh_empty_state(self) -> None:
        has_items = self.list.count() > 0
        self.empty_state.setVisible(not has_items)
        self.list.setVisible(True)
        if not has_items:
            self.active_hint.setText("Active layer: none")

    def clear_runtime_layers(self) -> None:
        self.list.clear()
        self._last_labels_by_key.clear()
        self.refresh_empty_state()
        self._refresh_buttons()

    def ensure_named_layer(
        self,
        label: str,
        checked: bool = True,
        top: bool = True,
        meta: dict | None = None,
        select: bool = False,
    ) -> None:
        label = str(label).strip()
        if not label:
            return
        meta = dict(meta or {})
        key = str(meta.get("key") or label)
        existing = self._find_item_by_key(key)
        if existing is not None:
            if existing.text() != label:
                self._rename_guard = True
                try:
                    existing.setText(label)
                finally:
                    self._rename_guard = False
            self._check_guard = True
            try:
                existing.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
            finally:
                self._check_guard = False
            meta.setdefault("label", label)
            meta["checked"] = checked
            self._set_item_meta(existing, meta)
            self._last_labels_by_key[key] = label
            if select:
                self._select_item(existing)
            self.refresh_empty_state()
            self._refresh_buttons()
            return

        meta.setdefault("key", key)
        meta.setdefault("label", label)
        meta["checked"] = checked
        it = self._make_check_item(label, checked=checked, meta=meta)
        if top:
            self.list.insertItem(0, it)
        else:
            self.list.addItem(it)
        self._last_labels_by_key[key] = label
        if select:
            self._select_item(it)
        self.refresh_empty_state()
        self._refresh_buttons()

    def remove_layers_with_prefix(self, prefix: str) -> None:
        prefix = str(prefix)
        for i in range(self.list.count() - 1, -1, -1):
            if self.list.item(i).text().startswith(prefix):
                item = self.list.takeItem(i)
                if item is not None:
                    meta = self._item_meta(item)
                    self._last_labels_by_key.pop(str(meta.get("key", item.text())), None)
        self.refresh_empty_state()
        self._refresh_buttons()

    def remove_layer_by_key(self, key: str) -> None:
        it = self._find_item_by_key(key)
        if it is None:
            return
        row = self.list.row(it)
        self.list.takeItem(row)
        self._last_labels_by_key.pop(str(key), None)
        self.refresh_empty_state()
        self._refresh_buttons()

    def upsert_paint_layer(self, layer_name: str, stroke_count: int | None = None, select: bool = False, checked: bool | None = None) -> None:
        clean = layer_name.strip() or "Paint Layer"
        label = f"Paint • {clean}"
        if stroke_count is not None:
            label += f"  ({int(stroke_count)} stroke{'s' if int(stroke_count)!=1 else ''})"
        if checked is None:
            existing = self._find_item_by_key(f"paint:{clean}")
            if existing is not None:
                checked = existing.checkState() == QtCore.Qt.CheckState.Checked
            else:
                checked = True
        self.ensure_named_layer(
            label,
            checked=bool(checked),
            top=True,
            select=select,
            meta={"kind": "paint", "key": f"paint:{clean}", "name": clean},
        )

    def set_generator_preview_state(self, caves: bool, ores: bool) -> None:
        """Ensure generator preview rows exist without clobbering user-defined layer order.

        Existing generator rows are updated in place so drag/drop ordering is preserved.
        Missing rows are appended near the bottom (under paint layers by default).
        """
        selected_key = self._selected_meta().get("key")

        desired = []
        if caves:
            desired.append((
                "gen:caves",
                "Cave Generator Preview",
                {"kind": "generator", "key": "gen:caves", "generator_kind": "caves", "name": "Cave Generator", "checked": True},
            ))
        if ores:
            desired.append((
                "gen:ores",
                "Ore Generator Preview",
                {"kind": "generator", "key": "gen:ores", "generator_kind": "ores", "name": "Ore Generator", "checked": True},
            ))

        desired_keys = {k for k, _, _ in desired}

        # Remove generator rows no longer desired.
        for i in range(self.list.count() - 1, -1, -1):
            it = self.list.item(i)
            meta = self._item_meta(it)
            if str(meta.get("kind", "")).lower() != "generator":
                continue
            key = str(meta.get("key", ""))
            if key not in desired_keys:
                self.list.takeItem(i)
                self._last_labels_by_key.pop(key, None)

        # Update existing rows in place; create missing rows without resetting order.
        for key, label, meta in desired:
            it = self._find_item_by_key(key)
            if it is None:
                it = self._make_check_item(label, checked=True, meta=meta)
                self.list.addItem(it)
            else:
                if it.text() != label:
                    self._rename_guard = True
                    try:
                        it.setText(label)
                    finally:
                        self._rename_guard = False
                self._check_guard = True
                try:
                    it.setCheckState(QtCore.Qt.CheckState.Checked)
                finally:
                    self._check_guard = False
                merged = self._item_meta(it)
                merged.update(meta)
                merged["label"] = label
                merged["checked"] = True
                self._set_item_meta(it, merged)
            self._last_labels_by_key[str(key)] = label

        if selected_key:
            self._select_item(self._find_item_by_key(str(selected_key)))
        self.refresh_empty_state()
        self._refresh_buttons()

    def restore_layer_stack(self, metas: list[dict], *, selected_key: str | None = None) -> None:
        self.list.clear()
        self._last_labels_by_key.clear()
        for meta in metas or []:
            mm = dict(meta or {})
            label = str(mm.get("label") or mm.get("name") or mm.get("key") or "Layer")
            checked = bool(mm.get("checked", True))
            it = self._make_check_item(label, checked=checked, meta=mm)
            self.list.addItem(it)
            self._last_labels_by_key[str(mm.get("key") or label)] = label
        self.refresh_empty_state()
        if selected_key:
            self.select_layer_by_key(str(selected_key))
        self._refresh_buttons()

    def select_layer_by_key(self, key: str) -> bool:
        it = self._find_item_by_key(key)
        if it is None:
            return False
        self._select_item(it)
        return True

    def current_layer_meta(self) -> dict:
        return self._selected_meta()

    def layer_stack_metas(self) -> list[dict]:
        metas: list[dict] = []
        for i in range(self.list.count()):
            metas.append(self._item_meta(self.list.item(i)))
        return metas

    def set_selected_layer_visibility(self, visible: bool) -> bool:
        item = self._selected_item()
        if item is None:
            return False
        self._check_guard = True
        try:
            item.setCheckState(QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked)
        finally:
            self._check_guard = False
        self._on_item_changed(item)
        return True

    def set_selected_layer_label(self, label: str) -> bool:
        item = self._selected_item()
        if item is None:
            return False
        label = str(label or "").strip()
        if not label:
            return False
        self._rename_guard = False
        item.setText(label)
        # itemChanged will fire and flow through existing rename logic.
        return True
