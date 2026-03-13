from __future__ import annotations
import logging
import re
import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List

from PySide6 import QtCore

from .nbt import read_nbt, TAG_Compound

log = logging.getLogger("mcgeo.world.open")

REGION_RE = re.compile(r"r\.(?P<rx>-?\d+)\.(?P<rz>-?\d+)\.mca$")


@dataclass(frozen=True)
class WorldIndex:
    world_path: Path
    region_dir: Path
    chunk_bounds: Tuple[int, int, int, int]     # min_cx,max_cx,min_cz,max_cz
    height_range: Tuple[int, int]               # min_y,max_y
    spawn_chunk: Tuple[int, int]                # cx,cz
    spawn_block: Tuple[int, int, int]           # x,y,z


class WorldIndexer(QtCore.QObject):
    progress = QtCore.Signal(str)
    finished = QtCore.Signal(object)  # WorldIndex
    failed = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QtCore.QThread | None = None
        self._worker: _IndexWorker | None = None  # keep a strong ref (Qt thread worker GC bug)

    def start_index(self, world_path: Path) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1000)

        self._thread = QtCore.QThread()
        self._worker = _IndexWorker(world_path)
        self._worker.moveToThread(self._thread)

        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self.finished)
        self._worker.failed.connect(self._thread.quit)
        self._worker.failed.connect(self.failed)

        # cleanup refs when thread ends
        self._thread.finished.connect(self._on_thread_finished)

        self._thread.started.connect(self._worker.run)
        self._thread.start()

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        self._worker = None


class _IndexWorker(QtCore.QObject):
    progress = QtCore.Signal(str)
    finished = QtCore.Signal(object)  # WorldIndex
    failed = QtCore.Signal(str)

    def __init__(self, world_path: Path) -> None:
        super().__init__()
        self.world_path = world_path

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.progress.emit("Scanning world…")

            region_dir = self.world_path / "region"
            if not region_dir.exists():
                raise RuntimeError("Missing 'region' folder. Is this a Java (Anvil) world?")

            min_rx = min_rz = 10**9
            max_rx = max_rz = -10**9
            region_files: List[Path] = []

            for p in region_dir.glob("r.*.*.mca"):
                m = REGION_RE.fullmatch(p.name)
                if not m:
                    continue
                rx = int(m.group("rx"))
                rz = int(m.group("rz"))
                min_rx = min(min_rx, rx)
                max_rx = max(max_rx, rx)
                min_rz = min(min_rz, rz)
                max_rz = max(max_rz, rz)
                region_files.append(p)

            if not region_files:
                raise RuntimeError("No region files found in 'region' folder.")

            self.progress.emit(f"Found {len(region_files)} region files. Reading level.dat…")

            # Approximate chunk bounds from region grid
            min_cx = min_rx * 32
            max_cx = max_rx * 32 + 31
            min_cz = min_rz * 32
            max_cz = max_rz * 32 + 31

            spawn_chunk, spawn_block = self._read_spawn()

            # 1.21+ defaults; custom heights will be refined later by chunk scans
            min_y, max_y = -64, 320

            wi = WorldIndex(
                world_path=self.world_path,
                region_dir=region_dir,
                chunk_bounds=(min_cx, max_cx, min_cz, max_cz),
                height_range=(min_y, max_y),
                spawn_chunk=spawn_chunk,
                spawn_block=spawn_block,
            )
            self.finished.emit(wi)
        except Exception as e:
            log.exception("World index failed")
            self.failed.emit(str(e))

    def _read_spawn(self) -> Tuple[Tuple[int, int], Tuple[int, int, int]]:
        level_dat = self.world_path / "level.dat"
        if not level_dat.exists():
            return ((0, 0), (0, 80, 0))
        try:
            raw = level_dat.read_bytes()
            # Java level.dat is gzipped NBT
            data = gzip.decompress(raw)
            root = read_nbt(data).value
            data_tag = root.get("Data")
            if not data_tag or data_tag.tag_id != TAG_Compound:
                return ((0, 0), (0, 80, 0))
            d = data_tag.value
            sx = int(d.get("SpawnX").value) if d.get("SpawnX") else 0
            sy = int(d.get("SpawnY").value) if d.get("SpawnY") else 80
            sz = int(d.get("SpawnZ").value) if d.get("SpawnZ") else 0
            return ((sx // 16, sz // 16), (sx, sy, sz))
        except Exception:
            return ((0, 0), (0, 80, 0))
