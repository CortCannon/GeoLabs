from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple
from ..world.block_colors import block_to_color

@dataclass
class MaterialInfo:
    name: str
    color_rgb: Tuple[float,float,float]  # 0..1

class MaterialRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._name_to_id: Dict[str,int] = {"minecraft:air": 0}
        self._id_to_info: List[MaterialInfo] = [MaterialInfo("minecraft:air", (0.0,0.0,0.0))]
        self._version = 0

    def get_or_create(self, name: str) -> int:
        if not name:
            name = "minecraft:air"
        with self._lock:
            mid = self._name_to_id.get(name)
            if mid is not None:
                return mid
            mid = len(self._id_to_info)
            c = block_to_color(name)
            rgb = (c.redF(), c.greenF(), c.blueF())
            self._name_to_id[name] = mid
            self._id_to_info.append(MaterialInfo(name, rgb))
            self._version += 1
            return mid

    def names(self) -> List[str]:
        with self._lock:
            return [mi.name for mi in self._id_to_info if mi.name != "minecraft:air"]

    def color(self, mid: int) -> Tuple[float,float,float]:
        with self._lock:
            if 0 <= mid < len(self._id_to_info):
                return self._id_to_info[mid].color_rgb
            return (1.0, 0.0, 1.0)

    def size(self) -> int:
        with self._lock:
            return len(self._id_to_info)

    def version(self) -> int:
        with self._lock:
            return self._version
