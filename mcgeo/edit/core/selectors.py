from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(slots=True)
class BlockSelector:
    whitelist: set[str] = field(default_factory=set)
    blacklist: set[str] = field(default_factory=set)

    def matches(self, block_id: str) -> bool:
        if self.whitelist and block_id not in self.whitelist:
            return False
        if block_id in self.blacklist:
            return False
        return True


@dataclass(slots=True)
class Constraints:
    min_y: int | None = None
    max_y: int | None = None
    selector: BlockSelector | None = None

    def y_ok(self, y: int) -> bool:
        if self.min_y is not None and y < self.min_y:
            return False
        if self.max_y is not None and y > self.max_y:
            return False
        return True

    def block_ok(self, block_id: str) -> bool:
        if self.selector is None:
            return True
        return self.selector.matches(block_id)
