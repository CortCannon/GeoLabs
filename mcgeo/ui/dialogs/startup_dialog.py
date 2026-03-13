from __future__ import annotations

from PySide6 import QtWidgets, QtCore


class StartupDialog(QtWidgets.QDialog):
    """Simple startup prompt: open project or open world."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Welcome to WorldGeoLabs')
        self.setModal(True)
        self.resize(520, 260)
        self.choice = None  # 'load_project' | 'open_world' | None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QtWidgets.QLabel('Start a session')
        title.setObjectName('PanelTitle')
        layout.addWidget(title)

        intro = QtWidgets.QLabel(
            'Open a saved WorldGeoLabs project, or choose a Minecraft world and then select the edit area on a 2D overview map.'
        )
        intro.setWordWrap(True)
        intro.setObjectName('SubtleHint')
        layout.addWidget(intro)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        layout.addLayout(grid)

        self.btn_load_project = QtWidgets.QPushButton('Load Project…')
        self.btn_load_project.setMinimumHeight(52)
        self.btn_load_project.clicked.connect(self._choose_project)

        self.btn_open_world = QtWidgets.QPushButton('Open World…')
        self.btn_open_world.setMinimumHeight(52)
        self.btn_open_world.clicked.connect(self._choose_world)

        self.btn_cancel = QtWidgets.QPushButton('Close Prompt')
        self.btn_cancel.clicked.connect(self.reject)

        grid.addWidget(self.btn_load_project, 0, 0)
        grid.addWidget(self.btn_open_world, 0, 1)
        grid.addWidget(self.btn_cancel, 1, 0, 1, 2)

        note = QtWidgets.QLabel(
            'Tip: after a world loads, you can reopen Project Area from the toolbar to change the area later.'
        )
        note.setWordWrap(True)
        note.setObjectName('SubtleHint')
        layout.addWidget(note)
        layout.addStretch(1)

    @QtCore.Slot()
    def _choose_project(self) -> None:
        self.choice = 'load_project'
        self.accept()

    @QtCore.Slot()
    def _choose_world(self) -> None:
        self.choice = 'open_world'
        self.accept()
