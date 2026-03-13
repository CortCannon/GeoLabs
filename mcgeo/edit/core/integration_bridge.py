from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .evaluator import Evaluator
from .invalidation import InvalidationTracker
from .layer_stack import LayerStack
from ..layers.box_replace import BoxReplaceLayer


@dataclass
class EditingCoreController:
    """Drop-in controller for integrating Editing Core v1 into an existing 3D-render build.

    This class intentionally avoids direct renderer or world-writer dependencies. The host UI
    provides chunk objects (real or demo adapters) and consumes deltas / dirty chunk coords.
    """

    stack: LayerStack = field(default_factory=LayerStack)
    evaluator: Evaluator = field(default_factory=Evaluator)
    invalidation: InvalidationTracker = field(default_factory=InvalidationTracker)

    def add_or_replace_box_layer(self, params: dict) -> BoxReplaceLayer:
        # Simple behavior for scaffold: one managed box layer at index 0
        layer = BoxReplaceLayer(
            name=str(params.get("name") or "Box Replace"),
            enabled=bool(params.get("enabled", True)),
            combine_mode=str(params.get("combine_mode") or "replace"),
            min_x=int(params.get("min_x", 0)),
            min_y=int(params.get("min_y", 0)),
            min_z=int(params.get("min_z", 0)),
            max_x=int(params.get("max_x", 15)),
            max_y=int(params.get("max_y", 31)),
            max_z=int(params.get("max_z", 15)),
            target_block=str(params.get("target_block") or "minecraft:iron_ore"),
            replace_whitelist=tuple(params.get("replace_whitelist") or ("minecraft:stone", "minecraft:deepslate")),
        )
        if self.stack.layers:
            self.stack.layers[0] = layer
            self.stack.version += 1
        else:
            self.stack.add(layer)
        self.invalidation.mark_chunks(layer.affected_chunks())
        return layer

    def preview_chunks(self, chunks: Iterable) -> tuple[list, dict]:
        deltas, stats = self.evaluator.evaluate_many(chunks, self.stack)
        touched = {(d.chunk_x, d.chunk_z) for d in deltas}
        if touched:
            self.invalidation.mark_chunks(list(touched))
        return deltas, {
            "changed_chunks": stats.changed_chunks,
            "changed_blocks": stats.changed_blocks,
            "evaluated_layers": stats.evaluated_layers,
            "stack_version": self.stack.version,
            "dirty_chunks": sorted(self.invalidation.dirty_chunks),
        }


    def reset(self) -> None:
        """Clear transient editing-core state for a new world/session."""
        self.stack = LayerStack()
        self.evaluator = Evaluator()
        self.invalidation = InvalidationTracker()

    def consume_dirty_chunks(self) -> set[tuple[int, int]]:
        return self.invalidation.consume_all()
