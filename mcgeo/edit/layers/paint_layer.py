from __future__ import annotations
from dataclasses import dataclass, field

from ..core.layer_base import LayerBase, Bounds


@dataclass(slots=True)
class PaintStroke:
    points: list[tuple[int, int, int]] = field(default_factory=list)
    radius: int = 3
    block_id: str = "minecraft:iron_ore"


@dataclass(slots=True)
class PaintLayer(LayerBase):
    strokes: list[PaintStroke] = field(default_factory=list)

    def influence_bounds(self) -> Bounds | None:
        if not self.strokes:
            return None
        xs, ys, zs = [], [], []
        for s in self.strokes:
            r = max(0, int(s.radius))
            for x, y, z in s.points:
                xs.extend([x-r, x+r])
                ys.extend([y-r, y+r])
                zs.extend([z-r, z+r])
        return Bounds(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def apply_to_chunk(self, chunk, result: dict[tuple[int, int, int], tuple[str, str, str, str]]) -> None:
        # Placeholder for next milestone: rasterize strokes into voxel ops
        return
