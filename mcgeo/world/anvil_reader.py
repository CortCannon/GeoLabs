from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from .region import RegionFile
from .nbt import read_nbt, NbtTag, TAG_Compound, TAG_List, TAG_String, TAG_Byte, TAG_Long_Array
from .blockstates_decode import decode_blockstates
from .palette import canonical_state, is_air

log = logging.getLogger("mcgeo.world")

@dataclass
class SectionModel:
    y: int
    palette: List[str]              # canonical state strings
    indices: List[int]              # 4096 palette indices

@dataclass
class ChunkModel:
    cx: int
    cz: int
    sections: Dict[int, SectionModel]  # key: section Y
    _surface_cache: Optional[List[Tuple[int, str]]] = None

    def _build_surface_cache(self) -> List[Tuple[int, str]]:
        cache: List[Tuple[int, str]] = [(0, "minecraft:air")] * 256
        if not self.sections:
            return cache
        top_sy = max(self.sections.keys())
        bot_sy = min(self.sections.keys())
        for z in range(16):
            for x in range(16):
                found_y = 0
                found_name = "minecraft:air"
                found = False
                for sy in range(top_sy, bot_sy - 1, -1):
                    sec = self.sections.get(sy)
                    if sec is None:
                        continue
                    for ly in range(15, -1, -1):
                        y = sy * 16 + ly
                        idx = (ly * 16 + (z & 15)) * 16 + (x & 15)
                        pi = sec.indices[idx]
                        if pi < 0 or pi >= len(sec.palette):
                            continue
                        name = sec.palette[pi].split("[", 1)[0]
                        if not is_air(name):
                            found_y = y
                            found_name = name
                            found = True
                            break
                    if found:
                        break
                cache[(z & 15) * 16 + (x & 15)] = (int(found_y), str(found_name))
        return cache

    def get_surface_block_cached(self, x: int, z: int) -> Tuple[int, str]:
        cache = self._surface_cache
        if cache is None:
            cache = self._build_surface_cache()
            self._surface_cache = cache
        return cache[(z & 15) * 16 + (x & 15)]

    def get_block(self, x: int, y: int, z: int) -> str:
        sy = y // 16
        sec = self.sections.get(sy)
        if sec is None:
            return "minecraft:air"
        ly = y & 15
        idx = (ly * 16 + (z & 15)) * 16 + (x & 15)  # YZX order (deterministic)
        pi = sec.indices[idx]
        if 0 <= pi < len(sec.palette):
            return sec.palette[pi].split("[", 1)[0]  # base name for color lookup
        return "minecraft:air"

    def find_surface_block(self, x: int, z: int) -> Tuple[int, str]:
        return self.get_surface_block_cached(x, z)

class AnvilWorld:
    def __init__(self, world_path: Path) -> None:
        self.world_path = world_path
        self.region_dir = world_path / "region"

    def _region_path(self, cx: int, cz: int) -> Path:
        rx = cx >> 5
        rz = cz >> 5
        return self.region_dir / f"r.{rx}.{rz}.mca"

    def read_chunk(self, cx: int, cz: int) -> Optional[ChunkModel]:
        rp = self._region_path(cx, cz)
        if not rp.exists():
            return None
        cxr = cx & 31
        czr = cz & 31
        with RegionFile(rp) as reg:
            raw = reg.read_chunk_nbt_bytes(cxr, czr)
        if raw is None:
            return None
        root = read_nbt(raw).value  # compound dict[str,NbtTag]

        # Modern chunks often store data at root; some have a 'Level' compound.
        data = root.get("Level").value if "Level" in root and root["Level"].tag_id == TAG_Compound else root

        # xPos/zPos might exist; ignore if missing.
        sections_tag = data.get("sections") or data.get("Sections")
        if not sections_tag or sections_tag.tag_id != TAG_List:
            return ChunkModel(cx, cz, {})

        elem_id, sections_list = sections_tag.value
        # sections_list is list of compound dicts
        sections: Dict[int, SectionModel] = {}
        for sec_comp in sections_list:
            # sec_comp is dict[str,NbtTag]
            y_tag = sec_comp.get("Y") or sec_comp.get("y")
            if not y_tag:
                continue
            y = int(y_tag.value)
            bs = sec_comp.get("block_states") or sec_comp.get("BlockStates")
            if not bs or bs.tag_id != TAG_Compound:
                continue
            bs_comp = bs.value

            pal_tag = bs_comp.get("palette") or bs_comp.get("Palette")
            if not pal_tag or pal_tag.tag_id != TAG_List:
                continue
            _, pal_list = pal_tag.value

            palette: List[str] = []
            for p in pal_list:
                # p is dict[str,NbtTag]
                name = p.get("Name").value if p.get("Name") else "minecraft:air"
                props_tag = p.get("Properties")
                props = None
                if props_tag and props_tag.tag_id == TAG_Compound:
                    props = {k: v.value for k, v in props_tag.value.items()}
                palette.append(canonical_state(name, props))

            data_tag = bs_comp.get("data") or bs_comp.get("Data")
            if not data_tag:
                indices = [0] * 4096
            else:
                if data_tag.tag_id != TAG_Long_Array:
                    indices = [0] * 4096
                else:
                    indices = decode_blockstates(list(data_tag.value), len(palette))

            sections[y] = SectionModel(y=y, palette=palette, indices=indices)

        return ChunkModel(cx, cz, sections)
