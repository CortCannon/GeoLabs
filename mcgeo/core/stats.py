from __future__ import annotations
from dataclasses import dataclass
import time

@dataclass
class LiveStats:
    fps: float = 0.0
    frame_time_ms: float = 0.0
    resident_chunks: int = 0
    inflight_builds: int = 0
    avg_build_ms: float = 0.0
    cache_hit_rate: float = 0.0

class FPSCounter:
    def __init__(self) -> None:
        self._last = time.perf_counter()
        self._acc = 0.0
        self._frames = 0
        self.fps = 0.0

    def tick(self) -> float:
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        self._acc += dt
        self._frames += 1
        if self._acc >= 0.5:
            self.fps = self._frames / self._acc
            self._acc = 0.0
            self._frames = 0
        return dt
