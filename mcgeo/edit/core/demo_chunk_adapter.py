from __future__ import annotations

class DemoChunkAdapter:
    """Temporary adapter for wiring the Editing Core into UI before real chunk decode is connected.

    Replace with an adapter backed by your existing Anvil/chunk decode path.
    """
    def __init__(self, chunk_x: int = 0, chunk_z: int = 0, min_y: int = -64, max_y: int = 320) -> None:
        self.chunk_x = int(chunk_x)
        self.chunk_z = int(chunk_z)
        self.min_y = int(min_y)
        self.max_y = int(max_y)

    def get_block(self, x: int, y: int, z: int) -> str:
        if y > 62:
            return "minecraft:air"
        if y > 57:
            return "minecraft:dirt"
        if y > 54:
            return "minecraft:grass_block"
        if y > 0:
            return "minecraft:stone"
        if y > -48:
            return "minecraft:deepslate"
        return "minecraft:tuff"
