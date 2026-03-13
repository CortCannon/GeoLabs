from __future__ import annotations
from dataclasses import dataclass
from typing import List

class BitStorageError(Exception):
    pass

def bits_needed(n: int) -> int:
    if n <= 1:
        return 0
    b = 0
    v = n - 1
    while v > 0:
        v >>= 1
        b += 1
    return b

def decode_blockstates(data_longs: List[int], palette_len: int) -> List[int]:
    """Decode modern Minecraft block_states BitStorage into 4096 palette indices.

    Critical: uses fixed-width slots within each 64-bit long; values do NOT cross long boundaries.
    """
    bits = max(4, bits_needed(palette_len))
    if palette_len <= 1:
        return [0] * 4096

    values_per_long = 64 // bits
    mask = (1 << bits) - 1

    out: List[int] = [0] * 4096
    idx = 0
    for long_val in data_longs:
        # Java long is signed; in NBT it is stored as signed 64, but bit ops should treat it unsigned.
        v = long_val & ((1 << 64) - 1)
        for i in range(values_per_long):
            if idx >= 4096:
                break
            out[idx] = (v >> (i * bits)) & mask
            idx += 1
        if idx >= 4096:
            break

    if idx < 4096:
        # Some data arrays can be shorter if palette_len==1; otherwise this is suspicious
        # but we won't hard-fail to stay robust.
        pass

    return out

def encode_blockstates(indices: List[int], palette_len: int) -> List[int]:
    bits = max(4, bits_needed(palette_len))
    if palette_len <= 1:
        return []  # Minecraft may omit data when only one palette entry

    values_per_long = 64 // bits
    mask = (1 << bits) - 1

    out = []
    idx = 0
    while idx < 4096:
        v = 0
        for i in range(values_per_long):
            if idx >= 4096:
                break
            v |= (int(indices[idx]) & mask) << (i * bits)
            idx += 1
        # store as signed 64-bit for NBT long array
        if v >= (1 << 63):
            v -= (1 << 64)
        out.append(v)
    return out
