from __future__ import annotations

import concurrent.futures as cf
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PySide6 import QtCore

log = logging.getLogger("mcgeo.world.warmup")


def _parse_region_coords(name: str):
    parts = name.split('.')
    if len(parts) != 4 or parts[0] != 'r' or parts[3] != 'mca':
        return None
    try:
        return int(parts[1]), int(parts[2])
    except Exception:
        return None


def region_files_for_chunk_bounds(region_dir: Path, bounds: tuple[int, int, int, int]) -> list[Path]:
    min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
    if min_cx > max_cx:
        min_cx, max_cx = max_cx, min_cx
    if min_cz > max_cz:
        min_cz, max_cz = max_cz, min_cz
    min_rx = min_cx // 32
    max_rx = max_cx // 32
    min_rz = min_cz // 32
    max_rz = max_cz // 32

    out: list[tuple[int,int,Path]] = []
    for p in region_dir.glob('r.*.*.mca'):
        coords = _parse_region_coords(p.name)
        if coords is None:
            continue
        rx, rz = coords
        if min_rx <= rx <= max_rx and min_rz <= rz <= max_rz:
            out.append((rz, rx, p))
    out.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in out]


def _warm_region_file(path_str: str) -> tuple[int, int, int, str]:
    p = Path(path_str)
    data = p.read_bytes()
    size = len(data)
    header = data[:4096]
    present = 0
    n = len(header) // 4
    for i in range(n):
        j = i * 4
        if header[j] or header[j+1] or header[j+2] or header[j+3]:
            present += 1
    # tiny deterministic checksum to ensure bytes are actually touched in memory
    checksum = 0
    step = 4096 if size > 0 else 1
    for off in range(0, size, step):
        checksum = (checksum * 131 + data[off]) & 0xFFFFFFFF
    return size, present, checksum, p.name


@dataclass
class RegionWarmupSummary:
    total_files: int
    done_files: int
    total_bytes: int
    present_chunk_slots: int
    workers: int


class RegionWarmupWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int, str)   # done,total,message
    finished = QtCore.Signal(object)          # RegionWarmupSummary
    failed = QtCore.Signal(str)

    def __init__(self, region_files: Iterable[Path], workers: int = 0) -> None:
        super().__init__()
        self._files = [Path(p) for p in region_files]
        self._workers = max(1, int(workers or (os.cpu_count() or 4)))

    @QtCore.Slot()
    def run(self) -> None:
        try:
            files = self._files
            total = len(files)
            if total <= 0:
                self.finished.emit(RegionWarmupSummary(0, 0, 0, 0, self._workers))
                return

            max_workers = min(self._workers, max(1, total))
            bytes_total = 0
            present_total = 0
            done = 0
            self.progress.emit(0, total, f"Preparing {total} region file(s)…")
            with cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='mcgeo-warm') as ex:
                futs = [ex.submit(_warm_region_file, str(p)) for p in files]
                for fut in cf.as_completed(futs):
                    size, present, _checksum, name = fut.result()
                    done += 1
                    bytes_total += int(size)
                    present_total += int(present)
                    self.progress.emit(done, total, f"Reading region {done}/{total}: {name}")

            self.finished.emit(
                RegionWarmupSummary(
                    total_files=total,
                    done_files=done,
                    total_bytes=bytes_total,
                    present_chunk_slots=present_total,
                    workers=max_workers,
                )
            )
        except Exception as e:
            log.exception("Region warmup failed")
            self.failed.emit(str(e))
