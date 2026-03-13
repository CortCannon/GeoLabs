from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore


class LogPanel(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Logs")

        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(5000)
        self._text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas, 'Courier New', monospace; font-size: 11px; }"
        )

        clear_btn = QtWidgets.QToolButton(text="Clear")
        clear_btn.clicked.connect(self._text.clear)

        copy_btn = QtWidgets.QToolButton(text="Copy all")
        copy_btn.clicked.connect(self._copy_all)

        self._autoscroll = QtWidgets.QCheckBox("Auto-scroll")
        self._autoscroll.setChecked(True)

        self._count_lbl = QtWidgets.QLabel("0 lines")
        self._count_lbl.setObjectName("SubtleHint")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("Logs")
        lbl.setObjectName("PanelTitle")
        header.addWidget(lbl)
        header.addStretch(1)
        header.addWidget(self._count_lbl)
        header.addWidget(self._autoscroll)
        header.addWidget(copy_btn)
        header.addWidget(clear_btn)
        layout.addLayout(header)
        layout.addWidget(self._text, 1)

    @QtCore.Slot(str)
    def append(self, line: str) -> None:
        self._text.appendPlainText(line)
        blocks = max(0, self._text.blockCount() - 1)
        self._count_lbl.setText(f"{blocks} lines")
        if self._autoscroll.isChecked():
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    @QtCore.Slot()
    def _copy_all(self) -> None:
        text = self._text.toPlainText()
        QtGui.QGuiApplication.clipboard().setText(text)
