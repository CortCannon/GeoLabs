from __future__ import annotations
import hashlib
import random
from typing import Any


def stable_seed(*parts: Any) -> int:
    h = hashlib.blake2b(digest_size=16)
    for part in parts:
        h.update(repr(part).encode("utf-8"))
        h.update(b"|")
    return int.from_bytes(h.digest()[:8], "little", signed=False)


def stable_rng(*parts: Any) -> random.Random:
    return random.Random(stable_seed(*parts))
