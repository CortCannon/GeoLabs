from __future__ import annotations
import logging
import json
import os
from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtGui

from ..core.uistate import UIState
from .log_handler import QtLogHandler
from .widgets.layers_panel import LayersPanel
from .widgets.blocks_panel import BlocksPanel
from .widgets.params_panel import ParamsPanel
from .widgets.paint_panel import PaintPanel
from .widgets.edit_core_panel import EditCorePanel
from .widgets.log_panel import LogPanel
from .dialogs.performance_dialog import PerformanceDialog
from .dialogs.apply_dialog import ApplyDialog
from .dialogs.create_feature_dialog import CreateFeatureDialog
from .dialogs.startup_dialog import StartupDialog
from .dialogs.project_area_dialog import ProjectAreaDialog
from ..rendering.renderer_manager import RendererManager
from ..world.world_open import WorldIndexer
from ..world.anvil_reader import AnvilWorld
from ..world.region_warmup import RegionWarmupWorker, region_files_for_chunk_bounds
from ..edit.core.integration_bridge import EditingCoreController
from ..edit.core.demo_chunk_adapter import DemoChunkAdapter

log = logging.getLogger("mcgeo.ui")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("WorldGeoLabs")
        self.setObjectName("MainWindow")
        self.setDockOptions(
            QtWidgets.QMainWindow.DockOption.AllowNestedDocks
            | QtWidgets.QMainWindow.DockOption.AllowTabbedDocks
            | QtWidgets.QMainWindow.DockOption.AnimatedDocks
            | QtWidgets.QMainWindow.DockOption.GroupedDragging
        )

        self.state = UIState()
        self._ui_settings = QtCore.QSettings("WorldGeoLabs", "WorldGeoLabs")
        self._perf_dlg: PerformanceDialog | None = None

        # Logging to UI
        self.log_panel = LogPanel()
        self._log_handler = QtLogHandler()
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s: %(message)s", "%H:%M:%S")
        )
        self._log_handler.message.connect(self.log_panel.append)
        logging.getLogger().addHandler(self._log_handler)

        # Panels
        self.layers_panel = LayersPanel()
        self.blocks_panel = BlocksPanel()
        self.params_panel = ParamsPanel()
        self.paint_panel = PaintPanel()
        self._paint_layer_strokes: dict[str, int] = {}
        self._paint_layers: dict[str, dict] = {}
        self._paint_layer_serial = 1
        self.edit_core_panel = EditCorePanel()
        self.edit_core = EditingCoreController()
        self._edit_core_box_params: dict = self.edit_core_panel.params()
        self._anvil_world: AnvilWorld | None = None
        self._last_world_index = None
        self._dev_tools_visible = False
        self._edit_core_tab_index = -1
        self._layer_header_sync_guard = False
        self._layer_header_meta: dict = {}
        self._startup_prompt_shown = False
        self._pending_project_payload: dict | None = None

        # Renderer (strict GL mode)
        self.renderer_mgr = RendererManager()
        self.viewport = self.renderer_mgr.create_viewport()
        self.viewport.setObjectName("WorldViewport")
        self.renderer_mgr.materials_changed.connect(self._on_materials_changed)
        self.renderer_mgr.paint_hover_changed.connect(self._on_paint_hover_changed)
        self.renderer_mgr.paint_stroke_committed.connect(self._on_paint_stroke_committed)

        # Layout / docks
        self._build_docks()
        self._build_workspace_shell()

        # Toolbar / menus / status
        self._build_toolbar()
        self._build_menus()
        self._build_status_widgets()

        self.statusBar().showMessage("Ready")

        # Indexer worker
        self._indexer = WorldIndexer()
        self._indexer.progress.connect(self._on_index_progress)
        self._indexer.finished.connect(self._on_index_done)
        self._indexer.failed.connect(self._on_index_failed)

        # UI signals
        self.params_panel.view_mode.currentTextChanged.connect(self._on_view_mode)
        self.params_panel.preview_settings_changed.connect(self._on_preview_settings_changed)
        self.params_panel.view_settings_changed.connect(self._on_view_settings_changed)
        self.blocks_panel.visibility_changed.connect(self._on_blocks_visibility)
        self.paint_panel.paint_settings_changed.connect(self._on_paint_settings_changed)
        self.paint_panel.realign_requested.connect(self._on_paint_realign_requested)
        self.paint_panel.add_layer_requested.connect(self._on_add_paint_layer)
        self.paint_panel.import_model_requested.connect(self._on_import_model_requested)
        self.paint_panel.focus_paint_requested.connect(self._focus_paint_tab)
        self.layers_panel.create_feature_requested.connect(self._show_create_feature_dialog)
        self.layers_panel.quick_feature_requested.connect(self._on_quick_feature_requested)
        self.layers_panel.layer_selected.connect(self._on_layer_selected)
        self.layers_panel.layer_edit_requested.connect(self._on_layer_edit_requested)
        self.layers_panel.layer_remove_requested.connect(self._on_layer_remove_requested)
        self.layers_panel.layer_duplicate_requested.connect(self._on_layer_duplicate_requested)
        self.layers_panel.layer_renamed.connect(self._on_layer_renamed)
        self.layers_panel.layer_visibility_changed.connect(self._on_layer_visibility_changed)
        self.layers_panel.layer_reordered.connect(self._on_layer_reordered)
        self.edit_core_panel.box_params_changed.connect(self._on_edit_core_box_params_changed)
        self.edit_core_panel.add_box_layer_requested.connect(self._on_edit_core_add_box_layer)
        self.edit_core_panel.preview_requested.connect(self._on_edit_core_preview)
        self.edit_core_panel.apply_demo_requested.connect(self._on_edit_core_apply_demo)
        self._layer_header_name.editingFinished.connect(self._on_layer_header_name_edited)
        self._layer_header_enabled.toggled.connect(self._on_layer_header_enabled_toggled)
        self._layer_header_dup.clicked.connect(lambda: self.layers_panel.btn_duplicate.click())
        self._layer_header_del.clicked.connect(lambda: self.layers_panel.btn_remove.click())

        # Seed initial settings into renderer
        self._push_preview_settings_to_renderer(self.params_panel.preview_settings())
        self.renderer_mgr.set_view_settings(self.params_panel.view_settings())
        self.renderer_mgr.set_view_mode(self.params_panel.view_mode.currentText())
        self.renderer_mgr.set_paint_settings(self.paint_panel.settings())
        self.edit_core_panel.set_stats(
            "Developer / internal editing-core tools\n"
            "- Hidden by default in the workflow reset build\n"
            "- Use only for backend milestone testing"
        )
        self._sync_layer_header_from_layers_selection()

        # Poll performance snapshot for status labels (lightweight)
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status_snapshot)
        self._status_timer.start()
        self._sync_preview_ui_state()
        self._restore_window_layout()
        self._sync_workspace_header()

    # ---------------- UI building ----------------
    def _build_docks(self) -> None:
        self.left_dock = QtWidgets.QDockWidget("Layers", self)
        self.left_dock.setObjectName("dock_layers")
        self.left_dock.setWidget(self.layers_panel)
        self.left_dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea)
        self.left_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.left_dock.setMinimumWidth(320)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        # Layer editor dock (replaces visible "Inspector" tabs UX)
        self.right_dock = QtWidgets.QDockWidget("Edit Selected Layer", self)
        self.right_dock.setObjectName("dock_layer_editor")

        self.inspector_tabs = QtWidgets.QTabWidget()
        self.inspector_tabs.setObjectName("LayerEditorPages")
        self.inspector_tabs.setDocumentMode(True)
        self.inspector_tabs.setUsesScrollButtons(False)

        self.inspector_tabs.addTab(self.params_panel, "Scene / Preview")
        self.inspector_tabs.addTab(self.paint_panel, "Painter")
        self._edit_core_tab_index = self.inspector_tabs.addTab(self.edit_core_panel, "Advanced / Dev")
        self.inspector_tabs.setTabVisible(self._edit_core_tab_index, False)

        self._layer_editor_title = QtWidgets.QLabel("Scene Tools")
        self._layer_editor_title.setObjectName("PanelTitle")
        self._layer_editor_hint = QtWidgets.QLabel(
            "Select a feature/layer on the left to edit it. "
            "If no layer is selected, scene cutaway + generator controls are shown."
        )
        self._layer_editor_hint.setObjectName("SubtleHint")
        self._layer_editor_hint.setWordWrap(True)

        # Compact "edit selected layer" header card (keeps workflow clean and focused)
        self._layer_header_card = QtWidgets.QFrame()
        self._layer_header_card.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self._layer_header_card.setObjectName("LayerHeaderCard")

        self._layer_header_name = QtWidgets.QLineEdit()
        self._layer_header_name.setPlaceholderText("Selected layer name")
        self._layer_header_name.setClearButtonEnabled(False)

        self._layer_header_type = QtWidgets.QLabel("Scene")
        self._layer_header_type.setObjectName("StatusPill")
        self._layer_header_type.setMinimumWidth(110)

        self._layer_header_enabled = QtWidgets.QCheckBox("Visible / Enabled")
        self._layer_header_dup = QtWidgets.QToolButton()
        self._layer_header_dup.setText("Duplicate")
        self._layer_header_del = QtWidgets.QToolButton()
        self._layer_header_del.setText("Delete")

        header_top = QtWidgets.QHBoxLayout()
        header_top.setContentsMargins(8, 8, 8, 4)
        header_top.addWidget(QtWidgets.QLabel("Selected Layer"))
        header_top.addStretch(1)
        header_top.addWidget(self._layer_header_type)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(8, 0, 8, 8)
        header_row.addWidget(self._layer_header_name, 1)
        header_row.addWidget(self._layer_header_enabled)
        header_row.addWidget(self._layer_header_dup)
        header_row.addWidget(self._layer_header_del)

        header_layout = QtWidgets.QVBoxLayout(self._layer_header_card)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addLayout(header_top)
        header_layout.addLayout(header_row)

        editor_container = QtWidgets.QWidget()
        editor_layout = QtWidgets.QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(6)
        editor_layout.addWidget(self._layer_editor_title)
        editor_layout.addWidget(self._layer_editor_hint)
        editor_layout.addWidget(self._layer_header_card)
        editor_layout.addWidget(self.inspector_tabs, 1)

        editor_scroll = QtWidgets.QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        editor_scroll.setWidget(editor_container)

        self.right_dock.setWidget(editor_scroll)
        self.right_dock.setMinimumWidth(380)
        self.right_dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.RightDockWidgetArea)
        self.right_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.right_dock)

        # Separate blocks dock (cleaner than mixing into inspector tabs)
        self.blocks_dock = QtWidgets.QDockWidget("Blocks Visibility", self)
        self.blocks_dock.setObjectName("dock_blocks")
        self.blocks_dock.setWidget(self.blocks_panel)
        self.blocks_dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea | QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.blocks_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.blocks_dock.setMinimumWidth(360)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.blocks_dock)
        self.tabifyDockWidget(self.right_dock, self.blocks_dock)
        self.right_dock.raise_()

        self.bottom_dock = QtWidgets.QDockWidget("Logs", self)
        self.bottom_dock.setObjectName("dock_logs")
        self.bottom_dock.setWidget(self.log_panel)
        self.bottom_dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea)
        self.bottom_dock.setMinimumHeight(220)
        self.bottom_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)

    def _std_icon(self, pixmap_enum):
        return self.style().standardIcon(pixmap_enum)

    def _build_workspace_shell(self) -> None:
        root = QtWidgets.QWidget()
        root.setObjectName("WorkspaceRoot")
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        header = QtWidgets.QFrame()
        header.setObjectName("WorkspaceHeader")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(14, 12, 14, 12)
        hl.setSpacing(12)

        title_col = QtWidgets.QVBoxLayout()
        title_col.setSpacing(2)
        self._workspace_title = QtWidgets.QLabel("WorldGeoLabs Workspace")
        self._workspace_title.setObjectName("WorkspaceTitle")
        self._workspace_subtitle = QtWidgets.QLabel(
            "Open a world, choose a project area, then build non-destructive underground feature layers."
        )
        self._workspace_subtitle.setObjectName("SubtleHint")
        self._workspace_subtitle.setWordWrap(True)
        title_col.addWidget(self._workspace_title)
        title_col.addWidget(self._workspace_subtitle)
        hl.addLayout(title_col, 1)

        pills = QtWidgets.QVBoxLayout()
        pills.setSpacing(6)
        self._workspace_world = QtWidgets.QLabel("No world loaded")
        self._workspace_world.setObjectName("HeaderPill")
        self._workspace_area = QtWidgets.QLabel("Area not selected")
        self._workspace_area.setObjectName("HeaderPill")
        self._workspace_tool = QtWidgets.QLabel("Tool: Navigate")
        self._workspace_tool.setObjectName("HeaderPill")
        pills.addWidget(self._workspace_world)
        pills.addWidget(self._workspace_area)
        pills.addWidget(self._workspace_tool)
        hl.addLayout(pills)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(8)
        self._workspace_open_btn = QtWidgets.QPushButton("Open World")
        self._workspace_open_btn.setObjectName("PrimaryButton")
        self._workspace_area_btn = QtWidgets.QPushButton("Project Area")
        self._workspace_feature_btn = QtWidgets.QPushButton("Create Feature")
        self._workspace_open_btn.clicked.connect(self.open_world)
        self._workspace_area_btn.clicked.connect(self.edit_project_area)
        self._workspace_feature_btn.clicked.connect(self._show_create_feature_dialog)
        actions.addWidget(self._workspace_open_btn)
        actions.addWidget(self._workspace_area_btn)
        actions.addWidget(self._workspace_feature_btn)
        hl.addLayout(actions)

        viewport_frame = QtWidgets.QFrame()
        viewport_frame.setObjectName("ViewportCard")
        vf = QtWidgets.QVBoxLayout(viewport_frame)
        vf.setContentsMargins(1, 1, 1, 1)
        vf.setSpacing(0)
        vf.addWidget(self.viewport, 1)

        layout.addWidget(header)
        layout.addWidget(viewport_frame, 1)
        self.setCentralWidget(root)
        self._workspace_root = root

    def _sync_workspace_header(self) -> None:
        if not hasattr(self, "_workspace_world"):
            return
        world_name = str(self.state.world_name or "No world loaded")
        self._workspace_world.setText(f"World: {world_name}")
        area_text = getattr(self, "_sb_area", None).text() if hasattr(self, "_sb_area") else "Area: not set"
        tool_text = getattr(self, "_sb_tool", None).text() if hasattr(self, "_sb_tool") else "Tool: Navigate"
        preview_text = getattr(self, "_sb_preview", None).text() if hasattr(self, "_sb_preview") else "Preview: Off"
        self._workspace_area.setText(f"{area_text}  •  {preview_text}")
        self._workspace_tool.setText(tool_text)
        if self.state.world_name:
            self._workspace_subtitle.setText(
                "Work layer-first: select a feature on the left, adjust it on the right, and preview the result in 3D before applying changes."
            )
        else:
            self._workspace_subtitle.setText(
                "Open a world, choose a project area, then build non-destructive underground feature layers."
            )

    def _restore_window_layout(self) -> None:
        try:
            geometry = self._ui_settings.value("main/geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            state = self._ui_settings.value("main/windowState")
            if state is not None:
                self.restoreState(state)
        except Exception:
            log.exception("Failed to restore saved window layout")

    def _save_window_layout(self) -> None:
        try:
            self._ui_settings.setValue("main/geometry", self.saveGeometry())
            self._ui_settings.setValue("main/windowState", self.saveState())
        except Exception:
            log.exception("Failed to save window layout")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._save_window_layout()
        super().closeEvent(event)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setIconSize(QtCore.QSize(18, 18))
        tb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.PreventContextMenu)
        self.main_toolbar = tb

        self.act_open = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_DirOpenIcon), "Open World", self)
        self.act_open.setStatusTip("Open a Minecraft Java world folder")
        self.act_open.triggered.connect(self.open_world)
        tb.addAction(self.act_open)

        self.act_load_project = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogContentsView), "Load Project", self)
        self.act_load_project.setStatusTip("Load a WorldGeoLabs project (.mcgeo.json)")
        self.act_load_project.triggered.connect(self.load_project)
        tb.addAction(self.act_load_project)

        self.act_save_project = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_DialogSaveButton), "Save Project", self)
        self.act_save_project.setStatusTip("Save WorldGeoLabs project (.mcgeo.json)")
        self.act_save_project.triggered.connect(self.save_project)
        tb.addAction(self.act_save_project)


        tb.addSeparator()

        self.act_project_area = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_DialogOpenButton), "Project Area", self)
        self.act_project_area.setStatusTip("Choose or change the project edit area (2D overview map)")
        self.act_project_area.triggered.connect(self.edit_project_area)
        tb.addAction(self.act_project_area)

        self.act_create_feature = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogNewFolder), "Create Feature", self)
        self.act_create_feature.setStatusTip("Add a non-destructive cave, ore, paint, or shape layer")
        self.act_create_feature.triggered.connect(self._show_create_feature_dialog)
        tb.addAction(self.act_create_feature)

        self.act_perf = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon), "Performance", self)
        self.act_perf.setStatusTip("Open performance tuning dialog")
        self.act_perf.triggered.connect(self.show_performance)
        tb.addAction(self.act_perf)

        self.act_paint = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_DirHomeIcon), "Painter", self)
        self.act_paint.setCheckable(True)
        self.act_paint.setStatusTip("Toggle 3D painter preview mode")
        self.act_paint.toggled.connect(self._on_toolbar_paint_toggled)
        tb.addAction(self.act_paint)

        self.act_apply = QtGui.QAction(self._std_icon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton), "Apply", self)
        self.act_apply.setStatusTip("Open apply dialog (safe write pipeline)")
        self.act_apply.triggered.connect(self.show_apply)
        tb.addAction(self.act_apply)

        tb.addSeparator()
        self.act_toggle_logs = QtGui.QAction("Logs", self)
        self.act_toggle_logs.setCheckable(True)
        self.act_toggle_logs.setChecked(True)
        self.act_toggle_logs.toggled.connect(self.bottom_dock.setVisible)
        self.bottom_dock.visibilityChanged.connect(self.act_toggle_logs.setChecked)
        tb.addAction(self.act_toggle_logs)

    def _build_menus(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        m_file.addAction(self.act_open)
        m_file.addSeparator()
        m_file.addAction(self.act_load_project)
        m_file.addAction(self.act_save_project)
        m_file.addSeparator()
        m_file.addAction(self.act_apply)

        m_view = mb.addMenu("&View")
        m_view.addAction(self.left_dock.toggleViewAction())
        m_view.addAction(self.right_dock.toggleViewAction())
        m_view.addAction(self.blocks_dock.toggleViewAction())
        m_view.addAction(self.bottom_dock.toggleViewAction())
        m_view.addSeparator()
        if self.main_toolbar is not None:
            m_view.addAction(self.main_toolbar.toggleViewAction())

        m_tools = mb.addMenu("&Tools")
        m_tools.addAction(self.act_create_feature)
        m_tools.addAction(self.act_perf)
        m_tools.addAction(self.act_paint)
        m_tools.addSeparator()
        self.act_dev_tools = QtGui.QAction("Show Developer Tools", self)
        self.act_dev_tools.setCheckable(True)
        self.act_dev_tools.setChecked(False)
        self.act_dev_tools.toggled.connect(self._set_dev_tools_visible)
        m_tools.addAction(self.act_dev_tools)

        m_help = mb.addMenu("&Help")
        about = QtGui.QAction("About WorldGeoLabs (preview build)", self)
        about.triggered.connect(self._show_about)
        m_help.addAction(about)

    def _build_status_widgets(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(True)

        self._sb_world = QtWidgets.QLabel("World: none")
        self._sb_world.setObjectName("StatusPill")
        self._sb_view = QtWidgets.QLabel("View: Surface")
        self._sb_view.setObjectName("StatusPill")
        self._sb_perf = QtWidgets.QLabel("FPS: -- | Resident: --")
        self._sb_perf.setObjectName("StatusPill")
        self._sb_mode = QtWidgets.QLabel("Renderer: OpenGL")
        self._sb_mode.setObjectName("StatusPill")
        self._sb_tool = QtWidgets.QLabel("Tool: Navigate")
        self._sb_tool.setObjectName("StatusPill")
        self._sb_area = QtWidgets.QLabel("Area: not set")
        self._sb_area.setObjectName("StatusPill")
        self._sb_preview = QtWidgets.QLabel("Preview: Off")
        self._sb_preview.setObjectName("StatusPill")

        for w in (self._sb_world, self._sb_view, self._sb_perf, self._sb_mode, self._sb_tool, self._sb_area, self._sb_preview):
            sb.addPermanentWidget(w)

    # ---------------- Actions ----------------
    def _show_not_implemented(self, name: str) -> None:
        QtWidgets.QMessageBox.information(
            self,
            f"{name} (next milestone)",
            f"{name} is not available in this build."
        )

    def _show_about(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "About WorldGeoLabs",
            "WorldGeoLabs preview build\n\n"
            "Windows-first Minecraft Java (Anvil) underground editor prototype.\n"
            "Current focus: streamed OpenGL viewport + inspect-first workflow + non-destructive feature previews."
        )

    def _set_dev_tools_visible(self, visible: bool) -> None:
        self._dev_tools_visible = bool(visible)
        if hasattr(self, "inspector_tabs") and self._edit_core_tab_index >= 0:
            self.inspector_tabs.setTabVisible(self._edit_core_tab_index, self._dev_tools_visible)
            if self._dev_tools_visible:
                self.statusBar().showMessage("Developer tools enabled (advanced layer editor available)")
            else:
                if self.inspector_tabs.currentIndex() == self._edit_core_tab_index:
                    self.inspector_tabs.setCurrentWidget(self.params_panel)
                    self._set_layer_editor_context("Scene Tools")
                self.statusBar().showMessage("Developer tools hidden")

    def _set_layer_editor_context(self, title: str, hint: str | None = None) -> None:
        try:
            if hasattr(self, "_layer_editor_title"):
                self._layer_editor_title.setText(title)
            if hasattr(self, "_layer_editor_hint"):
                if hint is None:
                    self._layer_editor_hint.setVisible(False)
                else:
                    self._layer_editor_hint.setVisible(True)
                    self._layer_editor_hint.setText(hint)
        except Exception:
            pass


    def _layer_type_label(self, meta: dict | None) -> str:
        m = dict(meta or {})
        kind = str(m.get("kind", "")).lower()
        if not kind:
            return "Scene"
        if kind == "generator":
            gk = str(m.get("generator_kind", "generator")).strip() or "generator"
            return f"Generator • {gk.title()}"
        if kind == "paint":
            return "Paint Layer"
        if kind == "editcore":
            return "Advanced / Dev"
        return kind.replace("_", " ").title()

    def _layer_header_display_name(self, meta: dict | None) -> str:
        m = dict(meta or {})
        kind = str(m.get("kind", "")).lower()
        if kind == "paint":
            return str(m.get("name") or m.get("label") or "Paint Layer")
        if kind == "generator":
            gk = str(m.get("generator_kind", "Generator")).title()
            return f"{gk} Preview"
        if kind == "editcore":
            return str(m.get("name") or "Box Replace (Dev)")
        return str(m.get("label") or "Scene Tools")

    def _layer_header_name_editable(self, meta: dict | None) -> bool:
        m = dict(meta or {})
        kind = str(m.get("kind", "")).lower()
        return kind in {"paint", "editcore"}

    def _sync_layer_header_from_layers_selection(self) -> None:
        try:
            meta = self.layers_panel.current_layer_meta()
        except Exception:
            meta = {}
        self._layer_header_meta = dict(meta or {})
        self._layer_header_sync_guard = True
        try:
            has_layer = bool(meta)
            self._layer_header_card.setVisible(True)
            self._layer_header_name.setEnabled(has_layer)
            self._layer_header_enabled.setEnabled(has_layer)
            self._layer_header_dup.setEnabled(has_layer)
            self._layer_header_del.setEnabled(has_layer)
            if not has_layer:
                self._layer_header_type.setText("Scene")
                self._layer_header_name.setText("")
                self._layer_header_name.setPlaceholderText("No layer selected")
                self._layer_header_enabled.setChecked(False)
                self._layer_header_enabled.setText("Visible / Enabled")
                return
            self._layer_header_type.setText(self._layer_type_label(meta))
            self._layer_header_name.setText(self._layer_header_display_name(meta))
            self._layer_header_name.setReadOnly(not self._layer_header_name_editable(meta))
            self._layer_header_name.setEnabled(True)
            self._layer_header_name.setPlaceholderText("Layer name")
            checked = bool(meta.get("checked", True))
            self._layer_header_enabled.setChecked(checked)
            kind = str(meta.get("kind", "")).lower()
            if kind == "generator":
                self._layer_header_enabled.setText("Preview visible")
            elif kind == "paint":
                self._layer_header_enabled.setText("Layer visible")
            else:
                self._layer_header_enabled.setText("Visible / Enabled")
        finally:
            self._layer_header_sync_guard = False

    @QtCore.Slot()
    def _on_layer_header_name_edited(self) -> None:
        if self._layer_header_sync_guard:
            return
        try:
            meta = self.layers_panel.current_layer_meta()
        except Exception:
            meta = {}
        if not meta:
            return
        if not self._layer_header_name_editable(meta):
            self._sync_layer_header_from_layers_selection()
            return
        name = self._layer_header_name.text().strip()
        if not name:
            self._sync_layer_header_from_layers_selection()
            return
        # Paint layers have styled labels in the layer list; normalize here.
        if str(meta.get("kind", "")).lower() == "paint" and not name.lower().startswith("paint •"):
            name = f"Paint • {name}"
        try:
            self.layers_panel.set_selected_layer_label(name)
        except Exception:
            pass
        self._sync_layer_header_from_layers_selection()

    @QtCore.Slot(bool)
    def _on_layer_header_enabled_toggled(self, checked: bool) -> None:
        if self._layer_header_sync_guard:
            return
        try:
            self.layers_panel.set_selected_layer_visibility(bool(checked))
        except Exception:
            pass
        self._sync_layer_header_from_layers_selection()

    def _preview_layer_order_for_renderer(self) -> list[str]:
        """Return generator preview layer order from the visible layer stack (top -> bottom).

        The mesh preview currently supports order-sensitive evaluation for generator layers
        (caves / ores). Non-generator layers are ignored by the renderer in this milestone.
        """
        out: list[str] = []
        try:
            metas = self.layers_panel.layer_stack_metas()
        except Exception:
            metas = []
        for m in metas:
            try:
                mm = dict(m or {})
            except Exception:
                continue
            if str(mm.get("kind", "")).lower() != "generator":
                continue
            if not bool(mm.get("checked", True)):
                continue
            key = str(mm.get("key", "")).strip().lower()
            if key in {"gen:caves", "gen:ores"} and key not in out:
                out.append(key)
        return out

    @QtCore.Slot()
    def _on_paint_realign_requested(self) -> None:
        try:
            self.renderer_mgr.request_paint_realign()
            self.statusBar().showMessage("Painter lock normal re-aligned to current hover")
        except Exception:
            log.exception("Failed to request painter re-align")

    def _paint_layer_data(self, name: str) -> dict:
        clean = (str(name or "Paint Layer").strip() or "Paint Layer")
        data = self._paint_layers.get(clean)
        if data is None:
            data = {
                "name": clean,
                "enabled": True,
                "preview_visible": True,
                "settings": {
                    "action": "Replace blocks",
                    "material": "minecraft:iron_ore",
                    "shape": "Sphere",
                    "size_blocks": 8,
                    "strength_pct": 100,
                    "spacing_pct_radius": 25,
                    "falloff": "Constant",
                    "axis_lock": "None",
                    "mirror": "None",
                    "host_only": False,
                    "protect_surface": False,
                    "surface_margin": 6,
                    "align_mode": "Follow hit normal (auto)",
                    "brush_roll_deg": 0.0,
                    "brush_offset_blocks": 0.0,
                },
                "strokes": [],
            }
            self._paint_layers[clean] = data
        return data

    def _ordered_paint_preview_layers(self) -> list[dict]:
        out: list[dict] = []
        try:
            metas = self.layers_panel.layer_stack_metas()
        except Exception:
            metas = []
        seen: set[str] = set()
        for m in metas:
            try:
                mm = dict(m or {})
            except Exception:
                continue
            if str(mm.get("kind", "")).lower() != "paint":
                continue
            name = str(mm.get("name") or "").strip() or "Paint Layer"
            layer = self._paint_layer_data(name)
            layer["enabled"] = bool(mm.get("checked", True))
            layer["preview_visible"] = bool(mm.get("checked", True))
            if not layer.get("preview_visible", True):
                continue
            if name in seen:
                continue
            seen.add(name)
            settings = dict(layer.get("settings") or {})
            strokes = list(layer.get("strokes") or [])
            if not strokes:
                continue
            out.append({
                "name": name,
                "enabled": bool(layer.get("enabled", True)),
                "preview_visible": bool(layer.get("preview_visible", True)),
                "settings": settings,
                "strokes": strokes,
            })
        return out

    def _preview_settings_for_renderer(self, base: dict | None = None) -> dict:
        d = dict(base if base is not None else self.params_panel.preview_settings())
        order = self._preview_layer_order_for_renderer()
        if order:
            d["preview_layer_order"] = order
        else:
            d.pop("preview_layer_order", None)
        paint_layers = self._ordered_paint_preview_layers()
        if paint_layers:
            d["paint_layers"] = paint_layers
        else:
            d.pop("paint_layers", None)
        return d

    def _push_preview_settings_to_renderer(self, base: dict | None = None, invalidate: bool = True) -> dict:
        settings = self._preview_settings_for_renderer(base)
        self.renderer_mgr.set_preview_settings(settings)
        if invalidate and hasattr(self.renderer_mgr, "invalidate_all_meshes"):
            # renderer may no-op if settings equality already triggered invalidation itself.
            pass
        return settings

    def _sync_preview_ui_state(self) -> None:
        try:
            labels = self.params_panel.active_generator_labels()
        except Exception:
            labels = []
        caves = "caves" in labels
        ores = "ores" in labels
        try:
            self.layers_panel.set_generator_preview_state(caves=caves, ores=ores)
        except Exception:
            pass
        if hasattr(self, "_sb_preview"):
            if not labels:
                self._sb_preview.setText("Preview: Off")
            else:
                self._sb_preview.setText("Preview: " + " + ".join(x.title() for x in labels))
            self._sync_workspace_header()

    def _reset_editing_session_for_new_world(self) -> None:
        # Inspect-first reset: loading a world should never appear pre-edited unless a project is loaded.
        try:
            self.params_panel.disable_all_generator_previews(emit=False)
        except Exception:
            pass
        try:
            self._push_preview_settings_to_renderer(self.params_panel.preview_settings())
        except Exception:
            pass
        try:
            self.layers_panel.clear_runtime_layers()
            self.layers_panel.remove_layers_with_prefix("[EditCore]")
        except Exception:
            pass
        try:
            self.edit_core.reset()
        except Exception:
            pass
        try:
            self.edit_core_panel.set_stats(
                "Developer / internal editing-core tools\n"
                "- Hidden by default in the workflow reset build\n"
                "- Use only for backend milestone testing"
            )
        except Exception:
            pass
        self._paint_layer_strokes.clear()
        self._paint_layers.clear()
        self._paint_layer_serial = 1
        self.state.paint_mode_enabled = False
        self._sb_tool.setText("Tool: Navigate")
        self._sync_workspace_header()
        if hasattr(self, "act_paint"):
            self.act_paint.blockSignals(True)
            self.act_paint.setChecked(False)
            self.act_paint.blockSignals(False)
        try:
            if hasattr(self.paint_panel, "paint_enabled"):
                self.paint_panel.paint_enabled.setChecked(False)
        except Exception:
            pass
        try:
            if hasattr(self, "inspector_tabs"):
                self.inspector_tabs.setCurrentWidget(self.params_panel)
                self._set_layer_editor_context(
                    "Scene Tools",
                    "Select a feature/layer on the left to edit it. If no layer is selected, scene cutaway + generator controls are shown."
                )
        except Exception:
            pass
        self._sync_preview_ui_state()
        self.statusBar().showMessage("World loaded in Inspect mode. No edits or generator previews are active.")


    def _next_paint_layer_name(self) -> str:
        while True:
            name = f"Paint Layer {self._paint_layer_serial}"
            self._paint_layer_serial += 1
            if name not in self._paint_layer_strokes:
                return name

    def _focus_generate_tab(self) -> None:
        if hasattr(self, "inspector_tabs"):
            self.inspector_tabs.setCurrentWidget(self.params_panel)
            self._set_layer_editor_context("Generator Settings", "Tune the selected generator preview layer.")
            try:
                for i in range(self.params_panel.tabs.count()):
                    if self.params_panel.tabs.tabText(i).lower().startswith("generate"):
                        self.params_panel.tabs.setCurrentIndex(i)
                        break
            except Exception:
                pass

    def _focus_inspect_tab(self) -> None:
        if hasattr(self, "inspector_tabs"):
            self.inspector_tabs.setCurrentWidget(self.params_panel)
            self._set_layer_editor_context(
                "Scene Tools",
                "Inspect / cutaway settings for the loaded world. View mode is fixed to Surface in this build."
            )
            try:
                for i in range(self.params_panel.tabs.count()):
                    if self.params_panel.tabs.tabText(i).lower().startswith("inspect"):
                        self.params_panel.tabs.setCurrentIndex(i)
                        break
            except Exception:
                pass

    @QtCore.Slot()
    def _show_create_feature_dialog(self) -> None:
        kind = CreateFeatureDialog.get_feature_kind(self, show_dev=self._dev_tools_visible)
        if kind:
            self._create_feature(kind)

    @QtCore.Slot(str)
    def _on_quick_feature_requested(self, kind: str) -> None:
        self._create_feature(kind)

    def _create_feature(self, kind: str) -> None:
        kind = str(kind or "").strip().lower()
        if kind == "paint":
            layer_name = self._next_paint_layer_name()
            self._focus_paint_tab()
            self.paint_panel.select_or_create_layer(layer_name)
            self.paint_panel.paint_enabled.setChecked(True)
            self._paint_layer_data(layer_name)
            self.layers_panel.upsert_paint_layer(layer_name, self._paint_layer_strokes.get(layer_name, 0), select=True)
            self.state.active_paint_layer = layer_name
            self.statusBar().showMessage(
                f"Created '{layer_name}'. Drag in the 3D view to record preview strokes."
            )
            return

        if kind in {"caves", "ores", "caves+ores", "both"}:
            self._focus_generate_tab()
            if kind in {"caves+ores", "both"}:
                self.params_panel.enable_generator_preview("both", subtle=True, emit=True)
                self.statusBar().showMessage("Enabled subtle cave + ore previews (non-destructive)")
                self._sync_preview_ui_state()
                self.layers_panel.select_layer_by_key("gen:caves")
            else:
                self.params_panel.enable_generator_preview(kind, subtle=True, emit=True)
                self.statusBar().showMessage(f"Enabled {kind} preview (non-destructive)")
                self._sync_preview_ui_state()
                self.layers_panel.select_layer_by_key(f"gen:{kind}")
            return

        if kind == "box":
            self._set_dev_tools_visible(True)
            if hasattr(self, "act_dev_tools"):
                self.act_dev_tools.blockSignals(True)
                self.act_dev_tools.setChecked(True)
                self.act_dev_tools.blockSignals(False)
            if hasattr(self, "inspector_tabs") and self._edit_core_tab_index >= 0:
                self.inspector_tabs.setCurrentIndex(self._edit_core_tab_index)
                self._set_layer_editor_context("Advanced Layer (Dev)", "Internal editing-core controls for backend testing.")
            self.statusBar().showMessage("Developer Box Replace tool opened (backend test tool)")
            return


    def _update_edit_area_status(self) -> None:
        b = self.state.edit_area_chunk_bounds
        if not b:
            self._sb_area.setText("Area: not set")
            return
        min_cx, max_cx, min_cz, max_cz = [int(v) for v in b]
        w = max_cx - min_cx + 1
        h = max_cz - min_cz + 1
        tag = "Full" if self.state.edit_area_full_world else f"{w}x{h} ch"
        self._sb_area.setText(f"Area: {tag}")
        self._sync_workspace_header()

    def _apply_project_area_selection(self, bounds: tuple[int, int, int, int], *, full_world: bool = False, recenter: bool = True) -> None:
        min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
        if min_cx > max_cx:
            min_cx, max_cx = max_cx, min_cx
        if min_cz > max_cz:
            min_cz, max_cz = max_cz, min_cz
        self.state.edit_area_chunk_bounds = (min_cx, max_cx, min_cz, max_cz)
        self.state.edit_area_full_world = bool(full_world)
        try:
            self.renderer_mgr.set_edit_area_chunk_bounds(self.state.edit_area_chunk_bounds)
        except Exception:
            log.exception("Failed to apply project area to renderer")
        self._update_edit_area_status()
        if recenter:
            cx = (min_cx + max_cx) // 2
            cz = (min_cz + max_cz) // 2
            try:
                self.renderer_mgr.focus_chunk(cx, cz)
            except Exception:
                pass
        self.statusBar().showMessage(
            f"Project area set: X {min_cx}..{max_cx}, Z {min_cz}..{max_cz} ({max_cx-min_cx+1}x{max_cz-min_cz+1} chunks)"
        )

    def _open_project_area_dialog(self, *, initial_bounds=None) -> bool:
        if self._last_world_index is None:
            QtWidgets.QMessageBox.information(self, "Project Area", "Load a world first.")
            return False
        current = initial_bounds if initial_bounds is not None else self.state.edit_area_chunk_bounds
        sel = ProjectAreaDialog.get_selection(self._last_world_index, current_selection=current, parent=self)
        if sel is None:
            return False
        self._apply_project_area_selection(sel.chunk_bounds, full_world=sel.use_full_world, recenter=True)
        return True

    @QtCore.Slot()
    def edit_project_area(self) -> None:
        self._open_project_area_dialog()

    @QtCore.Slot()
    def show_startup_prompt(self) -> None:
        if self._startup_prompt_shown:
            return
        self._startup_prompt_shown = True
        if self.state.world_path is not None:
            return
        dlg = StartupDialog(self)
        if dlg.exec() != int(QtWidgets.QDialog.DialogCode.Accepted):
            self.statusBar().showMessage("Ready")
            return
        if dlg.choice == 'load_project':
            self.load_project()
        elif dlg.choice == 'open_world':
            self.open_world()

    def _start_world_index_for_path(self, world_path: Path) -> None:
        self.state.world_path = world_path
        self.state.world_name = world_path.name
        self._sb_world.setText(f"World: {world_path.name} (indexing...)")
        self._sync_workspace_header()
        self.statusBar().showMessage(f"Indexing world: {world_path} ...")
        log.info("Opening world: %s", world_path)
        self._indexer.start_index(world_path)

    def _collect_project_payload(self) -> dict:
        selected_meta = self.layers_panel.current_layer_meta() if hasattr(self.layers_panel, "current_layer_meta") else {}
        paint_layers_store = {
            str(name): {
                "name": str(layer.get("name") or name),
                "enabled": bool(layer.get("enabled", True)),
                "preview_visible": bool(layer.get("preview_visible", True)),
                "settings": dict(layer.get("settings") or {}),
                "strokes": list(layer.get("strokes") or []),
            }
            for name, layer in sorted(self._paint_layers.items())
        }
        return {
            'schema': 'worldgeolabs.project.v2',
            'world_path': str(self.state.world_path),
            'world_name': self.state.world_name,
            'chunk_bounds': list(self.state.chunk_bounds) if self.state.chunk_bounds else None,
            'height_range': list(self.state.height_range) if self.state.height_range else None,
            'spawn_chunk': list(self.state.spawn_chunk) if self.state.spawn_chunk else None,
            'edit_area_chunk_bounds': list(self.state.edit_area_chunk_bounds) if self.state.edit_area_chunk_bounds else None,
            'edit_area_full_world': bool(self.state.edit_area_full_world),
            'view_mode': self.state.view_mode,
            'preview_settings': self.params_panel.preview_settings(),
            'view_settings': self.params_panel.view_settings(),
            'paint_settings': self.paint_panel.settings(),
            'paint_layer_serial': int(self._paint_layer_serial),
            'paint_layers_store': paint_layers_store,
            'layer_stack': self.layers_panel.layer_stack_metas(),
            'selected_layer_key': str(selected_meta.get('key') or ''),
            'blocks_visibility': self.blocks_panel.visibility_map(),
            'performance_settings': self.renderer_mgr.get_performance_settings(),
            'dev_tools_visible': bool(self._dev_tools_visible),
        }

    @QtCore.Slot()
    def save_project(self) -> None:
        if self.state.world_path is None or self._last_world_index is None:
            QtWidgets.QMessageBox.information(self, "Save Project", "Open a world first.")
            return
        default_dir = str(self.state.world_path)
        default_name = str((self.state.world_path / f"{self.state.world_name}.mcgeo.json").resolve())
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save WorldGeoLabs Project",
            default_name if Path(default_name).parent.exists() else default_dir,
            "WorldGeoLabs Project (*.mcgeo.json);;JSON (*.json)"
        )
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() == '.json' and not p.name.endswith('.mcgeo.json'):
            pass
        elif p.suffix.lower() != '.json':
            p = p.with_suffix(p.suffix + '.json' if p.suffix else '.mcgeo.json')
        data = self._collect_project_payload()
        try:
            p.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Project", f"Failed to save project\n{e}")
            return
        self.state.project_path = p
        self.statusBar().showMessage(f"Project saved: {p}")
        log.info("Saved project file: %s", p)

    def _restore_project_payload(self, data: dict) -> None:
        payload = dict(data or {})
        try:
            self._set_dev_tools_visible(bool(payload.get("dev_tools_visible", False)))
        except Exception:
            pass
        try:
            preview_settings = payload.get("preview_settings")
            if isinstance(preview_settings, dict):
                self.params_panel.apply_preview_settings(preview_settings, emit=False)
                self._on_preview_settings_changed(self.params_panel.preview_settings())
        except Exception:
            log.exception("Failed to restore preview settings from project")
        try:
            view_settings = payload.get("view_settings")
            if isinstance(view_settings, dict):
                self.params_panel.apply_view_settings(view_settings, emit=False)
                self._on_view_settings_changed(self.params_panel.view_settings())
        except Exception:
            log.exception("Failed to restore view settings from project")
        try:
            perf = payload.get("performance_settings")
            if isinstance(perf, dict) and perf:
                self.renderer_mgr.apply_performance_settings(perf)
        except Exception:
            log.exception("Failed to restore performance settings from project")
        self._paint_layer_strokes.clear()
        self._paint_layers.clear()
        self._paint_layer_serial = int(payload.get("paint_layer_serial", 1) or 1)
        for name, layer in dict(payload.get("paint_layers_store") or {}).items():
            clean = str(name or dict(layer or {}).get("name") or "Paint Layer").strip() or "Paint Layer"
            layer_copy = {
                "name": clean,
                "enabled": bool(dict(layer or {}).get("enabled", True)),
                "preview_visible": bool(dict(layer or {}).get("preview_visible", True)),
                "settings": dict(dict(layer or {}).get("settings") or {}),
                "strokes": list(dict(layer or {}).get("strokes") or []),
            }
            self._paint_layers[clean] = layer_copy
            self._paint_layer_strokes[clean] = len(layer_copy.get("strokes") or [])
            self.paint_panel.select_or_create_layer(clean, select_only=True)
        try:
            layer_stack = payload.get("layer_stack")
            selected_key = str(payload.get("selected_layer_key") or "")
            if isinstance(layer_stack, list) and layer_stack:
                self.layers_panel.restore_layer_stack(layer_stack, selected_key=selected_key or None)
            else:
                for name in self._paint_layers:
                    self.layers_panel.upsert_paint_layer(name, self._paint_layer_strokes.get(name, 0), select=False)
        except Exception:
            log.exception("Failed to restore layer stack from project")
        try:
            paint_settings = payload.get("paint_settings")
            if isinstance(paint_settings, dict):
                self.paint_panel.apply_settings(paint_settings, emit=False)
                self._on_paint_settings_changed(self.paint_panel.settings())
        except Exception:
            log.exception("Failed to restore paint settings from project")
        try:
            block_vis = payload.get("blocks_visibility")
            if isinstance(block_vis, dict) and block_vis:
                self.blocks_panel.set_visibility_map(block_vis, emit=False)
                self._on_blocks_visibility()
        except Exception:
            log.exception("Failed to restore block visibility from project")
        self._push_preview_settings_to_renderer()
        self._sync_layer_header_from_layers_selection()
        self._sync_workspace_header()

    def _build_apply_summary(self) -> dict:
        metas = self.layers_panel.layer_stack_metas()
        paint_layers = sum(1 for m in metas if str(m.get("kind", "")).lower() == "paint")
        generator_layers = sum(1 for m in metas if str(m.get("kind", "")).lower() == "generator")
        visible_paint = sum(1 for _name, layer in self._paint_layers.items() if bool(layer.get("preview_visible", True)) and list(layer.get("strokes") or []))
        stroke_count = sum(len(list(layer.get("strokes") or [])) for layer in self._paint_layers.values())
        area = self.state.edit_area_chunk_bounds
        if area is not None:
            min_cx, max_cx, min_cz, max_cz = area
            area_label = f"chunks {min_cx}..{max_cx}, {min_cz}..{max_cz}"
        else:
            area_label = "Area not selected"
        preview_labels = self.params_panel.active_generator_labels()
        preview_summary = " + ".join(x.title() for x in preview_labels) if preview_labels else "No generator preview layers active"
        if visible_paint:
            preview_summary += f" | {visible_paint} visible paint layer(s) / {stroke_count} stroke(s)"
        warnings = []
        if area is None:
            warnings.append("No project area is selected yet.")
        if not preview_labels and not visible_paint:
            warnings.append("There are no visible preview edits to apply yet.")
        return {
            "world_name": self.state.world_name or "No world loaded",
            "world_path": str(self.state.world_path) if self.state.world_path else "",
            "project_path": str(self.state.project_path) if self.state.project_path else "",
            "area_label": area_label,
            "layer_summary": f"{paint_layers} paint layer(s), {generator_layers} generator preview layer(s)",
            "preview_summary": preview_summary,
            "notes": "Safe write is still review-only in this milestone. The dialog now summarizes destination and session state before the apply pipeline is implemented.",
            "warnings": warnings,
        }

    @QtCore.Slot()
    def load_project(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load WorldGeoLabs Project",
            str(Path.cwd()),
            "WorldGeoLabs Project (*.mcgeo.json);;JSON (*.json)"
        )
        if not path:
            return
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load Project", f"Failed to read project file\n{e}")
            return
        world_path_raw = str(data.get('world_path') or '').strip()
        if not world_path_raw:
            QtWidgets.QMessageBox.critical(self, "Load Project", "Project file is missing world_path.")
            return
        world_path = Path(world_path_raw)
        if not world_path.exists():
            rel = (p.parent / world_path_raw).resolve()
            if rel.exists():
                world_path = rel
        if not world_path.exists():
            QtWidgets.QMessageBox.critical(self, "Load Project", f"World path not found\n{world_path}")
            return
        self.state.project_path = p
        self._pending_project_payload = dict(data)
        self._start_world_index_for_path(world_path)

    @QtCore.Slot()
    def open_world(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Minecraft world folder")
        if not path:
            return
        self._start_world_index_for_path(Path(path))

    @QtCore.Slot(str)
    def _on_index_progress(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _preload_selected_area_regions(self, world_index, bounds: tuple[int, int, int, int]) -> None:
        """Read all region files intersecting the selected edit area before 3D streaming starts.

        This is an upfront warm-cache pass (with progress bar) so the first 3D session feels less
        like it is stalling on cold file reads. It preserves the detailed 2D overview map and does
        not change mesh quality.
        """
        try:
            region_files = region_files_for_chunk_bounds(Path(world_index.region_dir), bounds)
        except Exception:
            log.exception("Failed to enumerate selected-area region files for warmup")
            return
        total = len(region_files)
        if total <= 0:
            return

        dlg = QtWidgets.QProgressDialog("Preparing selected area…", None, 0, total, self)
        dlg.setWindowTitle("Preparing world data")
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.setLabelText(f"Reading {total} region file(s) for the selected edit area…")

        thread = QtCore.QThread(self)
        worker = RegionWarmupWorker(region_files, workers=max(1, (os.cpu_count() or 4)))
        worker.moveToThread(thread)

        loop = QtCore.QEventLoop(self)
        summary_box: dict[str, object] = {}
        error_box: dict[str, str] = {}

        @QtCore.Slot(int, int, str)
        def _on_prog(done: int, total_count: int, message: str) -> None:
            try:
                dlg.setMaximum(max(1, int(total_count)))
                dlg.setValue(max(0, min(int(done), int(total_count))))
                dlg.setLabelText(message)
                self.statusBar().showMessage(message)
            except Exception:
                pass

        @QtCore.Slot(object)
        def _on_done(summary) -> None:
            summary_box["summary"] = summary
            loop.quit()

        @QtCore.Slot(str)
        def _on_failed(err: str) -> None:
            error_box["error"] = str(err)
            loop.quit()

        worker.progress.connect(_on_prog)
        worker.finished.connect(_on_done)
        worker.failed.connect(_on_failed)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)

        thread.start()
        dlg.show()
        loop.exec()

        try:
            thread.quit()
            thread.wait(2000)
        except Exception:
            pass
        try:
            dlg.setValue(dlg.maximum())
            dlg.close()
        except Exception:
            pass

        if "error" in error_box:
            log.warning("Selected-area region warmup failed: %s", error_box["error"])
            self.statusBar().showMessage("World indexed (warmup skipped due to error)")
            return

        summary = summary_box.get("summary")
        if summary is not None:
            try:
                mib = float(getattr(summary, "total_bytes", 0)) / (1024.0 * 1024.0)
                done_files = int(getattr(summary, "done_files", 0))
                total_files = int(getattr(summary, "total_files", 0))
                workers_used = int(getattr(summary, "workers", 0))
                msg = f"Prepared {done_files}/{total_files} region files ({mib:.1f} MiB) using {workers_used} workers"
                self.statusBar().showMessage(msg)
                log.info(msg)
            except Exception:
                pass

    def _preload_selected_area_meshes(self, bounds: tuple[int, int, int, int]) -> None:
        """Blocking selected-area decode/mesh preload with a progress dialog.

        Runs after the world/index + project area are known, but before interactive viewport timers
        resume. This front-loads chunk decode + greedy mesh generation into caches so the first 3D
        view comes up populated and later camera moves are mostly cache hits.
        """
        try:
            min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
            if min_cx > max_cx:
                min_cx, max_cx = max_cx, min_cx
            if min_cz > max_cz:
                min_cz, max_cz = max_cz, min_cz
        except Exception:
            return

        total = max(0, (max_cx - min_cx + 1) * (max_cz - min_cz + 1))
        if total <= 0:
            return

        dlg = QtWidgets.QProgressDialog("Loading selected world area…", "Cancel", 0, total, self)
        dlg.setWindowTitle("Loading world")
        dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.setLabelText("Decoding chunks + building meshes for the selected area…")

        cancelled = {"flag": False}

        def _on_cancel() -> None:
            cancelled["flag"] = True

        dlg.canceled.connect(_on_cancel)
        dlg.show()
        QtWidgets.QApplication.processEvents()

        def _progress(done: int, total_count: int, message: str) -> None:
            try:
                dlg.setMaximum(max(1, int(total_count)))
                dlg.setValue(max(0, min(int(done), int(total_count))))
                dlg.setLabelText(str(message))
                self.statusBar().showMessage(str(message))
            except Exception:
                pass
            QtWidgets.QApplication.processEvents()

        try:
            summary = self.renderer_mgr.preload_selected_area_voxel_cache(
                (min_cx, max_cx, min_cz, max_cz),
                progress_cb=_progress,
                cancel_check=lambda: bool(cancelled.get("flag", False)),
            )
        finally:
            try:
                dlg.setValue(dlg.maximum())
                dlg.close()
            except Exception:
                pass

        try:
            if summary and summary.get("cancelled"):
                msg = (
                    f"World preload canceled at {int(summary.get('done', 0))}/{int(summary.get('total', 0))} chunks. "
                    "Continuing with interactive streaming."
                )
                self.statusBar().showMessage(msg)
                log.warning(msg)
            else:
                staged = dict(summary.get('staged') or {})
                upload = dict(summary.get('gpu_upload') or {})
                msg = (
                    f"Selected area preloaded: {int(summary.get('done', 0))}/{int(summary.get('total', 0))} chunks "
                    f"(built {int(summary.get('built', 0))}, failed {int(summary.get('failed', 0))}, staged {int(staged.get('emitted', 0))}, uploaded {int(upload.get('uploaded', 0))}) "
                    f"using {int(summary.get('workers', 0))} workers"
                )
                self.statusBar().showMessage(msg)
                log.info(msg)
                if upload.get('reason') == 'gl_not_ready':
                    log.warning("Startup preload staged meshes but GL uploads were deferred because the context was not ready yet")
        except Exception:
            pass

    @QtCore.Slot(object)
    def _on_index_done(self, world_index) -> None:
        self.state.chunk_bounds = world_index.chunk_bounds
        self.state.height_range = world_index.height_range
        self.state.spawn_chunk = world_index.spawn_chunk
        self._last_world_index = world_index
        self._anvil_world = AnvilWorld(world_index.world_path)

        pending = self._pending_project_payload or {}
        self._pending_project_payload = None
        project_area_bounds = None
        project_area_full = False
        loaded_from_project = False
        if pending:
            try:
                arr = pending.get('edit_area_chunk_bounds')
                if isinstance(arr, (list, tuple)) and len(arr) == 4:
                    project_area_bounds = tuple(int(v) for v in arr)
                project_area_full = bool(pending.get('edit_area_full_world', False))
                loaded_from_project = True
            except Exception:
                project_area_bounds = None

        if project_area_bounds is None:
            sel = ProjectAreaDialog.get_selection(world_index, current_selection=self.state.edit_area_chunk_bounds, parent=self)
            if sel is None:
                self.statusBar().showMessage("World indexed. Project area selection canceled.")
                self._sb_world.setText(f"World: {self.state.world_name} (indexed; area not selected)")
                self._sync_workspace_header()
                self._update_edit_area_status()
                return
            project_area_bounds = sel.chunk_bounds
            project_area_full = sel.use_full_world

        self.statusBar().showMessage(
            f"Loaded {self.state.world_name} | chunks {self.state.chunk_bounds} | y {self.state.height_range}"
        )
        self._sb_world.setText(
            f"World: {self.state.world_name} | y {self.state.height_range[0]}..{self.state.height_range[1]}"
        )
        self._sync_workspace_header()
        log.info(
            "World indexed: bounds=%s height=%s spawn_chunk=%s",
            self.state.chunk_bounds, self.state.height_range, self.state.spawn_chunk
        )
        # Upfront selected-area warmup: read the intersecting region files first (with progress bar),
        # then start the 3D streaming renderer. This keeps mesh detail unchanged while improving the
        # first-time experience on cold caches.
        try:
            self._preload_selected_area_regions(world_index, project_area_bounds)
        except Exception:
            log.exception("Selected-area warmup failed")

        # Pause viewport streaming/redraw during startup decode/mesh preload so CPU is spent on loading,
        # not incremental rendering. The 3D view resumes once the selected area is prepared.
        try:
            self.renderer_mgr.set_loading_paused(True)
        except Exception:
            pass
        try:
            self.renderer_mgr.set_world_index(world_index)
            self._apply_project_area_selection(project_area_bounds, full_world=project_area_full, recenter=True)
            try:
                self._preload_selected_area_meshes(project_area_bounds)
            except Exception:
                log.exception("Selected-area chunk preload failed")
        finally:
            try:
                self.renderer_mgr.set_loading_paused(False)
            except Exception:
                pass

        self._reset_editing_session_for_new_world()
        if loaded_from_project:
            try:
                self._restore_project_payload(pending)
            except Exception:
                log.exception("Failed to restore project payload after world load")
        if self._perf_dlg is not None:
            self._perf_dlg.refresh_from_renderer()
        if loaded_from_project:
            self.statusBar().showMessage(f"Project loaded: {self.state.project_path or '(unsaved)'}")

    @QtCore.Slot(str)
    def _on_index_failed(self, err: str) -> None:
        self._pending_project_payload = None
        self.statusBar().showMessage("Failed to open world")
        self._sb_world.setText("World: open failed")
        self._sync_workspace_header()
        QtWidgets.QMessageBox.critical(self, "World open failed", err)
        log.exception("World open failed: %s", err)

    @QtCore.Slot()
    def show_performance(self) -> None:
        if self._perf_dlg is None:
            self._perf_dlg = PerformanceDialog(self, self.renderer_mgr)
        self._perf_dlg.show()
        self._perf_dlg.raise_()
        self._perf_dlg.activateWindow()
        self._perf_dlg.refresh_from_renderer()

    @QtCore.Slot()
    def show_apply(self) -> None:
        dlg = ApplyDialog(self, self._build_apply_summary())
        dlg.exec()

    @QtCore.Slot(str)
    def _on_view_mode(self, mode: str) -> None:
        self.state.view_mode = mode
        self._sb_view.setText("View: Surface")
        self._sync_workspace_header()
        self.renderer_mgr.set_view_mode(mode)
        self.renderer_mgr.set_view_settings(self.params_panel.view_settings())

    @QtCore.Slot(object)
    def _on_materials_changed(self, names) -> None:
        try:
            self.blocks_panel.set_blocks(list(names))
        except Exception:
            log.exception("Failed to update blocks list")

    @QtCore.Slot()
    def _on_blocks_visibility(self) -> None:
        vis = self.blocks_panel.visibility_map()
        self.renderer_mgr.set_material_visibility(vis)

    @QtCore.Slot(dict)
    def _on_preview_settings_changed(self, settings: dict) -> None:
        self._sync_preview_ui_state()
        settings2 = self._push_preview_settings_to_renderer(settings)
        if settings2.get("enabled"):
            order = settings2.get("preview_layer_order") or []
            if order:
                pretty = " → ".join("Caves" if x == "gen:caves" else "Ores" if x == "gen:ores" else str(x) for x in order)
                self.statusBar().showMessage(f"Updated non-destructive generator preview (eval order: {pretty})")
            else:
                self.statusBar().showMessage("Updated non-destructive generator preview")
        else:
            self.statusBar().showMessage("Generator previews are off (inspect mode)")

    @QtCore.Slot(dict)
    def _on_view_settings_changed(self, settings: dict) -> None:
        self.renderer_mgr.set_view_settings(settings)
        self.statusBar().showMessage("Updated cutaway / inspection settings")


    @QtCore.Slot(dict)
    def _on_paint_settings_changed(self, settings: dict) -> None:
        self.state.paint_mode_enabled = bool(settings.get("enabled"))
        self.state.active_paint_layer = str(settings.get("active_layer") or "Paint Layer")
        layer = self._paint_layer_data(self.state.active_paint_layer)
        layer["settings"] = dict(settings or {})
        layer["name"] = self.state.active_paint_layer
        self.renderer_mgr.set_paint_settings(settings)
        self._sb_tool.setText("Tool: Painter" if self.state.paint_mode_enabled else "Tool: Navigate")
        self._sync_workspace_header()
        if hasattr(self, "act_paint"):
            self.act_paint.blockSignals(True)
            self.act_paint.setChecked(self.state.paint_mode_enabled)
            self.act_paint.blockSignals(False)
        if self.state.paint_mode_enabled:
            self.layers_panel.upsert_paint_layer(self.state.active_paint_layer, self._paint_layer_strokes.get(self.state.active_paint_layer, 0), select=False)
        self.statusBar().showMessage(
            f"Painter {'enabled' if self.state.paint_mode_enabled else 'disabled'} | "
            f"{settings.get('action','Brush')} | size {settings.get('size_blocks','?')}"
        )

    @QtCore.Slot(bool)
    def _on_toolbar_paint_toggled(self, checked: bool) -> None:
        if hasattr(self, "inspector_tabs"):
            idx = self.inspector_tabs.indexOf(self.paint_panel)
            if idx >= 0:
                self.inspector_tabs.setCurrentIndex(idx)
                self._set_layer_editor_context("Paint Layer", "3D painter settings for the active paint layer.")
        self.paint_panel.paint_enabled.setChecked(bool(checked))

    @QtCore.Slot()
    def _focus_paint_tab(self) -> None:
        if hasattr(self, "inspector_tabs"):
            idx = self.inspector_tabs.indexOf(self.paint_panel)
            if idx >= 0:
                self.inspector_tabs.setCurrentIndex(idx)
                self._set_layer_editor_context("Paint Layer", "3D painter settings for the active paint layer.")
        self.paint_panel.paint_enabled.setChecked(True)

    @QtCore.Slot(str)
    def _on_add_paint_layer(self, name: str) -> None:
        name = (name or "Paint Layer").strip()
        self._paint_layer_data(name)
        self.paint_panel.select_or_create_layer(name, select_only=True)
        self.layers_panel.upsert_paint_layer(name, self._paint_layer_strokes.get(name, 0), select=True)
        self.state.active_paint_layer = name
        self._push_preview_settings_to_renderer()
        self.statusBar().showMessage(f"Added/selected paint layer: {name}")

    @QtCore.Slot()
    def _on_import_model_requested(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "3D model stamps (next milestone)",
            "Planned pipeline:\n"
            "1) Import OBJ/GLB\n"
            "2) Voxelize to stamp volume\n"
            "3) Align/rotate/scale in viewport\n"
            "4) Apply as non-destructive layer"
        )

    @QtCore.Slot(dict)
    def _on_paint_hover_changed(self, info: dict) -> None:
        try:
            self.paint_panel.set_hover_info(info)
        except Exception:
            pass

    @QtCore.Slot(dict)
    def _on_paint_stroke_committed(self, info: dict) -> None:
        layer = str(info.get("active_layer") or self.state.active_paint_layer or "Paint Layer")
        layer_data = self._paint_layer_data(layer)
        self._paint_layer_strokes[layer] = self._paint_layer_strokes.get(layer, 0) + 1
        self.layers_panel.upsert_paint_layer(layer, self._paint_layer_strokes[layer], select=True)
        try:
            self.paint_panel.set_stroke_info(info)
        except Exception:
            pass
        n = int(info.get("point_count", 0))

        stroke_payload = {
            "action": str(info.get("action", "Replace blocks")),
            "material": str(info.get("material", "minecraft:stone")),
            "shape": str(info.get("shape", "Sphere")),
            "size_blocks": int(info.get("size_blocks", 1)),
            "strength_pct": int(info.get("strength_pct", 100)),
            "axis_lock": str(info.get("axis_lock", layer_data.get("settings", {}).get("axis_lock", "None"))),
            "mirror": str(info.get("mirror", layer_data.get("settings", {}).get("mirror", "None"))),
            "host_only": bool(info.get("host_only", layer_data.get("settings", {}).get("host_only", False))),
            "protect_surface": bool(info.get("protect_surface", layer_data.get("settings", {}).get("protect_surface", False))),
            "surface_margin": int(info.get("surface_margin", layer_data.get("settings", {}).get("surface_margin", 6))),
            "points": [[float(p[0]), float(p[1]), float(p[2])] for p in (info.get("points") or [])[:4096] if isinstance(p, (list, tuple)) and len(p) >= 3],
            "bbox": list(info.get("bbox") or []),
        }
        layer_data.setdefault("strokes", []).append(stroke_payload)
        self._push_preview_settings_to_renderer()

        # Dirty-region preview remesh: only invalidate voxel chunks touched by the stroke bbox.
        dirty_chunks = 0
        bbox = info.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 6:
            try:
                brush_size = int(info.get("size_blocks", self.paint_panel.settings().get("size_blocks", 1)))
            except Exception:
                brush_size = 1
            pad = max(1, brush_size)
            try:
                x0, y0, z0, x1, y1, z1 = [int(v) for v in bbox]
                mnx, mxx = sorted((x0, x1))
                mnz, mxz = sorted((z0, z1))
                mnx -= pad; mxx += pad
                mnz -= pad; mxz += pad
                cminx = mnx // 16
                cmaxx = mxx // 16
                cminz = mnz // 16
                cmaxz = mxz // 16
                dirty_chunks = max(0, (cmaxx - cminx + 1)) * max(0, (cmaxz - cminz + 1))
                self.renderer_mgr.invalidate_preview_block_box((x0, y0, z0, x1, y1, z1), padding_blocks=pad)
            except Exception:
                log.exception("Failed dirty-region preview invalidation for paint stroke")

        log.info("Paint stroke recorded: layer=%s points=%d action=%s dirty_chunks=%s", layer, n, info.get("action"), dirty_chunks or 0)
        if dirty_chunks > 0:
            self.statusBar().showMessage(
                f"Recorded paint preview stroke on '{layer}' ({n} samples) | queued local remesh for ~{dirty_chunks} chunk(s)"
            )
        else:
            self.statusBar().showMessage(f"Recorded paint preview stroke on '{layer}' ({n} samples)")


    @QtCore.Slot(object)
    def _on_layer_selected(self, meta: object) -> None:
        try:
            m = dict(meta or {})
        except Exception:
            m = {}
        self._sync_layer_header_from_layers_selection()
        kind = str(m.get("kind", "")).lower()
        key = str(m.get("key", ""))
        if not m:
            self._focus_inspect_tab()
            return
        if kind == "paint":
            name = str(m.get("name") or m.get("label") or "Paint Layer")
            self._focus_paint_tab()
            try:
                self._paint_layer_data(name)
                self.paint_panel.select_or_create_layer(name, select_only=True)
            except Exception:
                pass
            self.state.active_paint_layer = name
            self._set_layer_editor_context(f"Edit Paint Layer: {name}", "Use the painter to add/remove/recolor preview strokes on this layer.")
            self.statusBar().showMessage(f"Selected paint layer: {name}")
            return
        if kind == "generator":
            self._focus_generate_tab()
            gk = str(m.get("generator_kind", "")).lower()
            self._set_layer_editor_context(
                f"Edit { (gk or 'generator').title() } Preview",
                "Non-destructive preview settings. Disable or delete the layer to remove the preview."
            )
            self.statusBar().showMessage(f"Selected {gk or 'generator'} preview layer")
            return
        if kind == "editcore":
            if self._dev_tools_visible and hasattr(self, "inspector_tabs") and self._edit_core_tab_index >= 0:
                self.inspector_tabs.setCurrentIndex(self._edit_core_tab_index)
                self._set_layer_editor_context("Advanced Layer (Dev)", "Internal editing-core controls for backend testing.")
            self.statusBar().showMessage("Selected advanced box-replace layer (developer tool)")
            return

    @QtCore.Slot(object)
    def _on_layer_edit_requested(self, meta: object) -> None:
        self._on_layer_selected(meta)

    @QtCore.Slot(object)
    def _on_layer_remove_requested(self, meta: object) -> None:
        try:
            m = dict(meta or {})
        except Exception:
            m = {}
        kind = str(m.get("kind", "")).lower()
        if kind == "generator":
            gk = str(m.get("generator_kind", "")).lower()
            if gk == "caves":
                self.params_panel.caves_enabled.setChecked(False)
                self.params_panel.emit_preview_settings()
            elif gk == "ores":
                self.params_panel.ores_enabled.setChecked(False)
                self.params_panel.emit_preview_settings()
            self._sync_preview_ui_state()
            self.statusBar().showMessage(f"Removed {gk or 'generator'} preview layer")
            return
        if kind == "paint":
            name = str(m.get("name") or "")
            self._paint_layer_strokes.pop(name, None)
            self._paint_layers.pop(name, None)
            self._push_preview_settings_to_renderer()
            self.statusBar().showMessage(f"Removed paint layer '{name}'")
            return
        if kind == "editcore":
            self.statusBar().showMessage("Removed advanced box-replace layer entry")
            return

    @QtCore.Slot(object)
    def _on_layer_duplicate_requested(self, meta: object) -> None:
        try:
            m = dict(meta or {})
        except Exception:
            m = {}
        kind = str(m.get("kind", "")).lower()
        if kind == "paint":
            base = str(m.get("name") or "Paint Layer").strip() or "Paint Layer"
            copy_name = base + " Copy"
            n = 2
            while copy_name in self._paint_layer_strokes:
                copy_name = f"{base} Copy {n}"
                n += 1
            self._paint_layer_strokes[copy_name] = 0
            src_layer = self._paint_layer_data(base)
            copied = {"name": copy_name, "enabled": True, "preview_visible": True, "settings": dict(src_layer.get("settings") or {}), "strokes": [dict(s) for s in (src_layer.get("strokes") or [])]}
            self._paint_layers[copy_name] = copied
            self._paint_layer_strokes[copy_name] = len(copied.get("strokes") or [])
            self.paint_panel.select_or_create_layer(copy_name, select_only=True)
            self.layers_panel.upsert_paint_layer(copy_name, self._paint_layer_strokes.get(copy_name, 0), select=True)
            self._push_preview_settings_to_renderer()
            self.statusBar().showMessage(f"Duplicated paint layer as '{copy_name}'")
            return
        if kind == "generator":
            self.statusBar().showMessage("Generator previews are singleton layers right now (duplicate not needed)")
            return
        if kind == "editcore":
            self.statusBar().showMessage("Advanced box replace duplication is not implemented yet")
            return

    @QtCore.Slot(object, str)
    def _on_layer_renamed(self, meta: object, new_label: str) -> None:
        try:
            m = dict(meta or {})
        except Exception:
            m = {}
        kind = str(m.get("kind", "")).lower()
        if kind == "paint":
            old_name = str(m.get("name") or "").strip()
            # Expect labels like "Paint • Name  (N strokes)" -> derive display name back out.
            name = str(new_label or "").strip()
            if name.lower().startswith("paint •"):
                name = name.split("•", 1)[1].strip()
            if "  (" in name:
                name = name.split("  (", 1)[0].rstrip()
            name = name or "Paint Layer"
            if old_name and old_name != name:
                self._paint_layer_strokes[name] = self._paint_layer_strokes.pop(old_name, 0)
                layer_data = self._paint_layers.pop(old_name, None)
                if layer_data is not None:
                    layer_data["name"] = name
                    self._paint_layers[name] = layer_data
                try:
                    self.paint_panel.rename_layer_entry(old_name, name)
                except Exception:
                    pass
                self.state.active_paint_layer = name
                # normalize layer row label back to styled label
                self.layers_panel.upsert_paint_layer(name, self._paint_layer_strokes.get(name, 0), select=True)
                self._push_preview_settings_to_renderer()
                self.statusBar().showMessage(f"Renamed paint layer to '{name}'")
            return
        if kind == "generator":
            # Preserve canonical labels to avoid confusion; revert on next sync.
            self._sync_preview_ui_state()
            self.statusBar().showMessage("Generator layer names are fixed in this milestone")
            return

    @QtCore.Slot(object, bool)
    def _on_layer_visibility_changed(self, meta: object, visible: bool) -> None:
        try:
            m = dict(meta or {})
        except Exception:
            m = {}
        kind = str(m.get("kind", "")).lower()
        if kind == "generator":
            gk = str(m.get("generator_kind", "")).lower()
            if gk == "caves" and bool(self.params_panel.caves_enabled.isChecked()) != bool(visible):
                self.params_panel.caves_enabled.setChecked(bool(visible))
                self.params_panel.emit_preview_settings()
            elif gk == "ores" and bool(self.params_panel.ores_enabled.isChecked()) != bool(visible):
                self.params_panel.ores_enabled.setChecked(bool(visible))
                self.params_panel.emit_preview_settings()
            self._sync_preview_ui_state()
            settings = self._push_preview_settings_to_renderer(self.params_panel.preview_settings())
            order = settings.get("preview_layer_order") or []
            suffix = ""
            if order:
                pretty = " → ".join("Caves" if x == "gen:caves" else "Ores" if x == "gen:ores" else str(x) for x in order)
                suffix = f" | eval order: {pretty}"
            self.statusBar().showMessage(f"{'Enabled' if visible else 'Hid'} {gk or 'generator'} preview layer{suffix}")
            return
        if kind == "paint":
            name = str(m.get("name") or "Paint Layer")
            layer = self._paint_layer_data(name)
            layer["enabled"] = bool(visible)
            layer["preview_visible"] = bool(visible)
            self._push_preview_settings_to_renderer()
            self.statusBar().showMessage(
                f"{'Showing' if visible else 'Hiding'} paint layer '{name}' preview"
            )
            return
        if kind == "editcore":
            self.statusBar().showMessage(
                f"{'Enabled' if visible else 'Disabled'} advanced box-replace layer entry"
            )

    @QtCore.Slot()
    def _on_layer_reordered(self) -> None:
        # Wire visible generator order into renderer preview evaluation (caves/ores for now).
        settings = self._push_preview_settings_to_renderer(self.params_panel.preview_settings())
        order = settings.get("preview_layer_order") or []
        if order:
            pretty = " → ".join("Caves" if x == "gen:caves" else "Ores" if x == "gen:ores" else str(x) for x in order)
            self.statusBar().showMessage(f"Layer order updated (preview eval order: {pretty})")
        else:
            self.statusBar().showMessage("Layer order updated")
        self._push_preview_settings_to_renderer()

    @QtCore.Slot(dict)
    def _on_edit_core_box_params_changed(self, params: dict) -> None:
        self._edit_core_box_params = dict(params or {})

    @QtCore.Slot()
    def _on_edit_core_add_box_layer(self) -> None:
        params = self.edit_core_panel.params()
        layer = self.edit_core.add_or_replace_box_layer(params)
        self.layers_panel.ensure_named_layer(
            f"Box Replace • {layer.name}",
            checked=layer.enabled,
            top=True,
            meta={"kind": "editcore", "key": "editcore:box_replace", "name": layer.name},
            select=True,
        )
        self.edit_core_panel.append_stats(
            f"Layer loaded: {layer.name} | mode={layer.combine_mode} | "
            f"box=({layer.min_x},{layer.min_y},{layer.min_z})..({layer.max_x},{layer.max_y},{layer.max_z})"
        )
        self.statusBar().showMessage(f"Editing Core: configured '{layer.name}'")

    def _make_edit_eval_chunks(self) -> list:
        # Prefer a real decoded chunk near spawn if available; otherwise use demo adapter.
        h = self.state.height_range or (-64, 320)
        min_y, max_y = int(h[0]), int(h[1])
        spawn = self.state.spawn_chunk or (0, 0)
        cx, cz = int(spawn[0]), int(spawn[1])

        if self._anvil_world is not None:
            try:
                model = self._anvil_world.read_chunk(cx, cz)
                if model is not None:
                    class _ChunkModelAdapter:
                        def __init__(self, m, min_y_, max_y_):
                            self._m = m
                            self.chunk_x = int(m.cx)
                            self.chunk_z = int(m.cz)
                            self.min_y = int(min_y_)
                            self.max_y = int(max_y_)

                        def get_block(self, x: int, y: int, z: int) -> str:
                            return self._m.get_block(x, y, z)

                    return [_ChunkModelAdapter(model, min_y, max_y)]
            except Exception:
                log.exception("Editing Core: failed to decode real chunk for preview; using demo chunk")
        return [DemoChunkAdapter(cx, cz, min_y=min_y, max_y=max_y)]

    def _run_edit_core_eval(self, apply_demo: bool = False) -> None:
        params = self.edit_core_panel.params()
        layer = self.edit_core.add_or_replace_box_layer(params)
        chunks = self._make_edit_eval_chunks()
        deltas, stats = self.edit_core.preview_chunks(chunks)
        dirty = sorted(self.edit_core.consume_dirty_chunks())
        mode_label = "Apply (demo)" if apply_demo else "Preview"
        source_label = "real chunk" if chunks and chunks[0].__class__.__name__ != "DemoChunkAdapter" else "demo chunk"

        lines = [
            f"{mode_label}: layer={layer.name}",
            f"Source: {source_label} @ chunk ({chunks[0].chunk_x}, {chunks[0].chunk_z})",
            f"Changed chunks: {stats.get('changed_chunks', 0)}",
            f"Changed blocks: {stats.get('changed_blocks', 0)}",
            f"Evaluated layers: {stats.get('evaluated_layers', 0)}",
            f"Stack version: {stats.get('stack_version', '?')}",
            f"Dirty chunks (for future remesh injection): {dirty[:8]}{' ...' if len(dirty) > 8 else ''}",
        ]
        if deltas:
            d0 = deltas[0]
            lines.append(f"First delta chunk: ({d0.chunk_x}, {d0.chunk_z}) with {d0.changed_block_count} changes")
        else:
            lines.append("No changes produced (check box bounds/selector/target chunk).")
        self.edit_core_panel.set_stats("\n".join(lines))

        log.info(
            "Editing Core %s evaluated: changed_chunks=%s changed_blocks=%s dirty=%s source=%s",
            "apply-demo" if apply_demo else "preview",
            stats.get("changed_chunks"),
            stats.get("changed_blocks"),
            dirty,
            source_label,
        )
        if apply_demo:
            self.statusBar().showMessage(
                "Editing Core Apply (demo): same evaluator path executed (no world writes yet)"
            )
        else:
            self.statusBar().showMessage(
                "Editing Core Preview evaluated (stats only; mesh injection to renderer is next milestone)"
            )

    @QtCore.Slot()
    def _on_edit_core_preview(self) -> None:
        self._run_edit_core_eval(apply_demo=False)

    @QtCore.Slot()
    def _on_edit_core_apply_demo(self) -> None:
        self._run_edit_core_eval(apply_demo=True)

    @QtCore.Slot()
    def _refresh_status_snapshot(self) -> None:
        try:
            snap = self.renderer_mgr.get_performance_snapshot() or {}
        except Exception:
            return
        fps = snap.get("fps")
        resident = snap.get("resident_chunks")
        inflight = snap.get("inflight")
        if fps is None and resident is None:
            return
        fps_txt = "--" if fps is None else str(fps)
        res_txt = "--" if resident is None else str(resident)
        inflight_txt = "" if inflight is None else f" | Inflight: {inflight}"
        self._sb_perf.setText(f"FPS: {fps_txt} | Resident: {res_txt}{inflight_txt}")
        self._sync_workspace_header()
