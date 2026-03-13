from __future__ import annotations
from dataclasses import dataclass
from typing import Any, BinaryIO
import io
import struct

# NBT tag IDs
TAG_End = 0
TAG_Byte = 1
TAG_Short = 2
TAG_Int = 3
TAG_Long = 4
TAG_Float = 5
TAG_Double = 6
TAG_Byte_Array = 7
TAG_String = 8
TAG_List = 9
TAG_Compound = 10
TAG_Int_Array = 11
TAG_Long_Array = 12

@dataclass
class NbtTag:
    tag_id: int
    value: Any

class NbtError(Exception):
    pass

def read_nbt(data: bytes) -> NbtTag:
    """Read a full NBT blob (root tag includes name). Returns the root compound tag."""
    buf = io.BytesIO(data)
    tag_id = _read_u8(buf)
    if tag_id != TAG_Compound:
        raise NbtError(f"Root tag must be TAG_Compound (10), got {tag_id}")
    _ = _read_string(buf)  # root name (often empty)
    comp = _read_compound_payload(buf)
    return NbtTag(TAG_Compound, comp)

def write_nbt(root_name: str, root_compound: dict[str, NbtTag]) -> bytes:
    out = io.BytesIO()
    out.write(struct.pack(">B", TAG_Compound))
    _write_string(out, root_name)
    _write_compound_payload(out, root_compound)
    return out.getvalue()

def _read_payload(buf: BinaryIO, tag_id: int) -> Any:
    if tag_id == TAG_Byte:
        return _read_i8(buf)
    if tag_id == TAG_Short:
        return _read_i16(buf)
    if tag_id == TAG_Int:
        return _read_i32(buf)
    if tag_id == TAG_Long:
        return _read_i64(buf)
    if tag_id == TAG_Float:
        return _read_f32(buf)
    if tag_id == TAG_Double:
        return _read_f64(buf)
    if tag_id == TAG_Byte_Array:
        n = _read_i32(buf)
        return buf.read(n)
    if tag_id == TAG_String:
        return _read_string(buf)
    if tag_id == TAG_List:
        elem_id = _read_u8(buf)
        n = _read_i32(buf)
        items = [_read_payload(buf, elem_id) for _ in range(n)]
        return (elem_id, items)
    if tag_id == TAG_Compound:
        return _read_compound_payload(buf)
    if tag_id == TAG_Int_Array:
        n = _read_i32(buf)
        return [ _read_i32(buf) for _ in range(n) ]
    if tag_id == TAG_Long_Array:
        n = _read_i32(buf)
        return [ _read_i64(buf) for _ in range(n) ]
    if tag_id == TAG_End:
        return None
    raise NbtError(f"Unsupported tag id: {tag_id}")

def _read_compound_payload(buf: BinaryIO) -> dict[str, NbtTag]:
    out: dict[str, NbtTag] = {}
    while True:
        tag_id = _read_u8(buf)
        if tag_id == TAG_End:
            break
        name = _read_string(buf)
        value = _read_payload(buf, tag_id)
        out[name] = NbtTag(tag_id, value)
    return out

def _write_payload(out: BinaryIO, tag_id: int, value: Any) -> None:
    if tag_id == TAG_Byte:
        out.write(struct.pack(">b", int(value)))
        return
    if tag_id == TAG_Short:
        out.write(struct.pack(">h", int(value)))
        return
    if tag_id == TAG_Int:
        out.write(struct.pack(">i", int(value)))
        return
    if tag_id == TAG_Long:
        out.write(struct.pack(">q", int(value)))
        return
    if tag_id == TAG_Float:
        out.write(struct.pack(">f", float(value)))
        return
    if tag_id == TAG_Double:
        out.write(struct.pack(">d", float(value)))
        return
    if tag_id == TAG_Byte_Array:
        b = bytes(value)
        out.write(struct.pack(">i", len(b)))
        out.write(b)
        return
    if tag_id == TAG_String:
        _write_string(out, str(value))
        return
    if tag_id == TAG_List:
        elem_id, items = value
        out.write(struct.pack(">B", int(elem_id)))
        out.write(struct.pack(">i", len(items)))
        for it in items:
            _write_payload(out, int(elem_id), it)
        return
    if tag_id == TAG_Compound:
        _write_compound_payload(out, value)
        return
    if tag_id == TAG_Int_Array:
        out.write(struct.pack(">i", len(value)))
        for v in value:
            out.write(struct.pack(">i", int(v)))
        return
    if tag_id == TAG_Long_Array:
        out.write(struct.pack(">i", len(value)))
        for v in value:
            out.write(struct.pack(">q", int(v)))
        return
    if tag_id == TAG_End:
        return
    raise NbtError(f"Unsupported tag id for write: {tag_id}")

def _write_compound_payload(out: BinaryIO, comp: dict[str, NbtTag]) -> None:
    # Deterministic output: write keys in sorted order (byte-for-byte stable)
    for name in sorted(comp.keys()):
        tag = comp[name]
        out.write(struct.pack(">B", int(tag.tag_id)))
        _write_string(out, name)
        _write_payload(out, int(tag.tag_id), tag.value)
    out.write(struct.pack(">B", TAG_End))

def _read_u8(buf: BinaryIO) -> int:
    b = buf.read(1)
    if len(b) != 1:
        raise NbtError("Unexpected EOF")
    return b[0]

def _read_i8(buf: BinaryIO) -> int:
    return struct.unpack(">b", buf.read(1))[0]

def _read_i16(buf: BinaryIO) -> int:
    return struct.unpack(">h", buf.read(2))[0]

def _read_i32(buf: BinaryIO) -> int:
    return struct.unpack(">i", buf.read(4))[0]

def _read_i64(buf: BinaryIO) -> int:
    return struct.unpack(">q", buf.read(8))[0]

def _read_f32(buf: BinaryIO) -> float:
    return struct.unpack(">f", buf.read(4))[0]

def _read_f64(buf: BinaryIO) -> float:
    return struct.unpack(">d", buf.read(8))[0]

def _read_string(buf: BinaryIO) -> str:
    n = struct.unpack(">H", buf.read(2))[0]
    s = buf.read(n)
    return s.decode("utf-8", errors="strict")

def _write_string(out: BinaryIO, s: str) -> None:
    b = s.encode("utf-8")
    out.write(struct.pack(">H", len(b)))
    out.write(b)
