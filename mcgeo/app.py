from __future__ import annotations
import logging
from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtGui

from .core.logging_setup import setup_logging
from .ui.main_window import MainWindow

log = logging.getLogger("mcgeo")


def _apply_app_theme(app: QtWidgets.QApplication) -> None:
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(25, 28, 33))
    pal.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(235, 239, 244))
    pal.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(19, 22, 27))
    pal.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(31, 35, 42))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor(252, 252, 252))
    pal.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor(20, 20, 20))
    pal.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(232, 237, 243))
    pal.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(39, 43, 50))
    pal.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(238, 241, 245))
    pal.setColor(QtGui.QPalette.ColorRole.BrightText, QtGui.QColor(255, 108, 108))
    pal.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(77, 136, 255))
    pal.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(255, 255, 255))
    app.setPalette(pal)

    app.setStyleSheet("""
    QWidget {
        font-size: 11px;
    }
    QMainWindow::separator {
        background: #4a5160;
        width: 1px;
        height: 1px;
    }
    QDockWidget {
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }
    QDockWidget::title {
        background: #272c34;
        color: #edf2f8;
        border-bottom: 1px solid #3b4350;
        padding: 7px 10px;
        font-weight: 600;
    }
    QToolBar {
        spacing: 7px;
        padding: 5px 8px;
        border-bottom: 1px solid #39414e;
        background: #242930;
    }
    QToolBar QToolButton {
        padding: 6px 10px;
        border: 1px solid transparent;
        border-radius: 8px;
    }
    QToolBar QToolButton:hover {
        background: #2f3641;
        border-color: #4d586a;
    }
    QToolBar QToolButton:checked {
        background: #355184;
        border-color: #5c7fc4;
    }
    QStatusBar {
        border-top: 1px solid #39414e;
        background: #20242c;
    }
    QMenuBar {
        background: #232830;
        color: #eef2f8;
    }
    QMenuBar::item {
        padding: 5px 8px;
        border-radius: 6px;
        margin: 2px;
    }
    QMenuBar::item:selected {
        background: #343c49;
    }
    QMenu {
        background: #252b34;
        color: #eef2f8;
        border: 1px solid #48505d;
        padding: 6px;
    }
    QMenu::item {
        padding: 6px 18px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background: #3b4452;
    }
    QLabel#PanelTitle {
        font-weight: 700;
        font-size: 12px;
        color: #eef1f5;
    }
    QLabel#WorkspaceTitle {
        font-weight: 700;
        font-size: 15px;
        color: #f4f7fb;
    }
    QLabel#SubtleHint {
        color: #acb7c7;
    }
    QLabel#StatusPill, QLabel#HeaderPill {
        background: #2e353f;
        color: #e9eef6;
        border: 1px solid #465063;
        border-radius: 10px;
        padding: 3px 9px;
        margin-left: 4px;
    }
    QFrame#WorkspaceHeader, QFrame#LayerHeaderCard, QFrame#ViewportCard, QFrame#AdvancedPanel {
        border: 1px solid #3a4250;
        border-radius: 12px;
        background: #232830;
    }
    QFrame#ViewportCard {
        background: #16191f;
    }
    QScrollArea {
        border: none;
        background: transparent;
    }
    QGroupBox {
        border: 1px solid #414957;
        border-radius: 10px;
        margin-top: 12px;
        padding-top: 8px;
        background: #262c34;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: #dde3ec;
        font-weight: 600;
    }
    QTabWidget::pane {
        border: 1px solid #3f4654;
        border-radius: 10px;
        background: #262b32;
        top: -1px;
    }
    QTabBar::tab {
        background: #2a2e35;
        color: #cbd4e1;
        border: 1px solid #414855;
        border-bottom: none;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        padding: 7px 12px;
        margin-right: 4px;
    }
    QTabBar::tab:selected {
        background: #343a44;
        color: #ffffff;
    }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget {
        background: #1f242b;
        color: #edf2f8;
        border: 1px solid #4b5668;
        border-radius: 8px;
        padding: 5px 6px;
        selection-background-color: #4d7cff;
    }
    QListWidget::item {
        padding: 4px 6px;
        border-radius: 6px;
    }
    QListWidget::item:selected {
        background: #33425c;
        color: #ffffff;
    }
    QPushButton, QToolButton {
        background: #323946;
        color: #eef2f8;
        border: 1px solid #4c5769;
        border-radius: 8px;
        padding: 6px 10px;
    }
    QPushButton:hover, QToolButton:hover {
        background: #3b4351;
        border-color: #627088;
    }
    QPushButton:pressed, QToolButton:pressed {
        background: #2c323d;
    }
    QPushButton#PrimaryButton {
        background: #3767c8;
        border-color: #5d87dd;
        font-weight: 600;
    }
    QPushButton#PrimaryButton:hover {
        background: #4474d6;
    }
    QCheckBox, QLabel {
        color: #e7edf6;
    }
    QHeaderView::section {
        background: #2a303a;
        color: #e8edf5;
        border: none;
        border-bottom: 1px solid #414957;
        padding: 6px;
    }
    QToolTip {
        background: #f1f4f8;
        color: #1b1e23;
        border: 1px solid #b8c1d1;
        padding: 4px 6px;
    }
    """)


def main() -> int:
    # High DPI friendliness
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    setup_logging(log_dir=Path.cwd() / "logs", level=logging.INFO)

    app = QtWidgets.QApplication([])
    app.setApplicationName("WorldGeoLabs")
    app.setOrganizationName("WorldGeoLabs")
    _apply_app_theme(app)

    w = MainWindow()
    w.resize(1500, 900)
    w.show()
    QtCore.QTimer.singleShot(0, w.show_startup_prompt)

    log.info("WorldGeoLabs started")
    return app.exec()
