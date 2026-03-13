from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

AIR_NAMES = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}

def canonical_state(name: str, props: Optional[Dict[str, str]]) -> str:
    """Deterministic canonical string for a block state."""
    if not props:
        return name
    items = sorted((k, str(v)) for k, v in props.items())
    inside = ",".join([f"{k}={v}" for k, v in items])
    return f"{name}[{inside}]"

def is_air(name: str) -> bool:
    return name in AIR_NAMES
