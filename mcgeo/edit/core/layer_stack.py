from __future__ import annotations
from dataclasses import dataclass, field

from .layer_base import LayerBase


@dataclass
class LayerStack:
    layers: list[LayerBase] = field(default_factory=list)
    version: int = 0

    def add(self, layer: LayerBase) -> None:
        self.layers.append(layer)
        self.version += 1

    def remove_by_id(self, layer_id: str) -> bool:
        before = len(self.layers)
        self.layers = [l for l in self.layers if l.layer_id != layer_id]
        changed = len(self.layers) != before
        if changed:
            self.version += 1
        return changed

    def move(self, old_index: int, new_index: int) -> None:
        if old_index < 0 or new_index < 0 or old_index >= len(self.layers) or new_index >= len(self.layers):
            return
        item = self.layers.pop(old_index)
        self.layers.insert(new_index, item)
        self.version += 1

    def enabled_layers(self) -> list[LayerBase]:
        return [l for l in self.layers if l.enabled]
