from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class InvalidationTracker:
    dirty_chunks: set[tuple[int, int]] = field(default_factory=set)

    def mark_chunks(self, coords: list[tuple[int, int]]) -> None:
        self.dirty_chunks.update(coords)

    def consume_all(self) -> set[tuple[int, int]]:
        out = set(self.dirty_chunks)
        self.dirty_chunks.clear()
        return out
