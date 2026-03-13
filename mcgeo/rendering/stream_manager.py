from __future__ import annotations
import concurrent.futures as cf
import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, Set, List, Optional, Iterable

from PySide6 import QtCore

from ..world.anvil_reader import AnvilWorld
from .mesh_builder import build_chunk_mesh, MeshData
from .materials import MaterialRegistry

log = logging.getLogger("mcgeo.render.stream")


@dataclass(frozen=True)
class ChunkKey:
    cx: int
    cz: int


def chebyshev_dist(a: ChunkKey, b: ChunkKey) -> int:
    return max(abs(a.cx - b.cx), abs(a.cz - b.cz))


def _preview_has_effects(preview_settings: Optional[dict]) -> bool:
    d = dict(preview_settings or {})
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
        if not bool(ld.get("enabled", True)) or not bool(ld.get("preview_visible", True)):
            continue
        strokes = ld.get("strokes") or []
        if strokes:
            return True
    return False


def _stable_preview_signature(preview_settings: Optional[dict]) -> str:
    """Stable signature for preview settings; surface LOD ignores this."""
    d = dict(preview_settings or {})
    if not _preview_has_effects(d):
        return "preview:off"
    try:
        payload = json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        payload = repr(sorted(d.items()))
    h = hashlib.sha1(payload.encode("utf-8", "replace")).hexdigest()[:16]
    return f"preview:on:{h}"


# ---------------- worker-process caches (persistent per process) ----------------

_PROC_WORLD_CACHE: dict[str, AnvilWorld] = {}
_PROC_MESH_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_PROC_MESH_CACHE_LIMIT = 512


def _proc_lru_get(key):
    hit = _PROC_MESH_CACHE.get(key)
    if hit is None:
        return None
    _PROC_MESH_CACHE.move_to_end(key)
    return hit


def _proc_lru_put(key, value):
    _PROC_MESH_CACHE[key] = value
    _PROC_MESH_CACHE.move_to_end(key)
    while len(_PROC_MESH_CACHE) > _PROC_MESH_CACHE_LIMIT:
        _PROC_MESH_CACHE.popitem(last=False)


def _process_build_task(world_path_str: str, cx: int, cz: int, lod: str,
                        preview_settings: Optional[dict] = None, preview_sig: Optional[str] = None):
    """
    Worker-process task. Builds mesh with a local material registry, then returns:
      - local material names (id -> name) for remapping on the main process
      - mesh bytes / count
    Uses a small per-process mesh/result cache so camera churn and repeated preview toggles are faster.
    """
    try:
        psig = str(preview_sig or _stable_preview_signature(preview_settings))
        cache_key = (world_path_str, int(cx), int(cz), str(lod), psig if lod == "voxel" else "surface")
        cached = _proc_lru_get(cache_key)
        if cached is not None:
            out = dict(cached)
            out["cache_hit"] = True
            return out

        world = _PROC_WORLD_CACHE.get(world_path_str)
        if world is None:
            world = AnvilWorld(Path(world_path_str))
            _PROC_WORLD_CACHE[world_path_str] = world

        local_reg = MaterialRegistry()
        chunk = world.read_chunk(cx, cz)
        mesh = build_chunk_mesh(chunk, cx, cz, lod, local_reg, preview=preview_settings)
        local_names = ["minecraft:air"] + local_reg.names()
        result = {
            "ok": True,
            "cx": cx,
            "cz": cz,
            "lod": lod,
            "vertex_count": int(mesh.vertex_count),
            "vertices": mesh.vertices,
            "local_names": local_names,
            "top_heights": list(mesh.top_heights or ()),
            "err": "",
            "preview_sig": psig,
            "cache_hit": False,
        }
        _proc_lru_put(cache_key, result)
        return result
    except Exception as e:
        return {
            "ok": False,
            "cx": cx,
            "cz": cz,
            "lod": lod,
            "vertex_count": 0,
            "vertices": b"",
            "local_names": ["minecraft:air"],
            "err": str(e),
            "preview_sig": str(preview_sig or ""),
            "cache_hit": False,
        }


class StreamManager(QtCore.QObject):
    mesh_ready = QtCore.Signal(int, int, object)  # cx,cz,MeshData
    stats = QtCore.Signal(int, int)               # resident, inflight
    materials_changed = QtCore.Signal(object)     # list[str]

    def __init__(self, world_path, near_ring: int = 4, workers: int = 0, preview_settings: Optional[dict] = None) -> None:
        super().__init__()
        self.world_path = Path(world_path)
        self.world = AnvilWorld(self.world_path)
        self.registry = MaterialRegistry()
        self.near_ring = near_ring
        self.workers = int(workers or max(1, (os.cpu_count() or 4)))
        self.max_schedule_per_update = max(128, self.workers * 32)
        self.preview_settings: dict = dict(preview_settings or {})
        self._preview_sig = _stable_preview_signature(self.preview_settings)
        self._allowed_chunk_bounds: tuple[int, int, int, int] | None = None
        # Background cache warming for the selected edit area (improves first-time camera travel).
        self._prefetch_enabled = True
        self._prefetch_budget_per_update = 32
        self._prefetch_cursor: tuple[int, int] | None = None
        # Selected-area workflow: keep the whole allowed area visible after preload.
        self._render_all_allowed_area = True

        # Process-only backend (user-requested; no Qt thread fallback)
        self._backend = "processes"
        self._executor_processes: Optional[_ProcessExecutor] = None

        self._lock = threading.Lock()
        self._target = ChunkKey(0, 0)
        self._resident_lod: Dict[ChunkKey, str] = {}
        self._inflight: Set[Tuple[int, int, str]] = set()
        self._last_mat_version = 0
        self._epoch = 0  # executor reset / hard invalidate generation

        # In-memory mesh caches in UI process (survive ring churn and preview edits)
        self.base_mesh_cache_limit = 4096
        self.preview_mesh_cache_limit = 4096
        self._base_mesh_cache: "OrderedDict[tuple[int,int,str], MeshData]" = OrderedDict()
        self._preview_mesh_cache: "OrderedDict[tuple[int,int,str,str], MeshData]" = OrderedDict()

        self._cache_stats = {
            "base_hits": 0,
            "base_misses": 0,
            "preview_hits": 0,
            "preview_misses": 0,
            "process_cache_hits": 0,
            "process_cache_misses": 0,
        }

        self._reset_executors(clear_inflight=False)

        log.info(
            "StreamManager backend=%s workers=%d initial_schedule_budget=%d near=%d base_cache=%d preview_cache=%d",
            self._backend, self.workers, self.max_schedule_per_update, self.near_ring,
            self.base_mesh_cache_limit, self.preview_mesh_cache_limit
        )

    @property
    def backend(self) -> str:
        return self._backend

    def set_backend(self, backend: str) -> None:
        """Process-only backend. Kept for UI/API compatibility."""
        if str(backend).lower().startswith("proc"):
            return
        log.info("Ignoring backend=%s request; ProcessPool backend is fixed in this build", backend)

    def set_workers(self, workers: int) -> None:
        workers = max(1, int(workers))
        if workers == self.workers:
            return
        self.workers = workers
        self._reset_executors(clear_inflight=True)
        log.info("StreamManager workers set to %d", workers)

    def set_rings(self, near_ring: int, *_ignored) -> None:
        self.near_ring = max(1, int(near_ring))
        log.info("StreamManager rings updated: near=%d (voxel)", self.near_ring)

    def set_schedule_budget(self, budget: int) -> None:
        self.max_schedule_per_update = max(1, int(budget))
        log.info("StreamManager schedule budget set to %d", self.max_schedule_per_update)
    def set_render_all_allowed_area(self, enabled: bool) -> None:
        self._render_all_allowed_area = bool(enabled)
        log.info("StreamManager render_all_allowed_area=%s", self._render_all_allowed_area)


    def set_cache_limits(self, base_mesh_entries: Optional[int] = None, preview_mesh_entries: Optional[int] = None) -> None:
        changed = False
        if base_mesh_entries is not None:
            n = max(128, int(base_mesh_entries))
            if n != self.base_mesh_cache_limit:
                self.base_mesh_cache_limit = n
                changed = True
        if preview_mesh_entries is not None:
            n = max(128, int(preview_mesh_entries))
            if n != self.preview_mesh_cache_limit:
                self.preview_mesh_cache_limit = n
                changed = True
        if changed:
            self._trim_caches()
            log.info("StreamManager cache limits updated: base=%d preview=%d", self.base_mesh_cache_limit, self.preview_mesh_cache_limit)

    def get_cache_stats(self) -> dict:
        return {
            **self._cache_stats,
            "base_cache_entries": len(self._base_mesh_cache),
            "preview_cache_entries": len(self._preview_mesh_cache),
            "base_cache_limit": int(self.base_mesh_cache_limit),
            "preview_cache_limit": int(self.preview_mesh_cache_limit),
        }

    def reset_cache_stats(self) -> None:
        for k in list(self._cache_stats.keys()):
            self._cache_stats[k] = 0

    def set_preview_settings(self, preview_settings: Optional[dict]) -> None:
        new_settings = dict(preview_settings or {})
        new_sig = _stable_preview_signature(new_settings)
        if new_settings == self.preview_settings and new_sig == self._preview_sig:
            return
        self.preview_settings = new_settings
        old_sig = self._preview_sig
        self._preview_sig = new_sig
        # Preserve base world and surface ring work. Only preview-sensitive voxel chunks are invalidated.
        self.invalidate_preview_only()
        log.info("StreamManager preview settings updated (sig %s -> %s); preserving base caches", old_sig, new_sig)

    def invalidate_preview_only(self, affected_chunks: Optional[Iterable[tuple[int, int] | ChunkKey]] = None) -> None:
        chunk_filter: Optional[set[tuple[int, int]]] = None
        if affected_chunks is not None:
            chunk_filter = set()
            for c in affected_chunks:
                try:
                    if isinstance(c, ChunkKey):
                        chunk_filter.add((int(c.cx), int(c.cz)))
                    else:
                        cx, cz = c  # type: ignore[misc]
                        chunk_filter.add((int(cx), int(cz)))
                except Exception:
                    continue

        with self._lock:
            if chunk_filter is None:
                self._resident_lod = {k: v for k, v in self._resident_lod.items() if v != "voxel"}
                self._inflight = {t for t in self._inflight if t[2] != "voxel"}
            else:
                self._resident_lod = {
                    k: v for k, v in self._resident_lod.items()
                    if not (v == "voxel" and (k.cx, k.cz) in chunk_filter)
                }
                self._inflight = {
                    t for t in self._inflight
                    if not (t[2] == "voxel" and (t[0], t[1]) in chunk_filter)
                }

    def invalidate_all(self, drop_caches: bool = False) -> None:
        # Drop resident/inflight bookkeeping; stale process callbacks are ignored via epoch.
        self._epoch += 1
        with self._lock:
            self._resident_lod.clear()
            self._inflight.clear()
        if drop_caches:
            self.clear_mesh_caches()

    def clear_mesh_caches(self) -> None:
        self._base_mesh_cache.clear()
        self._preview_mesh_cache.clear()
        self.reset_cache_stats()
        log.info("StreamManager mesh caches cleared")

    def _reset_executors(self, clear_inflight: bool = False) -> None:
        self._epoch += 1
        if self._executor_processes is not None:
            try:
                self._executor_processes.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._executor_processes = None

        # Strict process-only mode: raise if creation fails so we fix the issue instead of silently degrading.
        self._executor_processes = _ProcessExecutor(self.workers)

        if clear_inflight:
            with self._lock:
                self._inflight.clear()

    def shutdown(self) -> None:
        try:
            if self._executor_processes is not None:
                self._executor_processes.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def set_target_chunk(self, cx: int, cz: int) -> None:
        with self._lock:
            self._target = ChunkKey(cx, cz)
        # Re-anchor background prefetch so cache warming follows the current working area.
        self._prefetch_cursor = (int(cx), int(cz))


    def set_allowed_chunk_bounds(self, bounds: Optional[tuple[int, int, int, int]]) -> None:
        """Limit streaming to an inclusive chunk-bounds rectangle (min_cx,max_cx,min_cz,max_cz)."""
        normalized = None
        if bounds is not None:
            try:
                min_cx, max_cx, min_cz, max_cz = (int(v) for v in bounds)
                if min_cx > max_cx:
                    min_cx, max_cx = max_cx, min_cx
                if min_cz > max_cz:
                    min_cz, max_cz = max_cz, min_cz
                normalized = (min_cx, max_cx, min_cz, max_cz)
            except Exception:
                log.warning("Invalid allowed chunk bounds %r; disabling bounds limit", bounds)
                normalized = None

        if normalized == self._allowed_chunk_bounds:
            return
        old = self._allowed_chunk_bounds
        self._allowed_chunk_bounds = normalized

        # Drop resident entries outside the new bounds; update() will reschedule as needed.
        with self._lock:
            if self._allowed_chunk_bounds is None:
                pass
            else:
                self._resident_lod = {k: v for k, v in self._resident_lod.items() if self._chunk_allowed(k)}
        self._prefetch_cursor = None
        log.info("StreamManager allowed chunk bounds changed: %s -> %s", old, normalized)

    def _chunk_allowed(self, key: ChunkKey) -> bool:
        b = self._allowed_chunk_bounds
        if b is None:
            return True
        min_cx, max_cx, min_cz, max_cz = b
        return (min_cx <= int(key.cx) <= max_cx) and (min_cz <= int(key.cz) <= max_cz)

    def _cache_has_mesh(self, cx: int, cz: int, lod: str) -> bool:
        # Fast existence check without cloning/emitting.
        if lod == "voxel" and self._preview_sig != "preview:off":
            return self._cache_key_preview(cx, cz, lod, self._preview_sig) in self._preview_mesh_cache
        return self._cache_key_base(cx, cz, lod) in self._base_mesh_cache

    def preload_chunk_bounds_blocking(
        self,
        bounds: Optional[tuple[int, int, int, int]] = None,
        *,
        lod: str = "voxel",
        progress_cb=None,
        cancel_check=None,
    ) -> dict:
        """Blocking preload for a chunk rectangle into caches (no mesh_ready emits).

        Intended for startup/project-area loading so decoding/meshing happens before the viewport
        begins interactive streaming. Uses the existing process pool and stores results in the
        same caches used during normal camera movement.
        """
        if bounds is None:
            bounds = self._allowed_chunk_bounds
        if bounds is None:
            return {"total": 0, "done": 0, "built": 0, "failed": 0, "cancelled": False, "workers": int(self.workers)}

        min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
        if min_cx > max_cx:
            min_cx, max_cx = max_cx, min_cx
        if min_cz > max_cz:
            min_cz, max_cz = max_cz, min_cz

        if self._executor_processes is None:
            self._reset_executors(clear_inflight=False)
        if self._executor_processes is None:
            raise RuntimeError("Process executor is not initialized")

        coords: list[tuple[int, int]] = []
        for cz in range(min_cz, max_cz + 1):
            for cx in range(min_cx, max_cx + 1):
                coords.append((cx, cz))

        total = len(coords)
        if total <= 0:
            return {"total": 0, "done": 0, "built": 0, "failed": 0, "cancelled": False, "workers": int(self.workers)}

        def _emit(done: int, msg: str) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb(int(done), int(total), str(msg))
            except Exception:
                pass

        _emit(0, f"Preloading {total} chunk mesh(es)…")

        preview_sig = self._preview_sig if str(lod) == "voxel" else "surface"
        preview_settings = dict(self.preview_settings)
        done = 0
        built = 0
        failed = 0
        cancelled = False

        pending: dict[cf.Future, tuple[int, int]] = {}
        queue: list[tuple[int, int]] = []

        for (cx, cz) in coords:
            if cancel_check is not None:
                try:
                    if bool(cancel_check()):
                        cancelled = True
                        break
                except Exception:
                    pass
            if self._cache_has_mesh(cx, cz, lod):
                done += 1
                _emit(done, f"Preloading chunk meshes… {done}/{total} (cached)")
            else:
                queue.append((cx, cz))

        max_inflight = max(8, int(self.workers) * 4)
        q_idx = 0

        def _submit_one(cx: int, cz: int):
            fut = self._executor_processes.submit(
                _process_build_task,
                str(self.world_path),
                int(cx), int(cz), str(lod),
                preview_settings,
                preview_sig,
            )
            pending[fut] = (int(cx), int(cz))

        while not cancelled and (q_idx < len(queue) or pending):
            while q_idx < len(queue) and len(pending) < max_inflight:
                cx, cz = queue[q_idx]
                q_idx += 1
                _submit_one(cx, cz)

            if not pending:
                break

            done_set, _ = cf.wait(set(pending.keys()), return_when=cf.FIRST_COMPLETED)
            for fut in done_set:
                cx, cz = pending.pop(fut)
                try:
                    result = fut.result()
                    if result and bool(result.get("cache_hit", False)):
                        self._cache_stats["process_cache_hits"] += 1
                    else:
                        self._cache_stats["process_cache_misses"] += 1

                    if result and bool(result.get("ok", False)):
                        local_names = result.get("local_names") or ["minecraft:air"]
                        mesh = MeshData(
                            vertices=result.get("vertices", b""),
                            vertex_count=int(result.get("vertex_count", 0)),
                            lod=result.get("lod", lod),
                            materials_version=self.registry.version(),
                            top_heights=tuple(result.get("top_heights") or ()),
                        )
                        mesh = self._remap_process_mesh_material_ids(mesh, list(local_names))
                        self._cache_store(cx, cz, str(lod), mesh)
                        built += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                    log.exception("Startup preload failed for chunk (%d,%d) lod=%s", cx, cz, lod)
                finally:
                    done += 1
                    _emit(done, f"Preloading chunk meshes… {done}/{total}")

            if cancel_check is not None:
                try:
                    if bool(cancel_check()):
                        cancelled = True
                except Exception:
                    pass

        if cancelled:
            for fut in list(pending.keys()):
                try:
                    fut.cancel()
                except Exception:
                    pass
            pending.clear()

        return {
            "total": int(total),
            "done": int(done),
            "built": int(built),
            "failed": int(failed),
            "cancelled": bool(cancelled),
            "workers": int(self.workers),
            "lod": str(lod),
            "bounds": (min_cx, max_cx, min_cz, max_cz),
        }

    def emit_cached_chunk_bounds(
        self,
        bounds: Optional[tuple[int, int, int, int]] = None,
        *,
        lod: str = "voxel",
        progress_cb=None,
        cancel_check=None,
    ) -> dict:
        """Emit cached meshes for a chunk rectangle so the viewport can upload/draw them immediately."""
        if bounds is None:
            bounds = self._allowed_chunk_bounds
        if bounds is None:
            return {"total": 0, "done": 0, "emitted": 0, "missing": 0, "cancelled": False, "lod": str(lod)}

        min_cx, max_cx, min_cz, max_cz = [int(v) for v in bounds]
        if min_cx > max_cx:
            min_cx, max_cx = max_cx, min_cx
        if min_cz > max_cz:
            min_cz, max_cz = max_cz, min_cz

        coords: list[tuple[int, int]] = []
        for cz in range(min_cz, max_cz + 1):
            for cx in range(min_cx, max_cx + 1):
                coords.append((cx, cz))

        total = len(coords)
        if total <= 0:
            return {"total": 0, "done": 0, "emitted": 0, "missing": 0, "cancelled": False, "lod": str(lod)}

        def _emit_progress(done: int, msg: str) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb(int(done), int(total), str(msg))
            except Exception:
                pass

        _emit_progress(0, f"Staging preloaded chunks for display… 0/{total}")

        done = 0
        emitted = 0
        missing = 0
        cancelled = False

        for cx, cz in coords:
            if cancel_check is not None:
                try:
                    if bool(cancel_check()):
                        cancelled = True
                        break
                except Exception:
                    pass

            key = ChunkKey(int(cx), int(cz))
            if not self._chunk_allowed(key):
                done += 1
                _emit_progress(done, f"Staging preloaded chunks for display… {done}/{total}")
                continue

            mesh = self._cache_lookup(cx, cz, str(lod))
            if mesh is None:
                missing += 1
            else:
                with self._lock:
                    self._resident_lod[key] = str(lod)
                    self._inflight.discard((int(cx), int(cz), str(lod)))
                self.mesh_ready.emit(int(cx), int(cz), mesh)
                emitted += 1

            done += 1
            _emit_progress(done, f"Staging preloaded chunks for display… {done}/{total}")

        with self._lock:
            resident_n = len(self._resident_lod)
            inflight_n = len(self._inflight)
        self.stats.emit(int(resident_n), int(inflight_n))

        return {
            "total": int(total),
            "done": int(done),
            "emitted": int(emitted),
            "missing": int(missing),
            "cancelled": bool(cancelled),
            "lod": str(lod),
            "bounds": (min_cx, max_cx, min_cz, max_cz),
        }

    def _iter_prefetch_keys(self, target: ChunkKey, desired: Dict[ChunkKey, str], resident: Dict[ChunkKey, str],
                            inflight: Set[Tuple[int, int, str]], budget: int) -> List[ChunkKey]:
        if budget <= 0 or not self._prefetch_enabled:
            return []
        b = self._allowed_chunk_bounds
        if b is None:
            return []  # only prefetch within an explicit selected area
        min_cx, max_cx, min_cz, max_cz = b
        if min_cx > max_cx or min_cz > max_cz:
            return []

        # Row-major cyclic scan. Cursor starts near target for a better "where I am now" warmup.
        start_cx, start_cz = self._prefetch_cursor or (target.cx, target.cz)
        start_cx = max(min_cx, min(int(start_cx), max_cx))
        start_cz = max(min_cz, min(int(start_cz), max_cz))
        width = max_cx - min_cx + 1
        height = max_cz - min_cz + 1
        total = width * height
        start_idx = (start_cz - min_cz) * width + (start_cx - min_cx)

        out: List[ChunkKey] = []
        # Bound CPU work per update; enough checks to find useful work without stalling the UI thread.
        max_checks = min(total, max(256, budget * 64))
        checked = 0
        offset = 0
        next_cursor = None
        while checked < max_checks and len(out) < budget:
            idx = (start_idx + offset) % total
            cx = min_cx + (idx % width)
            cz = min_cz + (idx // width)
            key = ChunkKey(cx, cz)
            offset += 1
            checked += 1
            next_cursor = (cx, cz)

            if key in desired:
                continue
            lod = "voxel"
            if resident.get(key) == lod:
                continue
            if (cx, cz, lod) in inflight:
                continue
            if self._cache_has_mesh(cx, cz, lod):
                continue
            out.append(key)

        if next_cursor is not None:
            self._prefetch_cursor = next_cursor
        return out

    def update(self) -> None:
        with self._lock:
            target = self._target
            resident = dict(self._resident_lod)
            inflight = set(self._inflight)

        # Selected-area workflow: keep the whole allowed edit area visible after preload so the
        # user does not have to move the camera to "discover" already-loaded chunks.
        desired: Dict[ChunkKey, str] = {}
        if self._render_all_allowed_area and self._allowed_chunk_bounds is not None:
            min_cx, max_cx, min_cz, max_cz = self._allowed_chunk_bounds
            for cz in range(min_cz, max_cz + 1):
                for cx in range(min_cx, max_cx + 1):
                    desired[ChunkKey(cx, cz)] = "voxel"
        else:
            for dz in range(-self.near_ring, self.near_ring + 1):
                for dx in range(-self.near_ring, self.near_ring + 1):
                    dist = max(abs(dx), abs(dz))
                    if dist > self.near_ring:
                        continue
                    key = ChunkKey(target.cx + dx, target.cz + dz)
                    if not self._chunk_allowed(key):
                        continue
                    desired[key] = "voxel"

        with self._lock:
            self._resident_lod = {k: v for k, v in self._resident_lod.items() if k in desired}

        candidates: List[tuple[int, int, int, int, ChunkKey, str]] = []
        for key, lod in desired.items():
            current = resident.get(key)
            if current == lod:
                continue
            token = (key.cx, key.cz, lod)
            if token in inflight:
                continue
            dist = chebyshev_dist(key, target)
            lod_pri = 0
            candidates.append((lod_pri, dist, key.cz, key.cx, key, lod))
        candidates.sort()

        scheduled = 0
        for _, _, _, _, key, lod in candidates:
            if scheduled >= self.max_schedule_per_update:
                break
            token = (key.cx, key.cz, lod)
            with self._lock:
                if token in self._inflight:
                    continue
                self._inflight.add(token)
                self._resident_lod[key] = lod
            scheduled += 1
            if self._emit_if_cached(key.cx, key.cz, lod):
                continue
            self._submit_build(key.cx, key.cz, lod)

        # Background cache warming for the selected project area so the user does not have to
        # orbit around just to "discover" chunks before editing elsewhere.
        remaining_budget = max(0, min(int(self._prefetch_budget_per_update), self.max_schedule_per_update - scheduled))
        if remaining_budget > 0:
            prefetch_keys = self._iter_prefetch_keys(target, desired, resident, inflight, remaining_budget)
            for key in prefetch_keys:
                token = (key.cx, key.cz, "voxel")
                with self._lock:
                    if token in self._inflight:
                        continue
                    self._inflight.add(token)
                if self._cache_has_mesh(key.cx, key.cz, "voxel"):
                    with self._lock:
                        self._inflight.discard(token)
                    continue
                self._submit_build(key.cx, key.cz, "voxel", cache_only=True)

        with self._lock:
            self.stats.emit(len(self._resident_lod), len(self._inflight))

        mv = self.registry.version()
        if mv != self._last_mat_version:
            self._last_mat_version = mv
            self.materials_changed.emit(self.registry.names())

    # --------------- cache helpers ---------------
    def _clone_mesh(self, mesh: MeshData) -> MeshData:
        return MeshData(
            vertices=bytes(mesh.vertices or b""),
            vertex_count=int(mesh.vertex_count),
            lod=str(mesh.lod),
            materials_version=self.registry.version(),
            top_heights=tuple(mesh.top_heights or ()),
        )

    def _trim_caches(self) -> None:
        while len(self._base_mesh_cache) > self.base_mesh_cache_limit:
            self._base_mesh_cache.popitem(last=False)
        while len(self._preview_mesh_cache) > self.preview_mesh_cache_limit:
            self._preview_mesh_cache.popitem(last=False)

    def _cache_key_base(self, cx: int, cz: int, lod: str):
        return (int(cx), int(cz), str(lod))

    def _cache_key_preview(self, cx: int, cz: int, lod: str, preview_sig: str):
        return (int(cx), int(cz), str(lod), str(preview_sig))

    def _cache_lookup(self, cx: int, cz: int, lod: str) -> Optional[MeshData]:
        if lod == "voxel" and self._preview_sig != "preview:off":
            key = self._cache_key_preview(cx, cz, lod, self._preview_sig)
            mesh = self._preview_mesh_cache.get(key)
            if mesh is not None:
                self._preview_mesh_cache.move_to_end(key)
                self._cache_stats["preview_hits"] += 1
                return self._clone_mesh(mesh)
            self._cache_stats["preview_misses"] += 1
            return None
        # Base world cache (surface always uses this; voxel when preview disabled)
        key = self._cache_key_base(cx, cz, lod)
        mesh = self._base_mesh_cache.get(key)
        if mesh is not None:
            self._base_mesh_cache.move_to_end(key)
            self._cache_stats["base_hits"] += 1
            return self._clone_mesh(mesh)
        self._cache_stats["base_misses"] += 1
        return None

    def _cache_store(self, cx: int, cz: int, lod: str, mesh: MeshData) -> None:
        if lod == "voxel" and self._preview_sig != "preview:off":
            key = self._cache_key_preview(cx, cz, lod, self._preview_sig)
            self._preview_mesh_cache[key] = self._clone_mesh(mesh)
            self._preview_mesh_cache.move_to_end(key)
        else:
            key = self._cache_key_base(cx, cz, lod)
            self._base_mesh_cache[key] = self._clone_mesh(mesh)
            self._base_mesh_cache.move_to_end(key)
        self._trim_caches()

    def _emit_if_cached(self, cx: int, cz: int, lod: str) -> bool:
        mesh = self._cache_lookup(cx, cz, lod)
        if mesh is None:
            return False
        self.mesh_ready.emit(cx, cz, mesh)
        with self._lock:
            self._inflight.discard((cx, cz, lod))
        return True

    # --------------- build submission ---------------
    def _submit_build(self, cx: int, cz: int, lod: str, *, cache_only: bool = False) -> None:
        if self._executor_processes is None:
            raise RuntimeError("Process executor is not initialized")
        epoch = self._epoch
        preview_sig = self._preview_sig if lod == "voxel" else "surface"
        fut = self._executor_processes.submit(
            _process_build_task,
            str(self.world_path),
            cx, cz, lod,
            dict(self.preview_settings),
            preview_sig,
        )
        fut.add_done_callback(
            lambda f, _cx=cx, _cz=cz, _lod=lod, _epoch=epoch, _psig=preview_sig, _cache_only=cache_only:
                self._on_process_done(f, _cx, _cz, _lod, _epoch, _psig, _cache_only)
        )

    def _on_process_done(self, fut: cf.Future, cx: int, cz: int, lod: str, epoch: int, preview_sig: str,
                         cache_only: bool = False) -> None:
        try:
            if epoch != self._epoch:
                return
            # Ignore stale voxel results if preview settings changed while task was in flight.
            if lod == "voxel" and preview_sig != self._preview_sig:
                return

            result = fut.result()
            if result and bool(result.get("cache_hit", False)):
                self._cache_stats["process_cache_hits"] += 1
            else:
                self._cache_stats["process_cache_misses"] += 1

            if not result or not result.get("ok", False):
                err = "" if not result else result.get("err", "")
                if err:
                    log.debug("Build failed for chunk (%d,%d) lod=%s [processes]: %s", cx, cz, lod, err)
                mesh = MeshData(vertices=b"", vertex_count=0, lod=lod, materials_version=self.registry.version(), top_heights=())
                if not cache_only:
                    self.mesh_ready.emit(cx, cz, mesh)
                return

            local_names = result.get("local_names") or ["minecraft:air"]
            vertices = result.get("vertices", b"")
            vcount = int(result.get("vertex_count", 0))
            mesh = MeshData(
                vertices=vertices,
                vertex_count=vcount,
                lod=result.get("lod", lod),
                materials_version=self.registry.version(),
                top_heights=tuple(result.get("top_heights") or ())
            )
            mesh = self._remap_process_mesh_material_ids(mesh, local_names)
            self._cache_store(cx, cz, lod, mesh)
            if not cache_only:
                self.mesh_ready.emit(cx, cz, self._clone_mesh(mesh))
        except Exception as e:
            log.exception("Process callback failed for chunk (%d,%d) lod=%s: %s", cx, cz, lod, e)
            if not cache_only:
                self.mesh_ready.emit(cx, cz, MeshData(vertices=b"", vertex_count=0, lod=lod, materials_version=self.registry.version(), top_heights=()))
        finally:
            with self._lock:
                self._inflight.discard((cx, cz, lod))

    def _remap_process_mesh_material_ids(self, mesh: MeshData, local_names: List[str]) -> MeshData:
        if not mesh.vertices or mesh.vertex_count <= 0:
            mesh.materials_version = self.registry.version()
            return mesh

        lut = [0] * max(1, len(local_names))
        for lid, name in enumerate(local_names):
            lut[lid] = self.registry.get_or_create(name)

        if len(lut) == 1 or all(lut[i] == i for i in range(len(lut))):
            mesh.materials_version = self.registry.version()
            return mesh

        try:
            import numpy as np
            arr = np.frombuffer(mesh.vertices, dtype=np.float32).copy()
            if arr.size >= 7:
                mids = arr[6::7]
                idx = np.rint(mids).astype(np.int64)
                idx = np.clip(idx, 0, len(lut) - 1)
                lut_np = np.asarray(lut, dtype=np.float32)
                mids[:] = lut_np[idx]
                mesh.vertices = arr.astype(np.float32, copy=False).tobytes()
        except Exception:
            import array
            arr = array.array('f')
            arr.frombytes(mesh.vertices)
            for i in range(6, len(arr), 7):
                lid = int(arr[i] + 0.5)
                if lid < 0:
                    lid = 0
                elif lid >= len(lut):
                    lid = len(lut) - 1
                arr[i] = float(lut[lid])
            mesh.vertices = arr.tobytes()

        mesh.materials_version = self.registry.version()
        return mesh


class _ProcessExecutor:
    def __init__(self, max_workers: int) -> None:
        self._pool = cf.ProcessPoolExecutor(max_workers=max(1, int(max_workers)))

    def submit(self, fn, *args, **kwargs):
        return self._pool.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = False, cancel_futures: bool = True):
        self._pool.shutdown(wait=wait, cancel_futures=cancel_futures)
