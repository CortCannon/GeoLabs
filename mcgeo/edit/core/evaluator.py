from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterable

from .chunk_delta import ChunkDelta, VoxelChange
from .layer_stack import LayerStack


@dataclass
class PreviewStats:
    changed_chunks: int = 0
    changed_blocks: int = 0
    evaluated_layers: int = 0
    skipped_layers: int = 0


class Evaluator:
    """Deterministic evaluator used by both Preview and Apply (same code path)."""

    def evaluate_chunk(self, chunk, stack: LayerStack) -> ChunkDelta:
        # result map stores final proposed state by local voxel coord, applied in layer order
        proposed: dict[tuple[int, int, int], tuple[str, str, str]] = {}
        # value tuple = (old_block, new_block, layer_id, layer_name) but we only keep one final entry
        for layer in stack.layers:
            if not layer.enabled:
                continue
            bounds = layer.influence_bounds()
            if bounds is not None and not bounds.overlaps_chunk(chunk.chunk_x, chunk.chunk_z):
                continue
            layer.apply_to_chunk(chunk, proposed)

        delta = ChunkDelta(chunk.chunk_x, chunk.chunk_z)
        # stable output ordering local y,z,x for determinism
        for (x, y, z) in sorted(proposed.keys(), key=lambda t: (t[1], t[2], t[0])):
            old_block, new_block, layer_id, layer_name = proposed[(x, y, z)]
            if old_block == new_block:
                continue
            delta.add(VoxelChange(x, y, z, old_block, new_block, layer_id, layer_name))
        return delta

    def evaluate_many(self, chunks: Iterable, stack: LayerStack) -> tuple[list[ChunkDelta], PreviewStats]:
        stats = PreviewStats()
        deltas: list[ChunkDelta] = []
        enabled_count = sum(1 for l in stack.layers if l.enabled)
        for chunk in chunks:
            d = self.evaluate_chunk(chunk, stack)
            if d.changed_block_count:
                deltas.append(d)
                stats.changed_chunks += 1
                stats.changed_blocks += d.changed_block_count
        stats.evaluated_layers = enabled_count
        return deltas, stats
