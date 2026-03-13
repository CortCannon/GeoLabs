from __future__ import annotations
from PySide6 import QtGui
import hashlib

# A small starter palette; unknown blocks hash to a stable color.
BASE = {
    "minecraft:grass_block": (95, 159, 53),
    "minecraft:dirt": (134, 96, 67),
    "minecraft:stone": (125, 125, 125),
    "minecraft:deepslate": (70, 70, 75),
    "minecraft:sand": (219, 211, 160),
    "minecraft:water": (64, 96, 220),
    "minecraft:lava": (240, 110, 20),
    "minecraft:bedrock": (35, 35, 35),
    "minecraft:oak_log": (102, 81, 51),
    "minecraft:oak_leaves": (74, 132, 52),
    "minecraft:snow_block": (240, 240, 240),
    "minecraft:ice": (170, 200, 240),
    "wgl:preview_cave_marker": (40, 220, 255),
    "wgl:preview_ore_coal": (55, 55, 55),
    "wgl:preview_ore_iron": (196, 164, 132),
    "wgl:preview_ore_copper": (203, 117, 63),
    "wgl:preview_ore_gold": (235, 195, 45),
    "wgl:preview_ore_redstone": (185, 35, 35),
    "wgl:preview_ore_lapis": (49, 92, 210),
    "wgl:preview_ore_diamond": (90, 235, 220),
    "wgl:preview_ore_emerald": (45, 205, 85),
}

AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}

def block_to_color(block_name: str) -> QtGui.QColor:
    if block_name in AIR:
        return QtGui.QColor(0, 0, 0, 0)
    rgb = BASE.get(block_name)
    if rgb:
        return QtGui.QColor(*rgb)
    # stable hash color
    h = hashlib.md5(block_name.encode("utf-8")).digest()
    return QtGui.QColor(40 + h[0] % 160, 40 + h[1] % 160, 40 + h[2] % 160)
