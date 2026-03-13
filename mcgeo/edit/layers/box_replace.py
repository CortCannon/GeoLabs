from __future__ import annotations
from dataclasses import dataclass, field

from ..core.layer_base import LayerBase, Bounds
from ..core.selectors import Constraints, BlockSelector


@dataclass(slots=True)
class BoxReplaceLayer(LayerBase):
    min_x: int = 0
    min_y: int = 0
    min_z: int = 0
    max_x: int = 15
    max_y: int = 31
    max_z: int = 15
    target_block: str = "minecraft:iron_ore"
    replace_whitelist: tuple[str, ...] = ("minecraft:stone", "minecraft:deepslate")

    def __post_init__(self) -> None:
        if self.constraints is None:
            self.constraints = Constraints()
        if self.constraints.selector is None and self.replace_whitelist:
            self.constraints.selector = BlockSelector(whitelist=set(self.replace_whitelist))

    def influence_bounds(self) -> Bounds | None:
        return Bounds(self.min_x, self.min_y, self.min_z, self.max_x, self.max_y, self.max_z)

    def apply_to_chunk(self, chunk, result: dict[tuple[int, int, int], tuple[str, str, str, str]]) -> None:
        b = self.influence_bounds()
        assert b is not None
        cx0 = chunk.chunk_x * 16
        cz0 = chunk.chunk_z * 16
        x0 = max(b.min_x, cx0)
        x1 = min(b.max_x, cx0 + 15)
        z0 = max(b.min_z, cz0)
        z1 = min(b.max_z, cz0 + 15)
        if x0 > x1 or z0 > z1:
            return
        # stable iteration y,z,x
        for y in range(b.min_y, b.max_y + 1):
            if not self.constraints.y_ok(y):
                continue
            for z in range(z0, z1 + 1):
                for x in range(x0, x1 + 1):
                    old = chunk.get_block(x, y, z)
                    if not self.constraints.block_ok(old):
                        continue
                    if self.combine_mode.lower() in {"carve", "subtract"}:
                        new = "minecraft:air"
                    else:
                        new = self.target_block
                    result[(x, y, z)] = (old, new, self.layer_id, self.name)
