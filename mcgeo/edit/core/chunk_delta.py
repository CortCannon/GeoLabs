from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(slots=True)
class VoxelChange:
    x: int
    y: int
    z: int
    old_block: str
    new_block: str
    source_layer_id: str
    source_layer_name: str


@dataclass(slots=True)
class ChunkDelta:
    chunk_x: int
    chunk_z: int
    changes: list[VoxelChange] = field(default_factory=list)

    def add(self, change: VoxelChange) -> None:
        self.changes.append(change)

    @property
    def changed_block_count(self) -> int:
        return len(self.changes)

    def touched_sections(self, min_y: int = -64) -> set[int]:
        secs: set[int] = set()
        for c in self.changes:
            secs.add((c.y - min_y) // 16)
        return secs

    def summary(self) -> dict:
        return {
            "chunk": (self.chunk_x, self.chunk_z),
            "changed_block_count": self.changed_block_count,
            "touched_sections": sorted(self.touched_sections()),
        }
