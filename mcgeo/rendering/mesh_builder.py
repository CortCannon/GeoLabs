from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Optional
import math

from ..world.anvil_reader import ChunkModel
from ..world.palette import is_air
from .materials import MaterialRegistry

@dataclass
class MeshData:
    vertices: bytes          # packed float32
    vertex_count: int        # number of vertices (not floats)
    lod: str                 # "voxel" or "surface"
    materials_version: int
    top_heights: tuple[int, ...] | None = None  # 16x16 local top solid y (world Y)

# Vertex format: 7 float32 => (px,py,pz, r,g,b, matId)
_STRIDE = 7

# Preview ore/cave material names (render-only)
PREVIEW_CAVE_MARKER = "wgl:preview_cave_marker"
PREVIEW_ORES = [
    "wgl:preview_ore_coal",
    "wgl:preview_ore_iron",
    "wgl:preview_ore_copper",
    "wgl:preview_ore_gold",
    "wgl:preview_ore_redstone",
    "wgl:preview_ore_lapis",
    "wgl:preview_ore_diamond",
    "wgl:preview_ore_emerald",
]



def _chunk_top_heights(chunk: Optional[ChunkModel]) -> tuple[int, ...]:
    if chunk is None:
        return ()
    tops: list[int] = []
    for z in range(16):
        for x in range(16):
            try:
                y, _name = chunk.find_surface_block(x, z)
            except Exception:
                y = 0
            tops.append(int(y))
    return tuple(tops)

def build_chunk_mesh(
    chunk: Optional[ChunkModel],
    cx: int,
    cz: int,
    lod: str,
    reg: MaterialRegistry,
    preview: Optional[dict] = None,
) -> MeshData:
    if chunk is None:
        return MeshData(vertices=b"", vertex_count=0, lod=lod, materials_version=reg.version(), top_heights=())

    if lod == "surface":
        # Prototype preview layers currently apply to voxel LOD only.
        verts = _surface_greedy(chunk, cx, cz, reg)
        return MeshData(verts, len(verts)//(4*_STRIDE), lod, reg.version(), top_heights=_chunk_top_heights(chunk))
    else:
        verts = _voxel_greedy(chunk, cx, cz, reg, preview=preview)
        return MeshData(verts, len(verts)//(4*_STRIDE), lod, reg.version(), top_heights=_chunk_top_heights(chunk))


def _chunk_grid(chunk: ChunkModel, reg: MaterialRegistry):
    # Build dense grid for present sections only (still contiguous)
    if not chunk.sections:
        return ([], 0, 0, [])  # grid, min_sy, height, replaceable_mask
    min_sy = min(chunk.sections.keys())
    max_sy = max(chunk.sections.keys())
    h = (max_sy - min_sy + 1) * 16
    # x + z*16 + y*256
    grid = [0] * (16 * 16 * h)
    replaceable = [0] * (16 * 16 * h)
    for sy, sec in chunk.sections.items():
        y0 = (sy - min_sy) * 16
        pal_names = [s.split("[",1)[0] for s in sec.palette]
        for ly in range(16):
            gy = y0 + ly
            base_y = gy * 256
            for z in range(16):
                base_z = base_y + z*16
                for x in range(16):
                    idx = (ly * 16 + z) * 16 + x  # matches anvil_reader's order
                    pi = sec.indices[idx]
                    if 0 <= pi < len(pal_names):
                        name = pal_names[pi]
                    else:
                        name = "minecraft:air"
                    if is_air(name):
                        continue
                    mid = reg.get_or_create(name)
                    cell_i = base_z + x
                    grid[cell_i] = mid
                    if _is_replaceable_rock_name(name):
                        replaceable[cell_i] = 1
    return (grid, min_sy, h, replaceable)


def _emit_quad(out: List[float], p0, p1, p2, p3, color, matId: float):
    r,g,b = color
    # two triangles: p0 p1 p2 and p0 p2 p3
    for p in (p0,p1,p2, p0,p2,p3):
        out.extend([p[0],p[1],p[2], r,g,b, matId])

def _shade(color, factor: float):
    return (color[0]*factor, color[1]*factor, color[2]*factor)

def _preview_has_effects(preview: Optional[dict]) -> bool:
    d = dict(preview or {})
    if bool(d.get("enabled", False)):
        return True
    layers = d.get("paint_layers") or []
    if not isinstance(layers, list):
        return False
    for layer in layers:
        try:
            ld = dict(layer or {})
        except Exception:
            continue
        if not bool(ld.get('enabled', True)) or not bool(ld.get('preview_visible', True)):
            continue
        if ld.get('strokes'):
            return True
    return False


def _voxel_greedy(chunk: ChunkModel, cx: int, cz: int, reg: MaterialRegistry, preview: Optional[dict] = None) -> bytes:
    grid, min_sy, h, replaceable = _chunk_grid(chunk, reg)
    if not grid:
        return b""

    if _preview_has_effects(preview):
        _apply_preview_layers(grid, replaceable, min_sy, h, cx, cz, reg, preview or {})

    sx, sy, sz = 16, h, 16

    def at(x,y,z):
        if x<0 or x>=sx or y<0 or y>=sy or z<0 or z>=sz:
            return 0
        return grid[x + z*16 + y*256]

    out: List[float] = []
    ox = cx * 16.0
    oz = cz * 16.0
    oy0 = min_sy * 16.0

    dims = (sx, sy, sz)
    for d in range(3):
        u = (d + 1) % 3
        v = (d + 2) % 3
        x = [0,0,0]
        q = [0,0,0]
        q[d] = 1

        mask = [0] * (dims[u] * dims[v])
        for x[d] in range(-1, dims[d]):
            n = 0
            for x[v] in range(dims[v]):
                for x[u] in range(dims[u]):
                    a = 0
                    b = 0
                    ax,ay,az = x[0],x[1],x[2]
                    bx,by,bz = ax+q[0], ay+q[1], az+q[2]
                    if 0 <= ax < dims[0] and 0 <= ay < dims[1] and 0 <= az < dims[2]:
                        a = at(ax,ay,az)
                    if 0 <= bx < dims[0] and 0 <= by < dims[1] and 0 <= bz < dims[2]:
                        b = at(bx,by,bz)
                    if (a != 0) != (b != 0):
                        mask[n] = a if a != 0 else -b
                    else:
                        mask[n] = 0
                    n += 1

            n = 0
            for j in range(dims[v]):
                i = 0
                while i < dims[u]:
                    c = mask[n]
                    if c == 0:
                        i += 1
                        n += 1
                        continue
                    w = 1
                    while i + w < dims[u] and mask[n + w] == c:
                        w += 1
                    hgt = 1
                    done = False
                    while j + hgt < dims[v] and not done:
                        for k in range(w):
                            if mask[n + k + hgt*dims[u]] != c:
                                done = True
                                break
                        if not done:
                            hgt += 1
                    x0 = [0,0,0]
                    x1 = [0,0,0]
                    x0[d] = x[d] + 1
                    x1[d] = x[d] + 1
                    x0[u] = i
                    x0[v] = j
                    x1[u] = i + w
                    x1[v] = j + hgt

                    mat = float(abs(c))
                    base_color = reg.color(int(abs(c)))
                    if d == 1:
                        shade = 1.00 if c > 0 else 0.75
                    else:
                        shade = 0.88 if c > 0 else 0.80
                    col = _shade(base_color, shade)

                    def pos(xx,yy,zz):
                        return (ox + xx, oy0 + yy, oz + zz)

                    if d == 0:
                        X = x0[d]
                        if c > 0:
                            p0 = pos(X, x0[1], x0[2]); p1 = pos(X, x1[1], x0[2]); p2 = pos(X, x1[1], x1[2]); p3 = pos(X, x0[1], x1[2])
                        else:
                            p0 = pos(X, x0[1], x0[2]); p1 = pos(X, x0[1], x1[2]); p2 = pos(X, x1[1], x1[2]); p3 = pos(X, x1[1], x0[2])
                    elif d == 1:
                        Y = x0[d]
                        if c > 0:
                            p0 = pos(x0[0], Y, x0[2]); p1 = pos(x1[0], Y, x0[2]); p2 = pos(x1[0], Y, x1[2]); p3 = pos(x0[0], Y, x1[2])
                        else:
                            p0 = pos(x0[0], Y, x0[2]); p1 = pos(x0[0], Y, x1[2]); p2 = pos(x1[0], Y, x1[2]); p3 = pos(x1[0], Y, x0[2])
                    else:
                        Z = x0[d]
                        if c > 0:
                            p0 = pos(x0[0], x0[1], Z); p1 = pos(x1[0], x0[1], Z); p2 = pos(x1[0], x1[1], Z); p3 = pos(x0[0], x1[1], Z)
                        else:
                            p0 = pos(x0[0], x0[1], Z); p1 = pos(x0[0], x1[1], Z); p2 = pos(x1[0], x1[1], Z); p3 = pos(x1[0], x0[1], Z)

                    _emit_quad(out, p0,p1,p2,p3, col, mat)

                    for yy in range(hgt):
                        for xx in range(w):
                            mask[n + xx + yy*dims[u]] = 0
                    i += w
                    n += w
    import array
    arr = array.array('f', out)
    return arr.tobytes()


def _surface_greedy(chunk: ChunkModel, cx: int, cz: int, reg: MaterialRegistry) -> bytes:
    cells = [[(0,0) for _ in range(16)] for __ in range(16)]
    if chunk.sections:
        top_sy = max(chunk.sections.keys())
        bot_sy = min(chunk.sections.keys())
    else:
        return b""
    sec_cache = {}
    for sy, sec in chunk.sections.items():
        pal_names = [s.split("[",1)[0] for s in sec.palette]
        sec_cache[sy] = (sec, pal_names)

    for z in range(16):
        for x in range(16):
            found = False
            for sy in range(top_sy, bot_sy-1, -1):
                sec, pal_names = sec_cache.get(sy, (None, None))
                if sec is None:
                    continue
                for ly in range(15, -1, -1):
                    idx = (ly * 16 + z) * 16 + x
                    pi = sec.indices[idx]
                    name = pal_names[pi] if 0 <= pi < len(pal_names) else "minecraft:air"
                    if is_air(name):
                        continue
                    y = sy*16 + ly
                    mid = reg.get_or_create(name)
                    cells[z][x] = (y, mid)
                    found = True
                    break
                if found:
                    break

    out: List[float] = []
    used = [[False]*16 for _ in range(16)]
    ox = cx * 16.0
    oz = cz * 16.0

    for z in range(16):
        for x in range(16):
            if used[z][x]:
                continue
            y, mid = cells[z][x]
            if mid == 0:
                used[z][x] = True
                continue
            w = 1
            while x+w < 16 and not used[z][x+w] and cells[z][x+w] == (y,mid):
                w += 1
            hgt = 1
            done = False
            while z+hgt < 16 and not done:
                for k in range(w):
                    if used[z+hgt][x+k] or cells[z+hgt][x+k] != (y,mid):
                        done = True
                        break
                if not done:
                    hgt += 1
            for dz in range(hgt):
                for dx in range(w):
                    used[z+dz][x+dx] = True

            base_color = reg.color(mid)
            col = _shade(base_color, 1.0)
            mat = float(mid)
            Y = float(y + 1)
            p0 = (ox + x,     Y, oz + z)
            p1 = (ox + x + w, Y, oz + z)
            p2 = (ox + x + w, Y, oz + z + hgt)
            p3 = (ox + x,     Y, oz + z + hgt)
            _emit_quad(out, p0,p1,p2,p3, col, mat)

    import array
    arr = array.array('f', out)
    return arr.tobytes()



# ---------------- preview layer prototype ----------------

_REPLACEABLE_ROCK_NAMES = {
    "minecraft:stone", "minecraft:deepslate", "minecraft:tuff", "minecraft:andesite",
    "minecraft:diorite", "minecraft:granite", "minecraft:calcite", "minecraft:basalt",
    "minecraft:blackstone", "minecraft:end_stone", "minecraft:netherrack",
}

def _is_replaceable_rock_name(name: str) -> bool:
    base = name.split("[", 1)[0]
    if base in _REPLACEABLE_ROCK_NAMES:
        return True
    # lightweight heuristics for modded/variant stones
    return (
        base.endswith("_stone")
        or base.endswith("_deepslate")
        or base.endswith("_rock")
        or base.endswith("_slate")
    )

def _mix32(v: int) -> int:
    v &= 0xFFFFFFFF
    v ^= (v >> 16)
    v = (v * 0x7FEB352D) & 0xFFFFFFFF
    v ^= (v >> 15)
    v = (v * 0x846CA68B) & 0xFFFFFFFF
    v ^= (v >> 16)
    return v & 0xFFFFFFFF

def _hash_u32(*vals: int) -> int:
    h = 0x9E3779B9
    for i, v in enumerate(vals):
        h = _mix32(h ^ _mix32(int(v) + i * 0x85EBCA6B))
    return h

def _rand_range(seed: int, lo: int, hi: int) -> int:
    if hi <= lo:
        return lo
    return lo + (seed % (hi - lo + 1))

def _rand_unit(seed: int) -> float:
    return (seed & 0xFFFFFF) / float(0x1000000)

def _rand_signed(seed: int) -> float:
    return _rand_unit(seed) * 2.0 - 1.0

def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v

def _clampf(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v

def _cell_index(x: int, y: int, z: int) -> int:
    return x + z * 16 + y * 256

def _world_y_to_local(world_y: float, min_sy: int) -> int:
    oy = min_sy * 16
    return int(math.floor(world_y - oy))

def _compute_top_heights(grid: List[int], h: int) -> List[int]:
    # local top solid Y per (x,z), -1 if no solid
    tops = [-1] * (16 * 16)
    for z in range(16):
        for x in range(16):
            top = -1
            for y in range(h - 1, -1, -1):
                if grid[_cell_index(x, y, z)] != 0:
                    top = y
                    break
            tops[z * 16 + x] = top
    return tops

def _column_has_cover(tops: List[int], gx: int, gz: int, gy: int, min_cover: int) -> bool:
    if gx < 0 or gx > 15 or gz < 0 or gz > 15:
        return True  # outside chunk; don't over-constrain
    t = tops[gz * 16 + gx]
    if t < 0:
        return False
    return (t - gy) >= min_cover

def _hash_noise3(seed: int, x: int, y: int, z: int) -> float:
    # stable cell-ish noise in [-1,1]
    return _rand_signed(_hash_u32(seed, x, y, z))

def _carve_or_mark_sphere(
    grid: List[int],
    replaceable: List[int],
    h: int,
    cx: int,
    cz: int,
    min_sy: int,
    wx_center: float,
    wy_center: float,
    wz_center: float,
    radius: float,
    cave_mid: int,
    marker_mode: bool,
    tops: Optional[List[int]] = None,
    min_cover: int = 6,
    irregular_seed: int = 0,
    irregularity: float = 0.20,
):
    if radius <= 0.1:
        return
    ox = cx * 16.0
    oz = cz * 16.0
    oy = min_sy * 16.0
    x0 = _clamp(int(math.floor(wx_center - radius - ox)), 0, 15)
    x1 = _clamp(int(math.ceil (wx_center + radius - ox)), 0, 15)
    z0 = _clamp(int(math.floor(wz_center - radius - oz)), 0, 15)
    z1 = _clamp(int(math.ceil (wz_center + radius - oz)), 0, 15)
    y0 = _clamp(int(math.floor(wy_center - radius - oy)), 0, h - 1)
    y1 = _clamp(int(math.ceil (wy_center + radius - oy)), 0, h - 1)

    r2 = radius * radius
    invr = 1.0 / max(radius, 0.001)
    for gy in range(y0, y1 + 1):
        wy = oy + gy + 0.5
        dy2 = (wy - wy_center) ** 2
        if dy2 > r2:
            continue
        for gz in range(z0, z1 + 1):
            wz = oz + gz + 0.5
            dz2 = (wz - wz_center) ** 2
            if dy2 + dz2 > r2:
                continue
            for gx in range(x0, x1 + 1):
                wx = ox + gx + 0.5
                d2 = dy2 + dz2 + (wx - wx_center) ** 2
                if d2 > r2:
                    continue
                # irregular carve boundary for more natural walls
                if irregularity > 0.0:
                    dn = math.sqrt(max(0.0, d2)) * invr
                    n = _hash_noise3(irregular_seed, int(math.floor(wx)), int(math.floor(wy)), int(math.floor(wz)))
                    threshold = 1.0 + n * irregularity * (0.3 + 0.7 * dn)
                    if dn > threshold:
                        continue

                i = _cell_index(gx, gy, gz)
                if grid[i] == 0:
                    continue

                # Keep caves from punching through surface too easily.
                if tops is not None and not _column_has_cover(tops, gx, gz, gy, min_cover):
                    continue

                if marker_mode:
                    grid[i] = cave_mid
                    replaceable[i] = 0
                else:
                    grid[i] = 0
                    replaceable[i] = 0

def _carve_tunnel_segment(
    grid: List[int],
    replaceable: List[int],
    h: int,
    cx: int,
    cz: int,
    min_sy: int,
    tops: Optional[List[int]],
    cave_mid: int,
    marker_mode: bool,
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    r0: float, r1: float,
    seed: int,
    min_cover: int,
):
    dx = x1 - x0
    dy = y1 - y0
    dz = z1 - z0
    seg_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    steps = max(1, int(math.ceil(seg_len / max(0.8, min(r0, r1) * 0.75))))
    for s in range(steps + 1):
        t = s / float(steps)
        wx = x0 + dx * t
        wy = y0 + dy * t
        wz = z0 + dz * t
        rr = r0 + (r1 - r0) * t
        rr *= (0.92 + 0.16 * _rand_unit(_hash_u32(seed, s, 91)))
        _carve_or_mark_sphere(
            grid, replaceable, h, cx, cz, min_sy,
            wx, wy, wz, rr, cave_mid, marker_mode,
            tops=tops,
            min_cover=min_cover,
            irregular_seed=_hash_u32(seed, s, 92),
            irregularity=0.18,
        )

def _place_ore_irregular_ellipsoid(
    grid: List[int],
    replaceable: List[int],
    h: int,
    cx: int,
    cz: int,
    min_sy: int,
    wx_center: float,
    wy_center: float,
    wz_center: float,
    rx: float, ry: float, rz: float,
    ore_mid: int,
    seed: int,
    boundary_jitter: float = 0.22,
):
    if rx <= 0.1 or ry <= 0.1 or rz <= 0.1:
        return
    ox = cx * 16.0
    oz = cz * 16.0
    oy = min_sy * 16.0
    x0 = _clamp(int(math.floor(wx_center - rx - ox)), 0, 15)
    x1 = _clamp(int(math.ceil (wx_center + rx - ox)), 0, 15)
    z0 = _clamp(int(math.floor(wz_center - rz - oz)), 0, 15)
    z1 = _clamp(int(math.ceil (wz_center + rz - oz)), 0, 15)
    y0 = _clamp(int(math.floor(wy_center - ry - oy)), 0, h - 1)
    y1 = _clamp(int(math.ceil (wy_center + ry - oy)), 0, h - 1)

    inv_rx2 = 1.0 / max(0.01, rx * rx)
    inv_ry2 = 1.0 / max(0.01, ry * ry)
    inv_rz2 = 1.0 / max(0.01, rz * rz)

    for gy in range(y0, y1 + 1):
        wy = oy + gy + 0.5
        dy2 = (wy - wy_center) ** 2 * inv_ry2
        if dy2 > 1.5:
            continue
        for gz in range(z0, z1 + 1):
            wz = oz + gz + 0.5
            dz2 = (wz - wz_center) ** 2 * inv_rz2
            if dy2 + dz2 > 1.5:
                continue
            for gx in range(x0, x1 + 1):
                wx = ox + gx + 0.5
                d = dy2 + dz2 + (wx - wx_center) ** 2 * inv_rx2
                if d > 1.0 + boundary_jitter:
                    continue

                # noise-fray the boundary to avoid perfect ellipsoids
                n = _hash_noise3(seed, int(math.floor(wx)), int(math.floor(wy)), int(math.floor(wz)))
                if d > 1.0 + n * boundary_jitter:
                    continue

                i = _cell_index(gx, gy, gz)
                if grid[i] == 0 or replaceable[i] == 0:
                    continue
                grid[i] = ore_mid

def _depth_weight(world_y: float, center_y: float, spread: float) -> float:
    if spread <= 0.01:
        return 1.0 if abs(world_y - center_y) < 1.0 else 0.0
    t = (world_y - center_y) / spread
    return math.exp(-(t * t))

def _choose_ore_material(
    seed: int,
    depth_y: float,
    local_top_y: float,
    world_y_min: int,
    world_y_max: int,
    ore_mids: dict,
) -> int:
    # Approximate "realistic-ish" biases for showcase preview, not exact vanilla rates.
    # depth_y is world y of deposit center.
    top_rel = local_top_y - depth_y  # cover thickness proxy (bigger = deeper from surface)
    weights = []

    def add(name: str, w: float):
        if w > 0.0001:
            weights.append((name, w))

    # Coal: broad + common, mid/shallow
    add("coal", 0.6 * _depth_weight(depth_y, 60.0, 90.0) + 0.12)

    # Iron: common mid depth
    add("iron", 0.8 * _depth_weight(depth_y, 24.0, 80.0) + 0.08)

    # Copper: favors around y ~40 and shallower stone
    add("copper", 0.7 * _depth_weight(depth_y, 48.0, 70.0) + 0.07)

    # Gold: deeper bias
    add("gold", 0.42 * _depth_weight(depth_y, -24.0, 55.0) + 0.01)

    # Redstone / lapis: deep
    add("redstone", 0.55 * _depth_weight(depth_y, -30.0, 45.0) + 0.01)
    add("lapis", 0.33 * _depth_weight(depth_y, 0.0, 50.0) + 0.01)

    # Diamond: rare, deep
    add("diamond", 0.22 * _depth_weight(depth_y, -44.0, 35.0))

    # Emerald: rare + high terrain proxy (mountain-ish) + mid/high y
    mountain_factor = 0.0
    if local_top_y > 96:
        mountain_factor = min(1.0, (local_top_y - 96.0) / 80.0)
    add("emerald", (0.12 * _depth_weight(depth_y, 28.0, 45.0) + 0.01) * (0.25 + 0.75 * mountain_factor))

    if not weights:
        return ore_mids["iron"]

    total = sum(w for _, w in weights)
    r = _rand_unit(_hash_u32(seed, 0x5EED, int(depth_y * 10))) * total
    acc = 0.0
    for name, w in weights:
        acc += w
        if r <= acc:
            return ore_mids[name]
    return ore_mids[weights[-1][0]]

def _apply_vein_chain(
    grid: List[int], replaceable: List[int], h: int, cx: int, cz: int, min_sy: int,
    wx: float, wy: float, wz: float, ore_mid: int, seed: int,
    base_r: float, length: float, flatten_y: float = 1.0
):
    ang = _rand_unit(_hash_u32(seed, 1)) * (math.pi * 2.0)
    pitch = _rand_signed(_hash_u32(seed, 2)) * 0.35
    dx = math.cos(ang)
    dz = math.sin(ang)
    dy = pitch
    steps = max(2, int(length / max(1.0, base_r)))
    for s in range(steps):
        t = s / float(max(1, steps - 1))
        seg_seed = _hash_u32(seed, 100 + s)
        # slight meander
        wx += dx * (1.5 + 2.0 * _rand_unit(_hash_u32(seg_seed, 11)))
        wz += dz * (1.5 + 2.0 * _rand_unit(_hash_u32(seg_seed, 12)))
        wy += dy * (1.2 + 1.0 * _rand_unit(_hash_u32(seg_seed, 13)))
        dx = math.cos(ang + _rand_signed(_hash_u32(seg_seed, 14)) * 0.35)
        dz = math.sin(ang + _rand_signed(_hash_u32(seg_seed, 15)) * 0.35)
        dy = _clampf(dy + _rand_signed(_hash_u32(seg_seed, 16)) * 0.12, -0.6, 0.6)

        r = base_r * (0.75 + 0.45 * math.sin(t * math.pi))
        rx = r * (0.9 + 0.4 * _rand_unit(_hash_u32(seg_seed, 17)))
        rz = r * (0.9 + 0.4 * _rand_unit(_hash_u32(seg_seed, 18)))
        ry = max(0.75, r * flatten_y * (0.7 + 0.35 * _rand_unit(_hash_u32(seg_seed, 19))))
        _place_ore_irregular_ellipsoid(
            grid, replaceable, h, cx, cz, min_sy,
            wx, wy, wz, rx, ry, rz, ore_mid, _hash_u32(seg_seed, 20),
            boundary_jitter=0.18
        )

def _apply_stockwork(
    grid: List[int], replaceable: List[int], h: int, cx: int, cz: int, min_sy: int,
    wx: float, wy: float, wz: float, ore_mid: int, seed: int, base_r: float, count: int
):
    envelope = base_r * (2.0 + 0.4 * count)
    for n in range(count):
        hs = _hash_u32(seed, n)
        ox = _rand_signed(_hash_u32(hs, 1)) * envelope
        oy = _rand_signed(_hash_u32(hs, 2)) * (envelope * 0.65)
        oz = _rand_signed(_hash_u32(hs, 3)) * envelope
        rr = max(0.8, base_r * (0.55 + 0.75 * _rand_unit(_hash_u32(hs, 4))))
        _place_ore_irregular_ellipsoid(
            grid, replaceable, h, cx, cz, min_sy,
            wx + ox, wy + oy, wz + oz,
            rr * (0.8 + 0.5 * _rand_unit(_hash_u32(hs, 5))),
            rr * (0.6 + 0.4 * _rand_unit(_hash_u32(hs, 6))),
            rr * (0.8 + 0.5 * _rand_unit(_hash_u32(hs, 7))),
            ore_mid, _hash_u32(hs, 8),
            boundary_jitter=0.28
        )

def _paint_strength_pass(seed: int, strength_pct: int, wx: int, wy: int, wz: int) -> bool:
    strength_pct = max(0, min(100, int(strength_pct)))
    if strength_pct >= 100:
        return True
    if strength_pct <= 0:
        return False
    return (_hash_u32(seed, wx, wy, wz) % 100) < strength_pct

def _paint_target_mid(action: str, material: str, reg: MaterialRegistry) -> int:
    a = str(action or '').strip().lower()
    mat = str(material or 'minecraft:stone').strip() or 'minecraft:stone'
    if 'erase' in a or 'carve' in a or mat == 'minecraft:air':
        return 0
    return reg.get_or_create(mat)

def _mirror_points_for_stroke(points: List[Tuple[float, float, float]], mirror: str) -> List[Tuple[float, float, float]]:
    mode = str(mirror or 'None').strip().lower()
    if mode in {'', 'none'}:
        return list(points)
    variants: list[tuple[int, int, int]] = [(1, 1, 1)]
    if 'x+z' in mode:
        variants = [(1,1,1), (-1,1,1), (1,1,-1), (-1,1,-1)]
    elif 'x' in mode:
        variants = [(1,1,1), (-1,1,1)]
    elif 'z' in mode:
        variants = [(1,1,1), (1,1,-1)]
    out: list[tuple[float, float, float]] = []
    seen: set[tuple[int, int, int]] = set()
    for x, y, z in points:
        for sx, sy, sz in variants:
            p = (float(x * sx), float(y * sy), float(z * sz))
            key = (int(round(p[0] * 16.0)), int(round(p[1] * 16.0)), int(round(p[2] * 16.0)))
            if key not in seen:
                seen.add(key)
                out.append(p)
    return out

def _paint_apply_stamp(
    grid: List[int],
    replaceable: List[int],
    h: int,
    cx: int,
    cz: int,
    min_sy: int,
    tops: List[int],
    seed: int,
    stroke: dict,
    reg: MaterialRegistry,
) -> None:
    points_raw = stroke.get('points') or []
    pts: list[tuple[float, float, float]] = []
    for p in points_raw:
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            try:
                pts.append((float(p[0]), float(p[1]), float(p[2])))
            except Exception:
                pass
    if not pts:
        return
    pts = _mirror_points_for_stroke(pts, stroke.get('mirror', 'None'))
    action = str(stroke.get('action', 'Replace blocks'))
    shape = str(stroke.get('shape', 'Sphere')).strip().lower()
    size_blocks = max(1, int(stroke.get('size_blocks', 1)))
    radius = max(0.5, float(size_blocks) * 0.5)
    strength_pct = int(stroke.get('strength_pct', 100))
    host_only = bool(stroke.get('host_only', False))
    protect_surface = bool(stroke.get('protect_surface', False))
    surface_margin = max(0, int(stroke.get('surface_margin', 0)))
    axis_lock = str(stroke.get('axis_lock', 'None')).strip().upper()
    target_mid = _paint_target_mid(action, str(stroke.get('material', 'minecraft:stone')), reg)

    ox = cx * 16
    oz = cz * 16
    oy = min_sy * 16

    def passes(gx: int, gy: int, gz: int, wx: int, wy: int, wz: int) -> bool:
        if gx < 0 or gx > 15 or gz < 0 or gz > 15 or gy < 0 or gy >= h:
            return False
        idx = _cell_index(gx, gy, gz)
        if host_only and grid[idx] != 0 and replaceable[idx] == 0:
            return False
        if protect_surface and not _column_has_cover(tops, gx, gz, gy, surface_margin):
            return False
        return _paint_strength_pass(seed, strength_pct, wx, wy, wz)

    for stamp_i, (wxc, wyc, wzc) in enumerate(pts):
        x0 = _clamp(int(math.floor(wxc - radius - ox)), 0, 15)
        x1 = _clamp(int(math.ceil (wxc + radius - ox)), 0, 15)
        z0 = _clamp(int(math.floor(wzc - radius - oz)), 0, 15)
        z1 = _clamp(int(math.ceil (wzc + radius - oz)), 0, 15)
        y0 = _clamp(int(math.floor(wyc - radius - oy)), 0, h - 1)
        y1 = _clamp(int(math.ceil (wyc + radius - oy)), 0, h - 1)
        if shape == 'disc':
            if axis_lock == 'X':
                x0 = x1 = _clamp(int(round(wxc - ox)), 0, 15)
            elif axis_lock == 'Z':
                z0 = z1 = _clamp(int(round(wzc - oz)), 0, 15)
            else:
                y0 = y1 = _clamp(int(round(wyc - oy)), 0, h - 1)
        r2 = radius * radius
        for gy in range(y0, y1 + 1):
            wy = oy + gy
            for gz in range(z0, z1 + 1):
                wz = oz + gz
                for gx in range(x0, x1 + 1):
                    wx = ox + gx
                    inside = True
                    if shape in {'sphere', 'blob', 'tunnel brush', 'tunnel'}:
                        dx = (wx + 0.5) - float(wxc)
                        dy = (wy + 0.5) - float(wyc)
                        dz = (wz + 0.5) - float(wzc)
                        d2 = dx*dx + dy*dy + dz*dz
                        if shape == 'blob':
                            jitter = 1.0 + 0.20 * _rand_signed(_hash_u32(seed, stamp_i, gx, gy, gz))
                            inside = d2 <= (r2 * max(0.5, jitter))
                        else:
                            inside = d2 <= r2
                    elif shape == 'disc':
                        dx = (wx + 0.5) - float(wxc)
                        dy = (wy + 0.5) - float(wyc)
                        dz = (wz + 0.5) - float(wzc)
                        if axis_lock == 'X':
                            inside = (dy*dy + dz*dz) <= r2
                        elif axis_lock == 'Z':
                            inside = (dx*dx + dy*dy) <= r2
                        else:
                            inside = (dx*dx + dz*dz) <= r2
                    if not inside:
                        continue
                    if not passes(gx, gy, gz, wx, wy, wz):
                        continue
                    idx = _cell_index(gx, gy, gz)
                    grid[idx] = target_mid
                    if target_mid == 0:
                        replaceable[idx] = 0

def _apply_paint_preview_layers(
    grid: List[int],
    replaceable: List[int],
    min_sy: int,
    h: int,
    cx: int,
    cz: int,
    reg: MaterialRegistry,
    preview: dict,
    seed: int,
    tops: List[int],
) -> None:
    layers = preview.get('paint_layers') or []
    for layer_i, layer in enumerate(layers):
        try:
            layer_d = dict(layer or {})
        except Exception:
            continue
        if not bool(layer_d.get('enabled', True)) or not bool(layer_d.get('preview_visible', True)):
            continue
        settings = dict(layer_d.get('settings') or {})
        strokes = list(layer_d.get('strokes') or [])
        for stroke_i, stroke in enumerate(strokes):
            try:
                s = dict(stroke or {})
            except Exception:
                continue
            merged = dict(settings)
            merged.update(s)
            merged_seed = _hash_u32(seed, 0x5041494E, layer_i, stroke_i)
            _paint_apply_stamp(grid, replaceable, h, cx, cz, min_sy, tops, merged_seed, merged, reg)

def _apply_preview_layers(
    grid: List[int],
    replaceable: List[int],
    min_sy: int,
    h: int,
    cx: int,
    cz: int,
    reg: MaterialRegistry,
    preview: dict,
) -> None:
    seed = int(preview.get("seed", 1337))
    if h <= 0:
        return

    # Pre-register preview materials so they appear in block visibility list immediately.
    cave_mid = reg.get_or_create(PREVIEW_CAVE_MARKER)
    ore_mids = {
        "coal": reg.get_or_create("wgl:preview_ore_coal"),
        "iron": reg.get_or_create("wgl:preview_ore_iron"),
        "copper": reg.get_or_create("wgl:preview_ore_copper"),
        "gold": reg.get_or_create("wgl:preview_ore_gold"),
        "redstone": reg.get_or_create("wgl:preview_ore_redstone"),
        "lapis": reg.get_or_create("wgl:preview_ore_lapis"),
        "diamond": reg.get_or_create("wgl:preview_ore_diamond"),
        "emerald": reg.get_or_create("wgl:preview_ore_emerald"),
    }

    world_y_min = min_sy * 16
    world_y_max = world_y_min + h - 1
    tops = _compute_top_heights(grid, h)
    chunk_top_proxy = max(tops) if tops else -1

    def _run_preview_caves() -> None:
            # --- Caves: cell-anchored multi-branch tunnel systems (cross-chunk consistent) ---
            if bool(preview.get("caves_enabled", False)):
                caves_per_chunk = max(0, int(preview.get("caves_per_chunk", 3)))
                cave_radius = max(1, int(preview.get("caves_radius", 3)))
                caves_min_y = max(world_y_min, int(preview.get("caves_min_y", -64)))
                caves_max_y = min(world_y_max, int(preview.get("caves_max_y", 48)))
                marker_mode = bool(preview.get("caves_markers", True))

                # more "realistic" behavior: keep some roof to avoid frequent daylight breaks
                surface_cover_blocks = max(5, int(2 + cave_radius * 2))

                if caves_max_y >= caves_min_y and caves_per_chunk > 0:
                    # Feature density scales with control but is cell-based for chunk continuity.
                    cell_size = 32  # 2 chunks
                    wx0 = cx * 16
                    wz0 = cz * 16
                    wx1 = wx0 + 15
                    wz1 = wz0 + 15
                    cell_x0 = (wx0 // cell_size) - 1
                    cell_x1 = (wx1 // cell_size) + 1
                    cell_z0 = (wz0 // cell_size) - 1
                    cell_z1 = (wz1 // cell_size) + 1

                    # Convert "caves per chunk" to approximate systems per cell
                    base_prob = _clampf(caves_per_chunk / 4.0, 0.20, 1.75)
                    max_systems_per_cell = max(1, min(4, 1 + caves_per_chunk // 3))

                    for cell_z in range(cell_z0, cell_z1 + 1):
                        for cell_x in range(cell_x0, cell_x1 + 1):
                            for sys_i in range(max_systems_per_cell):
                                hs = _hash_u32(seed, 0xCA7E, cell_x, cell_z, sys_i)
                                if _rand_unit(hs) > min(0.95, 0.22 * base_prob + 0.08):
                                    continue

                                # Start point within cell; can span chunks naturally
                                start_x = cell_x * cell_size + _rand_range(_hash_u32(hs, 1), 2, cell_size - 3) + 0.5
                                start_z = cell_z * cell_size + _rand_range(_hash_u32(hs, 2), 2, cell_size - 3) + 0.5
                                start_y = _rand_range(_hash_u32(hs, 3), caves_min_y, caves_max_y) + 0.5

                                # Primary trunk
                                ang = _rand_unit(_hash_u32(hs, 4)) * (math.pi * 2.0)
                                pitch = _rand_signed(_hash_u32(hs, 5)) * 0.25
                                wx = start_x
                                wy = start_y
                                wz = start_z
                                trunk_segments = _rand_range(_hash_u32(hs, 6), 5, 10 + caves_per_chunk)
                                r_prev = float(cave_radius) * (0.95 + 0.25 * _rand_unit(_hash_u32(hs, 7)))

                                branch_budget = _rand_range(_hash_u32(hs, 8), 1, 2 + caves_per_chunk // 3)
                                branch_starts: List[Tuple[float, float, float, float, float]] = []

                                for seg in range(trunk_segments):
                                    hs_seg = _hash_u32(hs, 100 + seg)
                                    step_len = float(_rand_range(_hash_u32(hs_seg, 1), 4, 9))
                                    ang += _rand_signed(_hash_u32(hs_seg, 2)) * 0.42
                                    pitch = _clampf(pitch + _rand_signed(_hash_u32(hs_seg, 3)) * 0.12, -0.55, 0.55)

                                    wx2 = wx + math.cos(ang) * step_len
                                    wy2 = wy + pitch * step_len
                                    wz2 = wz + math.sin(ang) * step_len
                                    # clamp y within cave window +/- some tolerance for natural arches
                                    wy2 = _clampf(wy2, caves_min_y - 6.0, caves_max_y + 6.0)

                                    r_next = float(cave_radius) * (0.75 + 0.65 * _rand_unit(_hash_u32(hs_seg, 4)))
                                    _carve_tunnel_segment(
                                        grid, replaceable, h, cx, cz, min_sy, tops, cave_mid, marker_mode,
                                        wx, wy, wz, wx2, wy2, wz2, r_prev, r_next,
                                        seed=_hash_u32(hs_seg, 5), min_cover=surface_cover_blocks
                                    )

                                    # occasional chamber
                                    chamber_roll = _rand_unit(_hash_u32(hs_seg, 6))
                                    if chamber_roll < (0.10 + 0.03 * min(6, caves_per_chunk)):
                                        chamber_r = r_next * (1.6 + 1.4 * _rand_unit(_hash_u32(hs_seg, 7)))
                                        _carve_or_mark_sphere(
                                            grid, replaceable, h, cx, cz, min_sy,
                                            wx2, wy2, wz2, chamber_r, cave_mid, marker_mode,
                                            tops=tops, min_cover=max(4, surface_cover_blocks - 2),
                                            irregular_seed=_hash_u32(hs_seg, 8), irregularity=0.28
                                        )

                                    # save branch seed points
                                    if branch_budget > 0 and _rand_unit(_hash_u32(hs_seg, 9)) < 0.22:
                                        branch_starts.append((wx2, wy2, wz2, ang, r_next))
                                        branch_budget -= 1

                                    wx, wy, wz = wx2, wy2, wz2
                                    r_prev = r_next

                                # branches
                                for bi, (bx, by, bz, bang, br) in enumerate(branch_starts):
                                    hb = _hash_u32(hs, 500 + bi)
                                    ang = bang + _rand_signed(_hash_u32(hb, 1)) * 1.2
                                    pitch = _rand_signed(_hash_u32(hb, 2)) * 0.25
                                    segs = _rand_range(_hash_u32(hb, 3), 3, 7)
                                    r_prev_b = max(1.1, br * (0.6 + 0.25 * _rand_unit(_hash_u32(hb, 4))))
                                    wxb, wyb, wzb = bx, by, bz
                                    for s in range(segs):
                                        hbs = _hash_u32(hb, 20 + s)
                                        step_len = float(_rand_range(_hash_u32(hbs, 1), 3, 7))
                                        ang += _rand_signed(_hash_u32(hbs, 2)) * 0.65
                                        pitch = _clampf(pitch + _rand_signed(_hash_u32(hbs, 3)) * 0.16, -0.65, 0.65)
                                        wx2 = wxb + math.cos(ang) * step_len
                                        wy2 = _clampf(wyb + pitch * step_len, caves_min_y - 4.0, caves_max_y + 4.0)
                                        wz2 = wzb + math.sin(ang) * step_len
                                        r_next_b = max(0.9, r_prev_b * (0.78 + 0.18 * _rand_unit(_hash_u32(hbs, 4))))
                                        _carve_tunnel_segment(
                                            grid, replaceable, h, cx, cz, min_sy, tops, cave_mid, marker_mode,
                                            wxb, wyb, wzb, wx2, wy2, wz2, r_prev_b, r_next_b,
                                            seed=_hash_u32(hbs, 5), min_cover=surface_cover_blocks
                                        )
                                        wxb, wyb, wzb = wx2, wy2, wz2
                                        r_prev_b = r_next_b

    def _run_preview_ores() -> None:
            # --- Ores: mixed deposit styles (veins/lenses/stockwork), cell-anchored for continuity ---
            if bool(preview.get("ores_enabled", False)):
                ores_per_chunk = max(0, int(preview.get("ores_per_chunk", 10)))
                ore_radius = max(1, int(preview.get("ores_radius", 2)))
                ores_min_y = max(world_y_min, int(preview.get("ores_min_y", -48)))
                ores_max_y = min(world_y_max, int(preview.get("ores_max_y", 64)))

                if ores_max_y >= ores_min_y and ores_per_chunk > 0:
                    wx0 = cx * 16
                    wz0 = cz * 16
                    wx1 = wx0 + 15
                    wz1 = wz0 + 15

                    # 24-block cell makes deposits cross chunk seams often but not too many checks.
                    cell_size = 24
                    cell_x0 = (wx0 // cell_size) - 1
                    cell_x1 = (wx1 // cell_size) + 1
                    cell_z0 = (wz0 // cell_size) - 1
                    cell_z1 = (wz1 // cell_size) + 1

                    density = _clampf(ores_per_chunk / 10.0, 0.2, 4.0)
                    max_deposits_per_cell = max(1, min(8, 2 + ores_per_chunk // 4))
                    deposit_prob = min(0.97, 0.18 + 0.16 * density)

                    for cell_z in range(cell_z0, cell_z1 + 1):
                        for cell_x in range(cell_x0, cell_x1 + 1):
                            for dep_i in range(max_deposits_per_cell):
                                hs = _hash_u32(seed, 0x0E05, cell_x, cell_z, dep_i)
                                if _rand_unit(hs) > deposit_prob:
                                    continue

                                wx = cell_x * cell_size + _rand_range(_hash_u32(hs, 1), 0, cell_size - 1) + 0.5
                                wz = cell_z * cell_size + _rand_range(_hash_u32(hs, 2), 0, cell_size - 1) + 0.5
                                wy = _rand_range(_hash_u32(hs, 3), ores_min_y, ores_max_y) + 0.5

                                # Estimate local terrain height proxy using nearest column inside this chunk when possible.
                                lx = _clamp(int(math.floor(wx - wx0)), 0, 15)
                                lz = _clamp(int(math.floor(wz - wz0)), 0, 15)
                                lt = tops[lz * 16 + lx] if tops else -1
                                local_top_y_world = (world_y_min + lt) if lt >= 0 else (chunk_top_proxy if chunk_top_proxy >= 0 else world_y_max)

                                ore_mid = _choose_ore_material(_hash_u32(hs, 4), wy, float(local_top_y_world), world_y_min, world_y_max, ore_mids)

                                # Style selection (realistic-ish mixed deposits)
                                style_roll = _rand_unit(_hash_u32(hs, 5))
                                base_r = float(ore_radius) * (0.8 + 0.8 * _rand_unit(_hash_u32(hs, 6)))

                                # Bias style by ore type / depth
                                if ore_mid in (ore_mids["redstone"], ore_mids["lapis"]):
                                    style_roll = min(style_roll, 0.55)  # flatter/lens/vein more often
                                if ore_mid == ore_mids["diamond"]:
                                    style_roll = 0.60 + 0.39 * style_roll  # smaller chain/cluster style

                                if style_roll < 0.28:
                                    # Lens / pod
                                    rx = base_r * (1.1 + 0.8 * _rand_unit(_hash_u32(hs, 7)))
                                    rz = base_r * (1.1 + 0.8 * _rand_unit(_hash_u32(hs, 8)))
                                    ry = max(0.75, base_r * (0.45 + 0.35 * _rand_unit(_hash_u32(hs, 9))))
                                    _place_ore_irregular_ellipsoid(
                                        grid, replaceable, h, cx, cz, min_sy,
                                        wx, wy, wz, rx, ry, rz, ore_mid, _hash_u32(hs, 10),
                                        boundary_jitter=0.24
                                    )
                                elif style_roll < 0.70:
                                    # Vein chain
                                    flatten_y = 0.75 if ore_mid in (ore_mids["redstone"], ore_mids["lapis"]) else 1.0
                                    if ore_mid == ore_mids["copper"]:
                                        flatten_y = 0.55
                                    length = 7.0 + (6.0 * density) + 8.0 * _rand_unit(_hash_u32(hs, 11))
                                    if ore_mid == ore_mids["diamond"]:
                                        length *= 0.6
                                    _apply_vein_chain(
                                        grid, replaceable, h, cx, cz, min_sy,
                                        wx, wy, wz, ore_mid, _hash_u32(hs, 12),
                                        base_r=max(0.9, base_r), length=length, flatten_y=flatten_y
                                    )
                                else:
                                    # Stockwork / fracture network
                                    count = _rand_range(_hash_u32(hs, 13), 3, 7 + int(density))
                                    if ore_mid == ore_mids["diamond"]:
                                        count = _rand_range(_hash_u32(hs, 14), 2, 4)
                                    _apply_stockwork(
                                        grid, replaceable, h, cx, cz, min_sy,
                                        wx, wy, wz, ore_mid, _hash_u32(hs, 15),
                                        base_r=max(0.8, base_r * 0.85), count=count
                                    )

    # Optional UI-driven order from the layer stack (top -> bottom).
    # Supported entries: "gen:caves" / "gen:ores" (or shorthand cave/ore labels).
    order_raw = preview.get("preview_layer_order") or preview.get("layer_order") or []
    order_ops: list[str] = []
    try:
        iterable = list(order_raw)
    except Exception:
        iterable = []
    for item in iterable:
        key = ""
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("id") or item.get("name") or "").strip().lower()
        else:
            key = str(item).strip().lower()
        if key in {"gen:caves", "caves", "cave"}:
            if "caves" not in order_ops:
                order_ops.append("caves")
        elif key in {"gen:ores", "ores", "ore"}:
            if "ores" not in order_ops:
                order_ops.append("ores")

    if not order_ops:
        # Preserve legacy preview behavior if no explicit layer order is provided.
        order_ops = ["caves", "ores"]

    seen_ops: set[str] = set()
    for op in order_ops:
        if op in seen_ops:
            continue
        seen_ops.add(op)
        if op == "caves":
            _run_preview_caves()
        elif op == "ores":
            _run_preview_ores()

    # If UI omitted an enabled generator row (e.g., hidden layer list edge-case), still evaluate it.
    if "caves" not in seen_ops:
        _run_preview_caves()
    if "ores" not in seen_ops:
        _run_preview_ores()

    _apply_paint_preview_layers(grid, replaceable, min_sy, h, cx, cz, reg, preview, seed, tops)
