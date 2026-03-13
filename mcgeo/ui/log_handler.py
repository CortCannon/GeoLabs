from __future__ import annotations
import logging
from PySide6 import QtCore

class QtLogHandler(QtCore.QObject, logging.Handler):
    message = QtCore.Signal(str)

    def __init__(self, level: int = logging.INFO) -> None:
        QtCore.QObject.__init__(self)
        logging.Handler.__init__(self, level=level)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.message.emit(msg)
