from __future__ import annotations
import json
from pathlib import Path
from PySide6 import QtWidgets, QtCore


class BlocksPanel(QtWidgets.QWidget):
    """Lists discovered block materials and allows visibility toggles with user-editable groups."""
    visibility_changed = QtCore.Signal()

    ROLE_NAME = int(QtCore.Qt.ItemDataRole.UserRole)
    ROLE_GROUP = int(QtCore.Qt.ItemDataRole.UserRole + 1)

    DEFAULT_GROUP_RULES = {
        "Terrain": {
            "exact": ["minecraft:grass_block"],
            "contains": [
                "dirt", "sand", "gravel", "clay", "mud", "snow", "ice", "mycelium", "podzol",
                "stone", "deepslate", "andesite", "granite", "diorite", "tuff", "calcite", "basalt",
                "blackstone", "bedrock", "netherrack", "end_stone", "soul_soil", "soul_sand",
            ],
            "exclude_contains": ["ore", "log", "wood", "leaves", "grass", "fern", "flower"],
        },
        "Vegetation": {
            "contains": [
                "_log", "_wood", "_leaves", "_sapling", "mangrove_roots", "roots", "vine", "azalea",
                "flower", "bush", "rose", "tulip", "dandelion", "orchid", "lily", "peony", "poppy",
                "grass", "fern", "moss", "mushroom", "bamboo", "cactus", "sugar_cane", "kelp", "seagrass",
                "berry", "crop", "wheat", "carrots", "potatoes", "beetroots", "cocoa",
            ],
            "exclude_exact": ["minecraft:grass_block"],
            "exclude_contains": ["grass_block"],
        },
        "Stone / Rocks": {
            "contains": [
                "stone", "deepslate", "andesite", "granite", "diorite", "tuff", "calcite", "basalt",
                "blackstone", "obsidian", "cobble", "dripstone", "slate"
            ],
            "exclude_contains": ["ore", "brick", "button", "pressure_plate", "wall", "stairs", "slab"],
        },
        "Ores": {
            "contains": ["_ore", "raw_iron_block", "raw_copper_block", "raw_gold_block", "ancient_debris"],
        },
        "Liquids": {
            "contains": ["water", "lava", "bubble_column", "powder_snow"],
        },
        "Preview / Generated": {
            "contains": ["wgl:preview_", "worldgeolabs", "preview_"],
        },
        "Structures / Decor": {
            "contains": [
                "planks", "bricks", "glass", "pane", "door", "trapdoor", "stairs", "slab", "fence", "wall",
                "torch", "lantern", "chest", "barrel", "crafting_table", "furnace", "bed", "carpet", "banner",
                "rail", "redstone", "button", "lever", "pressure_plate", "sign"
            ],
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._vis: dict[str, bool] = {}
        self._group_rules: dict[str, dict] = json.loads(json.dumps(self.DEFAULT_GROUP_RULES))
        self._all_blocks: list[str] = []
        self._pending_filter_text = ""
        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._apply_filter_now)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Blocks / materials")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        desc = QtWidgets.QLabel(
            "Toggle blocks and use groups (Vegetation, Ores, Stone/Rocks, etc.). "
            "Groups are user-editable and never change the world—only viewport visibility."
        )
        desc.setWordWrap(True)
        desc.setObjectName("SubtleHint")
        layout.addWidget(desc)

        # Filter row
        self._filter = QtWidgets.QLineEdit()
        self._filter.setPlaceholderText("Filter blocks (e.g. stone, ore, leaves, wgl:preview)...")
        clear_btn = QtWidgets.QToolButton()
        clear_btn.setText("×")
        clear_btn.setToolTip("Clear filter")
        clear_btn.clicked.connect(self._filter.clear)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(self._filter, 1)
        filter_row.addWidget(clear_btn)
        layout.addLayout(filter_row)

        # Group row
        group_row = QtWidgets.QHBoxLayout()
        group_row.addWidget(QtWidgets.QLabel("Group"))
        self._group_combo = QtWidgets.QComboBox()
        self._group_combo.setMinimumWidth(180)
        self._group_combo.currentTextChanged.connect(lambda *_: self._apply_filter(self._filter.text()))
        group_row.addWidget(self._group_combo, 1)

        self._show_group = QtWidgets.QPushButton("Show group")
        self._hide_group = QtWidgets.QPushButton("Hide group")
        self._edit_groups = QtWidgets.QPushButton("Edit groups…")
        self._load_groups = QtWidgets.QPushButton("Load preset…")
        self._save_groups = QtWidgets.QPushButton("Save preset…")
        self._reset_groups = QtWidgets.QPushButton("Reset")
        group_row.addWidget(self._show_group)
        group_row.addWidget(self._hide_group)
        group_row.addWidget(self._edit_groups)
        layout.addLayout(group_row)

        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("Group presets"))
        preset_row.addWidget(self._load_groups)
        preset_row.addWidget(self._save_groups)
        preset_row.addWidget(self._reset_groups)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        info_row = QtWidgets.QHBoxLayout()
        self._count_lbl = QtWidgets.QLabel("0 materials")
        self._count_lbl.setObjectName("SubtleHint")
        info_row.addWidget(self._count_lbl)
        info_row.addStretch(1)
        self._visible_only = QtWidgets.QCheckBox("Visible only")
        info_row.addWidget(self._visible_only)
        layout.addLayout(info_row)

        self._list = QtWidgets.QListWidget()
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setAlternatingRowColors(True)
        self._list.setUniformItemSizes(True)
        self._list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self._list, 1)

        # Quick actions
        quick_row = QtWidgets.QHBoxLayout()
        self._show_all = QtWidgets.QPushButton("Show all")
        self._hide_all = QtWidgets.QPushButton("Hide all")
        self._preview_only = QtWidgets.QPushButton("Preview only")
        self._hide_common_solid = QtWidgets.QPushButton("Hide common solids")
        quick_row.addWidget(self._show_all)
        quick_row.addWidget(self._hide_all)
        quick_row.addWidget(self._preview_only)
        quick_row.addWidget(self._hide_common_solid)
        layout.addLayout(quick_row)

        selection_row = QtWidgets.QHBoxLayout()
        self._show_selected = QtWidgets.QPushButton("Show selected")
        self._hide_selected = QtWidgets.QPushButton("Hide selected")
        selection_row.addWidget(self._show_selected)
        selection_row.addWidget(self._hide_selected)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        # Wiring
        self._filter.textChanged.connect(self._queue_filter_apply)
        self._visible_only.toggled.connect(lambda *_: self._apply_filter(self._filter.text()))
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.itemDoubleClicked.connect(self._toggle_item)
        self._list.customContextMenuRequested.connect(self._open_menu)
        self._show_all.clicked.connect(lambda: self._set_all(True))
        self._hide_all.clicked.connect(lambda: self._set_all(False))
        self._show_group.clicked.connect(lambda: self._set_group_visibility(True))
        self._hide_group.clicked.connect(lambda: self._set_group_visibility(False))
        self._edit_groups.clicked.connect(self._edit_groups_dialog)
        self._load_groups.clicked.connect(self._load_groups_preset)
        self._save_groups.clicked.connect(self._save_groups_preset)
        self._reset_groups.clicked.connect(self._reset_groups_defaults)
        self._preview_only.clicked.connect(self._set_preview_only)
        self._hide_common_solid.clicked.connect(self._hide_common_solids)
        self._show_selected.clicked.connect(lambda: self._set_selected(True))
        self._hide_selected.clicked.connect(lambda: self._set_selected(False))

        self._refresh_group_combo()

    # ---------- classification / groups ----------
    def _normalize_rule_map(self, raw: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for group_name, cfg in (raw or {}).items():
            if not str(group_name).strip():
                continue
            d = dict(cfg or {})
            out[str(group_name)] = {
                "exact": [str(x) for x in d.get("exact", []) if str(x).strip()],
                "contains": [str(x) for x in d.get("contains", []) if str(x).strip()],
                "exclude_exact": [str(x) for x in d.get("exclude_exact", []) if str(x).strip()],
                "exclude_contains": [str(x) for x in d.get("exclude_contains", []) if str(x).strip()],
            }
        if not out:
            out = json.loads(json.dumps(self.DEFAULT_GROUP_RULES))
        return out

    def _refresh_group_combo(self) -> None:
        current = self._group_combo.currentText() or "All groups"
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem("All groups")
        for name in sorted(self._group_rules.keys()):
            self._group_combo.addItem(name)
        self._group_combo.addItem("Other")
        idx = self._group_combo.findText(current)
        self._group_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._group_combo.blockSignals(False)

    def _classify_group(self, block_name: str) -> str:
        n = str(block_name).lower()
        for group_name, cfg in self._group_rules.items():
            ex = [x.lower() for x in cfg.get("exclude_exact", [])]
            ex_contains = [x.lower() for x in cfg.get("exclude_contains", [])]
            if n in ex:
                continue
            if any(tok and tok in n for tok in ex_contains):
                continue

            exact = [x.lower() for x in cfg.get("exact", [])]
            contains = [x.lower() for x in cfg.get("contains", [])]
            if n in exact or any(tok and tok in n for tok in contains):
                return group_name
        return "Other"

    def _item_group(self, it: QtWidgets.QListWidgetItem) -> str:
        return str(it.data(self.ROLE_GROUP) or "Other")

    def _set_group_visibility(self, visible: bool) -> None:
        group_name = self._group_combo.currentText()
        if not group_name or group_name == "All groups":
            self._set_all(visible)
            return
        state = QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            it = self._list.item(i)
            if self._item_group(it) != group_name:
                continue
            if it.isHidden():
                # still apply even if hidden by text filter? yes, if group matches active group filter this is fine.
                pass
            it.setCheckState(state)
        self._list.blockSignals(False)
        self.visibility_changed.emit()
        self._apply_filter(self._filter.text())

    def _edit_groups_dialog(self) -> None:
        pretty = json.dumps(self._group_rules, indent=2, sort_keys=True)
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "Edit block groups",
            "Edit JSON rules (keys: exact, contains, exclude_exact, exclude_contains):",
            pretty,
        )
        if not ok:
            return
        try:
            data = json.loads(text)
            self._group_rules = self._normalize_rule_map(data)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Invalid group JSON", f"Could not parse groups:\n{exc}")
            return
        self._refresh_group_combo()
        self._rebuild_list_preserve_state()
        self._apply_filter(self._filter.text())


    def _save_groups_preset(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save block group preset",
            str(Path.home() / "wgl_block_groups.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            payload = {
                "version": 1,
                "groups": self._group_rules,
            }
            Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            QtWidgets.QMessageBox.information(self, "Preset saved", f"Saved group preset to:\n{path}")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save failed", f"Could not save preset:\n{exc}")

    def _load_groups_preset(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load block group preset",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "groups" in raw:
                data = raw.get("groups", {})
            else:
                data = raw
            self._group_rules = self._normalize_rule_map(data)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Load failed", f"Could not load preset:\n{exc}")
            return
        self._refresh_group_combo()
        self._rebuild_list_preserve_state()
        self._apply_filter(self._filter.text())
        QtWidgets.QMessageBox.information(self, "Preset loaded", f"Loaded group preset from:\n{path}")

    def _reset_groups_defaults(self) -> None:
        self._group_rules = json.loads(json.dumps(self.DEFAULT_GROUP_RULES))
        self._refresh_group_combo()
        self._rebuild_list_preserve_state()
        self._apply_filter(self._filter.text())

    # ---------- public API ----------
    def set_blocks(self, names: list[str]) -> None:
        self._all_blocks = sorted(set(str(n) for n in (names or [])))
        self.setUpdatesEnabled(False)
        try:
            self._rebuild_list_preserve_state()
            self._apply_filter(self._filter.text())
        finally:
            self.setUpdatesEnabled(True)

    def set_visibility_map(self, vis: dict[str, bool], *, emit: bool = True) -> None:
        self._vis.update({str(k): bool(v) for k, v in dict(vis or {}).items()})
        self.setUpdatesEnabled(False)
        try:
            self._rebuild_list_preserve_state()
            self._apply_filter(self._filter.text())
        finally:
            self.setUpdatesEnabled(True)
        if emit:
            self.visibility_changed.emit()

    def visibility_map(self) -> dict[str, bool]:
        for i in range(self._list.count()):
            it = self._list.item(i)
            name = str(it.data(self.ROLE_NAME) or it.text().split("  [", 1)[0])
            self._vis[name] = (it.checkState() == QtCore.Qt.CheckState.Checked)
        return dict(self._vis)

    # ---------- list population ----------
    def _rebuild_list_preserve_state(self) -> None:
        # preserve UI state
        for i in range(self._list.count()):
            it = self._list.item(i)
            name = str(it.data(self.ROLE_NAME) or it.text().split("  [", 1)[0])
            self._vis[name] = (it.checkState() == QtCore.Qt.CheckState.Checked)

        selected_names = {
            str(it.data(self.ROLE_NAME) or it.text().split("  [", 1)[0])
            for it in self._list.selectedItems()
        }

        self._list.setUpdatesEnabled(False)
        self._list.blockSignals(True)
        self._list.clear()
        try:
            for name in self._all_blocks:
                grp = self._classify_group(name)
                visible = self._vis.get(name, True)
                it = QtWidgets.QListWidgetItem(f"{name}  [{grp}]")
                it.setData(self.ROLE_NAME, name)
                it.setData(self.ROLE_GROUP, grp)
                it.setToolTip(f"{name}\nGroup: {grp}")
                it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsSelectable)
                it.setCheckState(QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked)
                self._list.addItem(it)
                if name in selected_names:
                    it.setSelected(True)
        finally:
            self._list.blockSignals(False)
            self._list.setUpdatesEnabled(True)

    # ---------- actions ----------
    def _set_all(self, visible: bool) -> None:
        state = QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.isHidden():
                continue
            it.setCheckState(state)
        self._list.blockSignals(False)
        self.visibility_changed.emit()
        self._apply_filter(self._filter.text())

    def _set_selected(self, visible: bool) -> None:
        state = QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked
        items = self._list.selectedItems()
        if not items:
            return
        self._list.blockSignals(True)
        for it in items:
            it.setCheckState(state)
        self._list.blockSignals(False)
        self.visibility_changed.emit()
        self._apply_filter(self._filter.text())

    def _set_preview_only(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            it = self._list.item(i)
            name = str(it.data(self.ROLE_NAME) or it.text())
            visible = name.startswith("wgl:preview_")
            it.setCheckState(QtCore.Qt.CheckState.Checked if visible else QtCore.Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self.visibility_changed.emit()
        self._apply_filter(self._filter.text())

    def _hide_common_solids(self) -> None:
        solids = {
            "minecraft:stone", "minecraft:deepslate", "minecraft:dirt", "minecraft:grass_block",
            "minecraft:tuff", "minecraft:andesite", "minecraft:diorite", "minecraft:granite",
            "minecraft:bedrock", "minecraft:netherrack", "minecraft:end_stone",
        }
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            it = self._list.item(i)
            name = str(it.data(self.ROLE_NAME) or it.text())
            if name in solids:
                it.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self.visibility_changed.emit()
        self._apply_filter(self._filter.text())

    def _toggle_item(self, it: QtWidgets.QListWidgetItem) -> None:
        it.setCheckState(
            QtCore.Qt.CheckState.Unchecked
            if it.checkState() == QtCore.Qt.CheckState.Checked
            else QtCore.Qt.CheckState.Checked
        )

    def _open_menu(self, pos):
        it = self._list.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        a_show_sel = menu.addAction("Show selected")
        a_hide_sel = menu.addAction("Hide selected")
        menu.addSeparator()
        a_show_filtered = menu.addAction("Show filtered")
        a_hide_filtered = menu.addAction("Hide filtered")
        menu.addSeparator()
        a_show_group = menu.addAction(f"Show group: {self._group_combo.currentText()}")
        a_hide_group = menu.addAction(f"Hide group: {self._group_combo.currentText()}")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == a_show_sel:
            self._set_selected(True)
        elif chosen == a_hide_sel:
            self._set_selected(False)
        elif chosen == a_show_filtered:
            self._set_all(True)
        elif chosen == a_hide_filtered:
            self._set_all(False)
        elif chosen == a_show_group:
            self._set_group_visibility(True)
        elif chosen == a_hide_group:
            self._set_group_visibility(False)

    def _on_item_changed(self, *_):
        self.visibility_changed.emit()
        if self._visible_only.isChecked():
            self._apply_filter(self._filter.text())

    def _queue_filter_apply(self, text: str) -> None:
        self._pending_filter_text = str(text)
        self._filter_timer.start()

    def _apply_filter_now(self) -> None:
        self._apply_filter(self._pending_filter_text)

    def _apply_filter(self, text: str) -> None:
        t = text.lower().strip()
        selected_group = self._group_combo.currentText()
        visible_count = 0
        total = self._list.count()
        group_counts: dict[str, int] = {}
        self._list.setUpdatesEnabled(False)
        try:
            for i in range(total):
                it = self._list.item(i)
                grp = self._item_group(it)
                group_counts[grp] = group_counts.get(grp, 0) + 1
                name = str(it.data(self.ROLE_NAME) or it.text()).lower()
                matches_text = (not t) or (t in name)
                matches_visible = (not self._visible_only.isChecked()) or (it.checkState() == QtCore.Qt.CheckState.Checked)
                matches_group = (selected_group in ("", "All groups")) or (grp == selected_group)
                hidden = not (matches_text and matches_visible and matches_group)
                it.setHidden(hidden)
                if not hidden:
                    visible_count += 1
        finally:
            self._list.setUpdatesEnabled(True)
        group_note = ""
        if selected_group and selected_group != "All groups":
            group_note = f" | group '{selected_group}': {group_counts.get(selected_group, 0)}"
        self._count_lbl.setText(f"{visible_count} shown / {total} total{group_note}")
