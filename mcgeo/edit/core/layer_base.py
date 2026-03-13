from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Iterable
import uuid

from .selectors import Constraints


class ChunkView(Protocol):
    chunk_x: int
    chunk_z: int
    def get_block(self, x: int, y: int, z: int) -> str: ...


@dataclass(slots=True)
class Bounds:
    min_x: int
    min_y: int
    min_z: int
    max_x: int
    max_y: int
    max_z: int

    def contains(self, x: int, y: int, z: int) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y and self.min_z <= z <= self.max_z

    def overlaps_chunk(self, chunk_x: int, chunk_z: int) -> bool:
        cx0 = chunk_x * 16
        cz0 = chunk_z * 16
        cx1 = cx0 + 15
        cz1 = cz0 + 15
        return not (self.max_x < cx0 or self.min_x > cx1 or self.max_z < cz0 or self.min_z > cz1)


@dataclass(slots=True)
class LayerBase:
    name: str
    enabled: bool = True
    combine_mode: str = "replace"
    constraints: Constraints = field(default_factory=Constraints)
    seed: int = 0
    layer_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    preview_visible: bool = True
    dirty_version: int = 0

    def mark_dirty(self) -> None:
        self.dirty_version += 1

    def influence_bounds(self) -> Bounds | None:
        return None

    def affected_chunks(self) -> list[tuple[int, int]]:
        b = self.influence_bounds()
        if b is None:
            return []
        out: list[tuple[int, int]] = []
        for cx in range(b.min_x // 16, b.max_x // 16 + 1):
            for cz in range(b.min_z // 16, b.max_z // 16 + 1):
                out.append((cx, cz))
        return out

    def apply_to_chunk(self, chunk: ChunkView, result: dict[tuple[int, int, int], str]) -> None:
        raise NotImplementedError
