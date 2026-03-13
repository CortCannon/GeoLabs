from __future__ import annotations
import random
from .blockstates_decode import decode_blockstates, encode_blockstates

def _roundtrip(palette_len: int, seed: int = 123) -> None:
    rnd = random.Random(seed)
    idx = [rnd.randrange(0, palette_len) for _ in range(4096)]
    data = encode_blockstates(idx, palette_len)
    out = decode_blockstates(data, palette_len)
    assert out == idx, f"roundtrip failed for palette_len={palette_len}"

def run_tests() -> None:
    for pal in [1, 2, 3, 4, 5, 16, 17, 32, 33, 128, 257, 4096]:
        _roundtrip(pal, seed=pal)

if __name__ == "__main__":
    run_tests()
    print("BitStorage tests OK")
