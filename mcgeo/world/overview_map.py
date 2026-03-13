from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Optional

from .region import RegionFile
from .anvil_reader import AnvilWorld


@dataclass(frozen=True)
class OverviewRaster:
    min_cx: int
    max_cx: int
    min_cz: int
    max_cz: int
    width_px: int
    height_px: int
    scale_chunks_per_px: int
    occupancy_counts: bytes  # row-major byte counts (0..255)
    total_present_chunks: int
    # Optional coarse top-surface color guide (row-major RGB bytes).
    surface_width_px: int = 0
    surface_height_px: int = 0
    surface_scale_chunks_per_px: int = 0
    surface_rgb: bytes = b""
    surface_valid: bytes = b""


# Small deterministic surface palette for common blocks; unknowns hash to a stable color.
_SURFACE_RGB = {
    "minecraft:grass_block": (95, 159, 53),
    "minecraft:dirt": (134, 96, 67),
    "minecraft:stone": (125, 125, 125),
    "minecraft:deepslate": (70, 70, 75),
    "minecraft:sand": (219, 211, 160),
    "minecraft:red_sand": (201, 110, 62),
    "minecraft:water": (64, 96, 220),
    "minecraft:lava": (240, 110, 20),
    "minecraft:bedrock": (35, 35, 35),
    "minecraft:oak_log": (102, 81, 51),
    "minecraft:birch_log": (206, 194, 147),
    "minecraft:spruce_log": (88, 68, 46),
    "minecraft:jungle_log": (137, 99, 67),
    "minecraft:oak_leaves": (74, 132, 52),
    "minecraft:birch_leaves": (106, 154, 69),
    "minecraft:spruce_leaves": (56, 100, 54),
    "minecraft:snow": (245, 245, 245),
    "minecraft:snow_block": (240, 240, 240),
    "minecraft:ice": (170, 200, 240),
    "minecraft:packed_ice": (155, 190, 236),
    "minecraft:blue_ice": (123, 162, 232),
    "minecraft:netherrack": (110, 50, 52),
    "minecraft:basalt": (71, 71, 76),
    "minecraft:blackstone": (52, 49, 56),
    "minecraft:end_stone": (219, 223, 158),
}


def _name_to_rgb(block_name: str) -> tuple[int, int, int]:
    rgb = _SURFACE_RGB.get(block_name)
    if rgb:
        return rgb
    h = hashlib.md5(block_name.encode("utf-8")).digest()
    return (40 + h[0] % 160, 40 + h[1] % 160, 40 + h[2] % 160)


def _emit_progress(progress_cb: Optional[Callable[[int, int, str], None]], done: int, total: int, message: str) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(int(done), int(total), str(message))
    except Exception:
        pass


def _surface_sample_batch(args):
    """Worker helper for coarse surface guide sampling.

    Args tuple = (world_path_str, jobs) where jobs is list[(index, cx, cz)].
    Returns list[(index, r, g, b, valid)].
    """
    world_path_str, jobs = args
    world = AnvilWorld(Path(world_path_str))
    out = []
    pts = ((8, 8), (4, 4), (12, 4), (4, 12), (12, 12))
    for i, cx, cz in jobs:
        try:
            chunk = world.read_chunk(int(cx), int(cz))
        except Exception:
            chunk = None
        if chunk is None:
            out.append((int(i), 0, 0, 0, 0))
            continue
        rs = gs = bs = n = 0
        for x, z in pts:
            _y, name = chunk.find_surface_block(x, z)
            if not name or name == "minecraft:air":
                continue
            r, g, b = _name_to_rgb(name)
            rs += r; gs += g; bs += b; n += 1
        if n <= 0:
            out.append((int(i), 0, 0, 0, 0))
            continue
        out.append((int(i), int(rs / n), int(gs / n), int(bs / n), 1))
    return out


def _scan_region_batch(args):
    """Worker helper for the detailed 2D overview occupancy + representative chunk scan.

    Returns:
      (occupancy_bytes, total_present_chunks, representative_cells)
    where representative_cells is list[(surface_index, rank, cx, cz)].
    """
    (
        entries,
        min_cx,
        max_cx,
        min_cz,
        max_cz,
        width_px,
        height_px,
        scale,
        surf_w,
        surf_h,
        surface_scale,
    ) = args

    bins = bytearray(int(width_px) * int(height_px))
    reps: dict[int, tuple[int, int, int]] = {}
    total_present = 0

    for region_rank, path_str in entries:
        p = Path(path_str)
        parts = p.name.split('.')
        if len(parts) != 4 or parts[0] != 'r' or parts[3] != 'mca':
            continue
        try:
            rx = int(parts[1])
            rz = int(parts[2])
        except Exception:
            continue
        try:
            with RegionFile(p) as reg:
                for lz in range(32):
                    for lx in range(32):
                        if not reg.has_chunk(lx, lz):
                            continue
                        total_present += 1
                        cx = rx * 32 + lx
                        cz = rz * 32 + lz
                        if cx < min_cx or cx > max_cx or cz < min_cz or cz > max_cz:
                            continue

                        px = (cx - min_cx) // scale
                        pz = (cz - min_cz) // scale
                        if 0 <= px < width_px and 0 <= pz < height_px:
                            idx = int(pz * width_px + px)
                            v = bins[idx]
                            if v < 255:
                                bins[idx] = v + 1

                        sx = (cx - min_cx) // surface_scale
                        sz = (cz - min_cz) // surface_scale
                        if 0 <= sx < surf_w and 0 <= sz < surf_h:
                            sidx = int(sz * surf_w + sx)
                            rank = int(region_rank) * 1024 + (lz * 32 + lx)
                            prev = reps.get(sidx)
                            if prev is None or rank < prev[0]:
                                reps[sidx] = (rank, int(cx), int(cz))
        except Exception:
            # Keep dialog robust even if a region file is malformed.
            continue

    return bytes(bins), int(total_present), [(int(i), int(rank), int(cx), int(cz)) for i, (rank, cx, cz) in reps.items()]


def _surface_workers_auto(job_count: int) -> int:
    env = os.environ.get('MCGEO_OVERVIEW_WORKERS', '').strip()
    if env:
        try:
            return max(1, min(int(env), max(1, job_count)))
        except Exception:
            pass
    cpu = max(1, (os.cpu_count() or 1))
    # Leave one core for UI/OS but still push CPU harder than a single-threaded pass.
    return max(1, min(job_count, max(1, cpu - 1)))


def _overview_workers_auto(region_count: int) -> int:
    return _surface_workers_auto(region_count)


def build_chunk_coverage_raster(world_index, max_dim_px: int = 1024, progress_cb=None) -> OverviewRaster:
    """Build a top-down project-area raster.

    Fast path: scans region headers/chunk presence across the world using broad CPU parallelism.
    Optional coarse surface-color guide: decodes a capped number of representative chunks
    and samples their top surface blocks to give the user a rough idea of where they are.
    """
    min_cx, max_cx, min_cz, max_cz = [int(v) for v in world_index.chunk_bounds]
    chunk_w = max(1, max_cx - min_cx + 1)
    chunk_h = max(1, max_cz - min_cz + 1)
    max_dim_px = max(64, int(max_dim_px))
    scale = max(1, (max(chunk_w, chunk_h) + max_dim_px - 1) // max_dim_px)
    width_px = max(1, (chunk_w + scale - 1) // scale)
    height_px = max(1, (chunk_h + scale - 1) // scale)

    bins = bytearray(width_px * height_px)
    total_present = 0

    # Coarse "top layer" guide: keep sample count bounded.
    target_surface_samples = 12_000
    surface_scale = max(
        scale,
        int(math.ceil(math.sqrt((chunk_w * chunk_h) / float(max(1, target_surface_samples)))))
    )
    surf_w = max(1, (chunk_w + surface_scale - 1) // surface_scale)
    surf_h = max(1, (chunk_h + surface_scale - 1) // surface_scale)
    rep_rank = [None] * (surf_w * surf_h)
    rep_cx = [None] * (surf_w * surf_h)
    rep_cz = [None] * (surf_w * surf_h)

    region_dir = Path(world_index.region_dir)
    region_entries: list[tuple[int, str]] = []
    for rp in sorted(region_dir.glob('r.*.*.mca'), key=lambda p: p.name):
        name = rp.name
        parts = name.split('.')
        if len(parts) != 4 or parts[0] != 'r' or parts[3] != 'mca':
            continue
        try:
            rx = int(parts[1]); rz = int(parts[2])
        except Exception:
            continue
        region_entries.append((len(region_entries), str(rp)))

    stage1_total = max(1, len(region_entries))
    _emit_progress(progress_cb, 0, stage1_total, f"Building detailed 2D world map… stage 1/2 • scanning 0/{len(region_entries)} region files")

    if region_entries:
        workers = _overview_workers_auto(len(region_entries))
        target_batches = max(1, workers * 2)
        batch_size = max(1, min(32, (len(region_entries) + target_batches - 1) // target_batches))
        batches = [
            (
                region_entries[i:i + batch_size],
                min_cx, max_cx, min_cz, max_cz,
                width_px, height_px, scale,
                surf_w, surf_h, surface_scale,
            )
            for i in range(0, len(region_entries), batch_size)
        ]

        done_regions = 0
        if workers <= 1 or len(batches) <= 1:
            for batch in batches:
                part_bins, part_total, part_reps = _scan_region_batch(batch)
                total_present += int(part_total)
                mv = memoryview(part_bins)
                for idx in range(len(bins)):
                    if mv[idx]:
                        bins[idx] = min(255, bins[idx] + int(mv[idx]))
                for sidx, rank, cx, cz in part_reps:
                    prev_rank = rep_rank[sidx]
                    if prev_rank is None or int(rank) < int(prev_rank):
                        rep_rank[sidx] = int(rank)
                        rep_cx[sidx] = int(cx)
                        rep_cz[sidx] = int(cz)
                done_regions += len(batch[0])
                _emit_progress(progress_cb, done_regions, stage1_total, f"Building detailed 2D world map… stage 1/2 • scanned {done_regions}/{len(region_entries)} region files")
        else:
            try:
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    futs = {ex.submit(_scan_region_batch, batch): batch for batch in batches}
                    for fut in as_completed(futs):
                        batch = futs[fut]
                        part_bins, part_total, part_reps = fut.result()
                        total_present += int(part_total)
                        mv = memoryview(part_bins)
                        for idx in range(len(bins)):
                            if mv[idx]:
                                bins[idx] = min(255, bins[idx] + int(mv[idx]))
                        for sidx, rank, cx, cz in part_reps:
                            prev_rank = rep_rank[sidx]
                            if prev_rank is None or int(rank) < int(prev_rank):
                                rep_rank[sidx] = int(rank)
                                rep_cx[sidx] = int(cx)
                                rep_cz[sidx] = int(cz)
                        done_regions += len(batch[0])
                        _emit_progress(progress_cb, done_regions, stage1_total, f"Building detailed 2D world map… stage 1/2 • scanned {done_regions}/{len(region_entries)} region files")
            except Exception:
                for batch in batches:
                    part_bins, part_total, part_reps = _scan_region_batch(batch)
                    total_present += int(part_total)
                    mv = memoryview(part_bins)
                    for idx in range(len(bins)):
                        if mv[idx]:
                            bins[idx] = min(255, bins[idx] + int(mv[idx]))
                    for sidx, rank, cx, cz in part_reps:
                        prev_rank = rep_rank[sidx]
                        if prev_rank is None or int(rank) < int(prev_rank):
                            rep_rank[sidx] = int(rank)
                            rep_cx[sidx] = int(cx)
                            rep_cz[sidx] = int(cz)
                    done_regions += len(batch[0])
                    _emit_progress(progress_cb, done_regions, stage1_total, f"Building detailed 2D world map… stage 1/2 • scanned {done_regions}/{len(region_entries)} region files")

    surf_rgb = bytearray(surf_w * surf_h * 3)
    surf_valid = bytearray(surf_w * surf_h)
    try:
        jobs = [(i, int(rep_cx[i]), int(rep_cz[i])) for i in range(surf_w * surf_h) if rep_cx[i] is not None and rep_cz[i] is not None]
        stage2_total = max(1, len(jobs))
        _emit_progress(progress_cb, 0, stage2_total, f"Building detailed 2D world map… stage 2/2 • sampling 0/{len(jobs)} representative chunks")
        if jobs:
            workers = _surface_workers_auto(len(jobs))
            # Batch jobs to reduce multiprocessing overhead while still spreading work broadly.
            target_batches = max(workers, workers * 3)
            batch_size = max(8, min(128, (len(jobs) + target_batches - 1) // target_batches))
            batches = [(str(world_index.world_path), jobs[i:i + batch_size]) for i in range(0, len(jobs), batch_size)]

            done_jobs = 0
            if workers <= 1 or len(batches) <= 1:
                for b in batches:
                    rows = _surface_sample_batch(b)
                    for i, r1, g1, b1, valid in rows:
                        if not valid:
                            continue
                        surf_rgb[i * 3 + 0] = r1
                        surf_rgb[i * 3 + 1] = g1
                        surf_rgb[i * 3 + 2] = b1
                        surf_valid[i] = 1
                    done_jobs += len(b[1])
                    _emit_progress(progress_cb, done_jobs, stage2_total, f"Building detailed 2D world map… stage 2/2 • sampled {done_jobs}/{len(jobs)} representative chunks")
            else:
                try:
                    with ProcessPoolExecutor(max_workers=workers) as ex:
                        futs = {ex.submit(_surface_sample_batch, b): b for b in batches}
                        for fut in as_completed(futs):
                            batch = futs[fut]
                            for i, r1, g1, b1, valid in fut.result():
                                if not valid:
                                    continue
                                surf_rgb[i * 3 + 0] = r1
                                surf_rgb[i * 3 + 1] = g1
                                surf_rgb[i * 3 + 2] = b1
                                surf_valid[i] = 1
                            done_jobs += len(batch[1])
                            _emit_progress(progress_cb, done_jobs, stage2_total, f"Building detailed 2D world map… stage 2/2 • sampled {done_jobs}/{len(jobs)} representative chunks")
                except Exception:
                    world = AnvilWorld(Path(world_index.world_path))
                    pts = ((8, 8), (4, 4), (12, 4), (4, 12), (12, 12))
                    for i, cx, cz in jobs:
                        chunk = world.read_chunk(int(cx), int(cz))
                        if chunk is None:
                            continue
                        rs = gs = bs = n = 0
                        for x, z in pts:
                            _y, name = chunk.find_surface_block(x, z)
                            if not name or name == "minecraft:air":
                                continue
                            r, g, b = _name_to_rgb(name)
                            rs += r; gs += g; bs += b; n += 1
                        if n <= 0:
                            continue
                        surf_rgb[i * 3 + 0] = int(rs / n)
                        surf_rgb[i * 3 + 1] = int(gs / n)
                        surf_rgb[i * 3 + 2] = int(bs / n)
                        surf_valid[i] = 1
                        done_jobs += 1
                        _emit_progress(progress_cb, done_jobs, stage2_total, f"Building detailed 2D world map… stage 2/2 • sampled {done_jobs}/{len(jobs)} representative chunks")
        else:
            _emit_progress(progress_cb, stage2_total, stage2_total, "Building detailed 2D world map… stage 2/2 • no representative chunks to sample")
    except Exception:
        # If surface sampling fails, the occupancy heatmap remains usable.
        surf_rgb = bytearray()
        surf_valid = bytearray()
        surf_w = surf_h = 0
        surface_scale = 0

    return OverviewRaster(
        min_cx=min_cx,
        max_cx=max_cx,
        min_cz=min_cz,
        max_cz=max_cz,
        width_px=width_px,
        height_px=height_px,
        scale_chunks_per_px=scale,
        occupancy_counts=bytes(bins),
        total_present_chunks=total_present,
        surface_width_px=surf_w,
        surface_height_px=surf_h,
        surface_scale_chunks_per_px=int(surface_scale),
        surface_rgb=bytes(surf_rgb),
        surface_valid=bytes(surf_valid),
    )
