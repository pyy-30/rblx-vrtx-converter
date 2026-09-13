#!/usr/bin/env python3
"""
JSON_to_RBXLX.py
Convert a Vortex/plugin JSON file back into a Roblox .rbxlx XML place file.

Handles lights/textures both from structured arrays (plugin output)
and from child_blob_hex (VRTX_to_JSON output).

Usage:
    py JSON_to_RBXLX.py input.json [output.rbxlx] [--verbose]
"""

import sys
import json
import random
import struct
from pathlib import Path
import xml.etree.ElementTree as ET

# =========================================================
#  CONSTANTS
# =========================================================
VORTEX_TO_MATERIAL_TOKEN = {
    "Smooth":   272,
    "Plastic":  256,
    "Wood":     512,
    "Metal":   1088,
    "Grass":   1280,
    "Ice":     1536,
    "Paint":   1072,
}

FACE_TO_NORMAL = {
    "Front":  4, "Back":  2, "Top":    1,
    "Bottom": 5, "Left":  3, "Right":  0,
}

TEXTURE_TO_SURFACE = {
    "Studs":  3,
    "Inlets": 4,
}

SURFACE_PROPS = {
    "Front":  "FrontSurface",
    "Back":   "BackSurface",
    "Top":    "TopSurface",
    "Bottom": "BottomSurface",
    "Left":   "LeftSurface",
    "Right":  "RightSurface",
}

# Vortex face index (binary) → name
VORTEX_FACE_NAMES = ["Front", "Back", "Top", "Bottom", "Left", "Right"]
VORTEX_KIND_NAMES = {0: "Studs", 1: "Inlets"}

ROBLOX_ROOT_ATTRS = {
    "xmlns:xmime": "http://www.w3.org/2005/05/xmlmime",
    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xsi:noNamespaceSchemaLocation": "http://www.roblox.com/roblox.xsd",
    "version": "4",
}


# =========================================================
#  CHILD BLOB PARSER
# =========================================================
def parse_child_blob(hex_str):
    """Parse a child_blob_hex string into structured textures + lights.

    Returns:
        (textures, point_lights, spot_lights, surface_lights, truss)
    """
    if not hex_str or not isinstance(hex_str, str):
        return [], [], [], [], False

    try:
        b = [int(tok, 16) for tok in hex_str.split()]
    except ValueError:
        return [], [], [], [], False

    if len(b) < 10:
        return [], [], [], [], False

    truss     = bool(b[1])
    tex_count = b[2]

    textures = []
    pos = 10
    for _ in range(tex_count):
        if pos + 8 > len(b):
            break
        face_idx = b[pos]
        kind_idx = b[pos + 4]
        face_name = VORTEX_FACE_NAMES[face_idx] if 0 <= face_idx < 6 else "Front"
        kind_name = VORTEX_KIND_NAMES.get(kind_idx, "Studs")
        textures.append({"face": face_name, "kind": kind_name})
        pos += 8

    def read_float(off):
        if off + 4 > len(b):
            return 0.0
        return struct.unpack("<f", bytes(b[off:off+4]))[0]

    def read_u32(off):
        if off + 4 > len(b):
            return 0
        return struct.unpack("<I", bytes(b[off:off+4]))[0]

    point_lights   = []
    spot_lights    = []
    surface_lights = []

    while pos < len(b):
        b1 = b[pos]
        b2 = b[pos + 1] if pos + 1 < len(b) else 0

        # PointLight: marker 0x01 + 6 floats = 25 bytes
        if b1 == 1 and pos + 25 <= len(b):
            r = read_float(pos + 1)
            g = read_float(pos + 5)
            bb = read_float(pos + 9)
            brightness = read_float(pos + 17) / 1500000.0
            range_val  = read_float(pos + 21)
            point_lights.append({
                "color":      {"r": round(r, 3), "g": round(g, 3), "b": round(bb, 3)},
                "brightness": round(brightness, 3),
                "range":      round(range_val, 3),
                "enabled":    True,
            })
            pos += 25

        # Spot / Surface: marker 0x00 0x01 + 7 floats + u32 face = 34 bytes
        elif b1 == 0 and b2 == 1 and pos + 34 <= len(b):
            r = read_float(pos + 2)
            g = read_float(pos + 6)
            bb = read_float(pos + 10)
            brightness = read_float(pos + 18) / 1500000.0
            range_val  = read_float(pos + 22)
            angle      = read_float(pos + 26)
            face_id    = read_u32(pos + 30)
            face_name  = VORTEX_FACE_NAMES[face_id] if 0 <= face_id < 6 else "Front"
            # The binary can't distinguish SpotLight from SurfaceLight, so
            # default to SurfaceLight (matches the plugin's import behaviour).
            surface_lights.append({
                "color":      {"r": round(r, 3), "g": round(g, 3), "b": round(bb, 3)},
                "brightness": round(brightness, 3),
                "range":      round(range_val, 3),
                "angle":      round(angle, 3),
                "face":       face_name,
                "enabled":    True,
            })
            pos += 34

        else:
            pos += 1

    return textures, point_lights, spot_lights, surface_lights, truss


def enrich_part_from_blob(obj):
    """If the part has empty/missing structured fields, populate them from child_blob_hex."""
    has_tex = bool(obj.get("textures"))
    has_pts = bool(obj.get("point_lights"))
    has_sps = bool(obj.get("spot_lights"))
    has_sur = bool(obj.get("surface_lights"))

    if has_tex and has_pts and has_sps and has_sur and obj.get("truss") is not None:
        return

    blob = obj.get("child_blob_hex")
    if not blob:
        return

    textures, points, spots, surfaces, truss = parse_child_blob(blob)

    if not has_tex and textures:
        obj["textures"] = textures
    if not has_pts and points:
        obj["point_lights"] = points
    if not has_sps and spots:
        obj["spot_lights"] = spots
    if not has_sur and surfaces:
        obj["surface_lights"] = surfaces
    if truss:
        obj["truss"] = True


# =========================================================
#  XML HELPERS
# =========================================================
def new_referent():
    return "RBX" + "".join(random.choice("0123456789ABCDEF") for _ in range(32))


def quat_to_matrix(qx, qy, qz, qw):
    return [
        [1 - 2*qy*qy - 2*qz*qz,   2*qx*qy - 2*qz*qw,    2*qx*qz + 2*qy*qw],
        [2*qx*qy + 2*qz*qw,      1 - 2*qx*qx - 2*qz*qz, 2*qy*qz - 2*qx*qw],
        [2*qx*qz - 2*qy*qw,      2*qy*qz + 2*qx*qw,     1 - 2*qx*qx - 2*qy*qy],
    ]


def encode_color3uint8(r, g, b):
    ri = int(round(max(0.0, min(1.0, r)) * 255))
    gi = int(round(max(0.0, min(1.0, g)) * 255))
    bi = int(round(max(0.0, min(1.0, b)) * 255))
    return (0xFF << 24) | (ri << 16) | (gi << 8) | bi


def add_string(parent, name, value):
    ET.SubElement(parent, "string", {"name": name}).text = str(value)


def add_bool(parent, name, value):
    ET.SubElement(parent, "bool", {"name": name}).text = "true" if value else "false"


def add_float(parent, name, value):
    ET.SubElement(parent, "float", {"name": name}).text = str(float(value))


def add_int(parent, name, value):
    ET.SubElement(parent, "int", {"name": name}).text = str(int(value))


def add_token(parent, name, value):
    ET.SubElement(parent, "token", {"name": name}).text = str(int(value))


def add_vector3(parent, name, x, y, z):
    el = ET.SubElement(parent, "Vector3", {"name": name})
    ET.SubElement(el, "X").text = str(float(x))
    ET.SubElement(el, "Y").text = str(float(y))
    ET.SubElement(el, "Z").text = str(float(z))


def add_cframe(parent, name, pos, quat):
    el = ET.SubElement(parent, "CoordinateFrame", {"name": name})
    ET.SubElement(el, "X").text = str(float(pos[0]))
    ET.SubElement(el, "Y").text = str(float(pos[1]))
    ET.SubElement(el, "Z").text = str(float(pos[2]))
    m = quat_to_matrix(quat[0], quat[1], quat[2], quat[3])
    for i in range(3):
        for j in range(3):
            ET.SubElement(el, f"R{i}{j}").text = str(float(m[i][j]))


def add_color3uint8(parent, name, r, g, b):
    ET.SubElement(parent, "Color3uint8", {"name": name}).text = str(encode_color3uint8(r, g, b))


def add_color3(parent, name, r, g, b):
    el = ET.SubElement(parent, "Color3", {"name": name})
    ET.SubElement(el, "R").text = str(float(r))
    ET.SubElement(el, "G").text = str(float(g))
    ET.SubElement(el, "B").text = str(float(b))


def add_protected_string(parent, name, value):
    ET.SubElement(parent, "ProtectedString", {"name": name}).text = str(value)


# =========================================================
#  PART / SCRIPT PROPERTIES
# =========================================================
def build_part_props(props, obj):
    add_string(props, "Name", obj.get("name", "Part"))

    pos   = obj.get("position", [0, 0, 0])
    quat  = obj.get("rotation", [0, 0, 0, 1])
    size  = obj.get("size", [1, 1, 1])
    col   = obj.get("color", {"r": 0.5, "g": 0.5, "b": 0.5})
    flags = obj.get("flags", [0, 1, 1, 1, 0, 0])

    add_cframe(props, "CFrame", pos, quat)
    add_vector3(props, "size", size[0], size[1], size[2])
    add_color3uint8(props, "Color3uint8",
                    col.get("r", 0.5), col.get("g", 0.5), col.get("b", 0.5))

    transparency = obj.get("transparency")
    if transparency is None:
        transparency = 1.0 - col.get("a", 1.0)
    add_float(props, "Transparency", transparency)

    mat_name = obj.get("material", "Plastic")
    add_token(props, "Material", VORTEX_TO_MATERIAL_TOKEN.get(mat_name, 256))

    add_bool(props, "CastShadow", flags[1] == 1)
    add_bool(props, "Anchored",   flags[2] == 1)
    add_bool(props, "CanCollide", flags[3] == 1)
    add_bool(props, "Locked",     flags[5] == 1)

    # Surfaces — default Smooth, override from textures
    surfaces = {face: 0 for face in SURFACE_PROPS}
    for t in obj.get("textures") or []:
        face = t.get("face")
        kind = t.get("kind")
        if face in SURFACE_PROPS and kind in TEXTURE_TO_SURFACE:
            surfaces[face] = TEXTURE_TO_SURFACE[kind]
    for face, token in surfaces.items():
        add_token(props, SURFACE_PROPS[face], token)

    add_bool(props,  "CanQuery", True)
    add_bool(props,  "CanTouch", True)
    add_float(props, "Reflectance", 0.0)
    add_token(props, "shape", 1)
    add_token(props, "formFactorRaw", 1)


def build_script_props(props, obj):
    add_string(props, "Name", obj.get("name", "Script"))
    add_protected_string(props, "Source", obj.get("source", ""))
    add_bool(props, "Disabled", not obj.get("enabled", True))
    add_token(props, "RunContext", 0)


# =========================================================
#  LIGHT ITEMS
# =========================================================
def build_point_light_item(data):
    item = ET.Element("Item", {"class": "PointLight", "referent": new_referent()})
    props = ET.SubElement(item, "Properties")
    c = data.get("color", {"r": 1, "g": 1, "b": 1})
    add_color3(props, "Color",      c.get("r", 1.0), c.get("g", 1.0), c.get("b", 1.0))
    add_float(props,  "Brightness", data.get("brightness", 1.0))
    add_float(props,  "Range",      data.get("range", 8.0))
    add_bool(props,   "Enabled",    data.get("enabled", True))
    add_bool(props,   "Shadows",    False)
    add_string(props, "Name",       "PointLight")
    return item


def build_spot_light_item(data, class_name="SpotLight"):
    item = ET.Element("Item", {"class": class_name, "referent": new_referent()})
    props = ET.SubElement(item, "Properties")
    c = data.get("color", {"r": 1, "g": 1, "b": 1})
    add_color3(props, "Color",      c.get("r", 1.0), c.get("g", 1.0), c.get("b", 1.0))
    add_float(props,  "Brightness", data.get("brightness", 1.0))
    add_float(props,  "Range",      data.get("range", 8.0))
    add_float(props,  "Angle",      data.get("angle", 90.0))
    add_token(props,  "Face",       FACE_TO_NORMAL.get(data.get("face", "Front"), 4))
    add_bool(props,   "Enabled",    data.get("enabled", True))
    add_bool(props,   "Shadows",    False)
    add_string(props, "Name",       class_name)
    return item


def add_lights_to_part(item, obj):
    for light in obj.get("point_lights") or []:
        item.append(build_point_light_item(light))
    for light in obj.get("spot_lights") or []:
        item.append(build_spot_light_item(light, "SpotLight"))
    for light in obj.get("surface_lights") or []:
        item.append(build_spot_light_item(light, "SurfaceLight"))


# =========================================================
#  ITEM BUILDERS
# =========================================================
def build_service_item(cls, name):
    item = ET.Element("Item", {"class": cls, "referent": new_referent()})
    props = ET.SubElement(item, "Properties")
    add_string(props, "Name", name)
    return item


def build_item(obj):
    kind = obj.get("kind")

    if kind == "group":
        item = ET.Element("Item", {"class": "Model", "referent": new_referent()})
        props = ET.SubElement(item, "Properties")
        add_string(props, "Name", obj.get("name", "Model"))
        return item

    if kind == "part":
        cls = "Part"
        flags = obj.get("flags", [0]*6)
        if len(flags) > 4 and flags[4] == 1:
            cls = "SpawnLocation"
        elif obj.get("truss"):
            cls = "TrussPart"
        item = ET.Element("Item", {"class": cls, "referent": new_referent()})
        props = ET.SubElement(item, "Properties")
        build_part_props(props, obj)
        add_lights_to_part(item, obj)
        return item

    if kind == "script":
        cls = obj.get("class", "Script")
        item = ET.Element("Item", {"class": cls, "referent": new_referent()})
        props = ET.SubElement(item, "Properties")
        build_script_props(props, obj)
        return item

    return None


# =========================================================
#  TREE EMISSION
# =========================================================
def build_children_map(objects):
    children = {}
    for idx, obj in enumerate(objects):
        if obj.get("kind") == "service":
            continue
        pid = obj.get("parent_id")
        if pid is None:
            pid = 0
        children.setdefault(int(pid), []).append(idx)
    return children


def emit_children(parent_idx, parent_xml, objects, children):
    for child_idx in children.get(parent_idx, []):
        obj = objects[child_idx]
        item = build_item(obj)
        if item is None:
            continue
        parent_xml.append(item)
        emit_children(child_idx, item, objects, children)


# =========================================================
#  MAIN
# =========================================================
def run(json_data):
    objects = json_data.get("objects", [])

    # Enrich every part with data from child_blob_hex if the structured
    # fields are missing (VRTX_to_JSON output).
    for obj in objects:
        if obj.get("kind") == "part":
            enrich_part_from_blob(obj)

    root = ET.Element("roblox", ROBLOX_ROOT_ATTRS)
    ET.SubElement(root, "External").text = "null"
    ET.SubElement(root, "External").text = "nil"

    ws      = build_service_item("Workspace",               "Workspace")
    lt      = build_service_item("Lighting",                "Lighting")
    rs      = build_service_item("ReplicatedStorage",       "ReplicatedStorage")
    sss     = build_service_item("ServerScriptService",     "ServerScriptService")
    sp      = build_service_item("StarterPlayer",           "StarterPlayer")
    sps     = build_service_item("StarterPlayerScripts",    "StarterPlayerScripts")
    spc     = build_service_item("StarterCharacterScripts", "StarterCharacterScripts")
    players = build_service_item("Players",                 "Players")

    sp.append(sps)
    sp.append(spc)
    root.extend([ws, lt, rs, sss, sp, players])

    service_xml = {0: ws, 1: lt, 2: rs, 3: sss, 4: sps}

    # Lighting properties
    lighting = json_data.get("lighting", {})
    lt_props = lt.find("Properties")
    amb = lighting.get("ambient_color", {"r": 0.5, "g": 0.5, "b": 0.5})
    sun = lighting.get("sun_color",     {"r": 1.0, "g": 1.0, "b": 1.0})
    add_color3(lt_props, "Ambient",        amb.get("r", 0.5), amb.get("g", 0.5), amb.get("b", 0.5))
    add_color3(lt_props, "OutdoorAmbient", sun.get("r", 1.0), sun.get("g", 1.0), sun.get("b", 1.0))

    raw_br = float(lighting.get("sun_brightness", 2000))
    brightness = max(0.0, min(10.0, (raw_br / 1000.0 - 1) / 2))
    add_float(lt_props, "Brightness", brightness)
    add_bool(lt_props, "GlobalShadows", lighting.get("sun_shadows", True))
    add_token(lt_props, "Technology", 3)

    children = build_children_map(objects)
    for svc_idx, svc_xml in service_xml.items():
        emit_children(svc_idx, svc_xml, objects, children)

    return root, objects


# =========================================================
#  ENTRY
# =========================================================
if __name__ == "__main__":
    args  = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    verbose = any(f in ("-v", "--verbose") for f in flags)

    if not args:
        print("Usage: py JSON_to_RBXLX.py input.json [output.rbxlx] [--verbose]")
        sys.exit(1)

    in_path  = Path(args[0])
    out_path = Path(args[1]) if len(args) > 1 else in_path.with_suffix(".rbxlx")

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    root, objects = run(data)

    try:
        ET.indent(root, space="\t")
    except AttributeError:
        pass

    tree = ET.ElementTree(root)
    tree.write(out_path, encoding="utf-8", xml_declaration=False)

    parts   = sum(1 for o in objects if o.get("kind") == "part")
    scripts = sum(1 for o in objects if o.get("kind") == "script")
    groups  = sum(1 for o in objects if o.get("kind") == "group")

    lights, textures, trusses = 0, 0, 0
    for o in objects:
        if o.get("kind") == "part":
            lights   += len(o.get("point_lights") or [])
            lights   += len(o.get("spot_lights") or [])
            lights   += len(o.get("surface_lights") or [])
            textures += len(o.get("textures") or [])
            if o.get("truss"): trusses += 1

    print(f"Saved: {out_path}")
    print(f"  services : 5")
    print(f"  parts    : {parts}")
    print(f"  groups   : {groups}")
    print(f"  scripts  : {scripts}")
    print(f"  lights   : {lights}")
    print(f"  textures : {textures}")
    print(f"  trusses  : {trusses}")

    if verbose:
        print("\n" + "=" * 60)
        with open(out_path, "r", encoding="utf-8") as f:
            print(f.read())
        print("=" * 60)
