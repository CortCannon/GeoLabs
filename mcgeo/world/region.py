from __future__ import annotations
import io
import os
import struct
import zlib
import gzip
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

class RegionError(Exception):
    pass

@dataclass(frozen=True)
class ChunkLocation:
    sector_offset: int
    sector_count: int
    timestamp: int

class RegionFile:
    """Read a Minecraft .mca region file (Anvil format)."""
    SECTOR_BYTES = 4096
    HEADER_BYTES = 8192

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Optional[io.BufferedReader] = None
        self._loc: list[ChunkLocation] = []

    def __enter__(self) -> "RegionFile":
        self._fh = open(self.path, "rb")
        header = self._fh.read(self.HEADER_BYTES)
        if len(header) != self.HEADER_BYTES:
            raise RegionError(f"Bad region header: {self.path}")
        offsets = header[:4096]
        times = header[4096:8192]
        self._loc = []
        for i in range(1024):
            off = offsets[i*4:(i+1)*4]
            t = struct.unpack(">I", times[i*4:(i+1)*4])[0]
            sector_offset = (off[0] << 16) | (off[1] << 8) | off[2]
            sector_count = off[3]
            self._loc.append(ChunkLocation(sector_offset, sector_count, t))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    @staticmethod
    def index(cx_in_region: int, cz_in_region: int) -> int:
        return (cx_in_region & 31) + ((cz_in_region & 31) * 32)

    def has_chunk(self, cx_in_region: int, cz_in_region: int) -> bool:
        loc = self._loc[self.index(cx_in_region, cz_in_region)]
        return loc.sector_offset != 0 and loc.sector_count != 0

    def read_chunk_nbt_bytes(self, cx_in_region: int, cz_in_region: int) -> Optional[bytes]:
        if not self._fh:
            raise RegionError("RegionFile not opened")
        loc = self._loc[self.index(cx_in_region, cz_in_region)]
        if loc.sector_offset == 0 or loc.sector_count == 0:
            return None

        self._fh.seek(loc.sector_offset * self.SECTOR_BYTES)
        length_bytes = self._fh.read(4)
        if len(length_bytes) != 4:
            raise RegionError("Unexpected EOF reading chunk length")
        length = struct.unpack(">I", length_bytes)[0]
        ctype = self._fh.read(1)
        if len(ctype) != 1:
            raise RegionError("Unexpected EOF reading compression type")
        ctype = ctype[0]
        payload = self._fh.read(length - 1)

        if ctype == 1:
            return gzip.decompress(payload)
        if ctype == 2:
            return zlib.decompress(payload)
        if ctype == 3:
            # Uncompressed (rare)
            return payload
        raise RegionError(f"Unknown compression type {ctype} in {self.path}")
