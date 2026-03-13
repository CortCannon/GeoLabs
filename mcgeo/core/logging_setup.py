from __future__ import annotations
import logging
import sys
from pathlib import Path

def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> None:
    """Configure root logging with console + optional file handler.

    The UI attaches its own handler to show logs in-app.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if reloaded
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_dir / "worldgeolabs.log"), encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
