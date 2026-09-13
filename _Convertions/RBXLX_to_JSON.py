#!/usr/bin/env python3
"""
RBXLX_to_JSON.py
Convert a Roblox .rbxlx / .rbxmx XML file into the JSON format that
JSON_to_VRTX.py accepts. Same schema as the Roblox plugin emits.

Usage:
    py RBXLX_to_JSON.py input.rbxlx [output.json] [--verbose]
"""

import sys
import json
import math
import struct
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

# =========================================================
#  LOOKUP TABLES
# =========================================================
SERVICE_ORDER = [
    ("Workspace",            0),
    ("Lighting",             1),
    ("ReplicatedStorage",   10),
    ("ServerScriptService", 12),
    ("StarterPlayerScripts", 11),
]

# Roblox NormalId -> Vortex face name
NORMAL_ID_TO_VORTEX_FACE = {
    0: "Right", 1: "Top", 2: "Back", 3: "Left", 4: "Front", 5: "Bottom",
}

# Vortex face name -> Vortex face index
VORTEX_FACE_INDEX = {
    "Front": 0, "Back": 1, "Top": 2, "Bottom": 3, "Left": 4, "Right": 5,
}

# Roblox SurfaceType token -> texture kind
SURFACE_TYPE_TO_TEXTURE = {
    3: "Studs",
    4: "Inlets",
}

# Roblox Material token -> Roblox material name
MATERIAL_TOKENS = {
    256: "Plastic", 272: "Wood", 288: "Slate", 304: "Concrete",
    320: "CorrodedMetal", 336: "DiamondPlate", 352: "Foil",
    368: "Grass", 384: "Ice", 400: "Marble", 416: "Granite",
    432: "Brick", 448: "Pebble", 464: "Sand", 480: "Fabric",
    496: "SmoothPlastic", 512: "Metal", 528: "WoodPlanks",
    544: "Cobblestone", 560: "Air", 576: "Water", 592: "Rock",
    608: "Glacier", 624: "Snow", 640: "Sandstone", 656: "Mud",
    672: "Basalt", 688: "Ground", 704: "CrackedLava",
    720: "Asphalt", 736: "LeafyGrass", 752: "Salt",
    768: "Limestone", 784: "Pavement", 800: "ForceField",
    816: "Neon", 832: "Glass", 848: "Plaster", 864: "Carpet",
    880: "CeramicTiles", 896: "ClayRoofTiles", 912: "RoofShingles",
    928: "Cardboard",
}

# Roblox material name -> Vortex material name
MATERIAL_MAP = {
    "Plastic": "Plastic",
    "SmoothPlastic": "Smooth",
    "Neon": "Smooth",
    "Glass": "Ice", "ForceField": "Ice", "Glacier": "Ice", "Ice": "Ice",
    "Foil": "Paint",
    "Metal": "Metal", "CorrodedMetal": "Metal", "DiamondPlate": "Metal",
    "Wood": "Wood", "WoodPlanks": "Wood",
    "Grass": "Grass", "LeafyGrass": "Grass", "Ground": "Grass",
    "Carpet": "Grass", "Fabric": "Grass", "Mud": "Grass",
    # everything else → Paint
}

MATERIAL_IDS = {
    "Smooth": 0, "Plastic": 1, "Wood": 2, "Metal": 3,
    "Grass": 4, "Ice": 5, "Paint": 6,
}

PART_CLASSES   = {"Part", "WedgePart", "CornerWedgePart", "TrussPart",
                  "SpawnLocation", "MeshPart", "UnionOperation", "IntersectOperation"}
SCRIPT_CLASSES = {"Script": 8, "LocalScript": 7, "RemoteEvent": 13,
                  "BindableEvent": 14, "RemoteFunction": 15}
SOURCE_SCRIPT_CLASSES = {"Script", "LocalScript"}
LIGHT_CLASSES  = {"PointLight", "SpotLight", "SurfaceLight"}


def map_material(roblox_name):
    return MATERIAL_MAP.get(roblox_name, "Paint")


def r3(x):
    return round(float(x), 3)


def r6(x):
    return round(float(x), 6)


def matrix_to_quat(r00, r01, r02, r10, r11, r12, r20, r21, r22):
    trace = r00 + r11 + r22
    if trace > 0:
        s = (trace + 1) ** 0.5 * 2
        w, x, y, z = 0.25 * s, (r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s
    elif r00 > r11 and r00 > r22:
        s = (1 + r00 - r11 - r22) ** 0.5 * 2
        w, x, y, z = (r21 - r12) / s, 0.25 * s, (r01 + r10) / s, (r02 + r20) / s
    elif r11 > r22:
        s = (1 + r11 - r00 - r22) ** 0.5 * 2
        w, x, y, z = (r02 - r20) / s, (r01 + r10) / s, 0.25 * s, (r12 + r21) / s
    else:
        s = (1 + r22 - r00 - r11) ** 0.5 * 2
        w, x, y, z = (r10 - r01) / s, (r02 + r20) / s, (r12 + r21) / s, 0.25 * s
    return [r6(x), r6(y), r6(z), r6(w)]


# =========================================================
#  XML PROPERTY ACCESSORS
# =========================================================
def _find_prop(item, name):
    props = item.find("Properties")
    if props is None:
        return None
    for child in props:
        if child.get("name") == name:
            return child
    return None


def get_str(item, name, default=""):
    el = _find_prop(item, name)
    if el is None or el.text is None:
        return default
    return el.text


def get_bool(item, name, default=False):
    txt = get_str(item, name, None)
    if txt is None:
        return default
    return txt.strip().lower() == "true"


def get_float(item, name, default=0.0):
    txt = get_str(item, name, None)
    if txt is None:
        return default
    try:
        return float(txt)
    except ValueError:
        return default


def get_int(item, name, default=0):
    txt = get_str(item, name, None)
    if txt is None:
        return default
    try:
        return int(txt)
    except ValueError:
        return default


def get_vec3(item, name):
    el = _find_prop(item, name)
    if el is None:
        return [0.0, 0.0, 0.0]
    try:
        return [float(el.find("X").text), float(el.find("Y").text), float(el.find("Z").text)]
    except (AttributeError, ValueError):
        return [0.0, 0.0, 0.0]


def get_cframe(item, name):
    el = _find_prop(item, name)
    if el is None:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]
    try:
        pos = [float(el.find("X").text), float(el.find("Y").text), float(el.find("Z").text)]
        r00 = float(el.find("R00").text); r01 = float(el.find("R01").text); r02 = float(el.find("R02").text)
        r10 = float(el.find("R10").text); r11 = float(el.find("R11").text); r12 = float(el.find("R12").text)
        r20 = float(el.find("R20").text); r21 = float(el.find("R21").text); r22 = float(el.find("R22").text)
    except (AttributeError, ValueError):
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]
    quat = matrix_to_quat(r00, r01, r02, r10, r11, r12, r20, r21, r22)
    return [r3(p) for p in pos], quat


def decode_color3uint8(value):
    r = ((value >> 16) & 0xFF) / 255.0
    g = ((value >> 8) & 0xFF) / 255.0
    b = (value & 0xFF) / 255.0
    return r, g, b


# =========================================================
#  CHILD BLOB BUILDER  (matches the plugin's binary layout)
# =========================================================
FACE_ID = {"Front": 0, "Back": 1, "Top": 2, "Bottom": 3, "Left": 4, "Right": 5}


def f2b(f):
    return list(struct.pack("<f", float(f)))


def build_child_blob(part_obj):
    out = [0] * 10  # 10-byte header

    out[1] = 1 if part_obj.get("truss") else 0
    textures = part_obj.get("textures", [])
    out[2] = len(textures)

    for t in textures:
        face_idx = VORTEX_FACE_INDEX[t["face"]]
        kind = 0 if t["kind"] == "Studs" else 1
        out.extend([face_idx, 0, 0, 0, kind, 0, 0, 0])

    wrote_spots = False
    for light in (part_obj.get("spot_lights") or []) + (part_obj.get("surface_lights") or []):
        if not light.get("enabled", True):
            continue
        out.extend([0, 1])
        out.extend(f2b(light["color"]["r"]))
        out.extend(f2b(light["color"]["g"]))
        out.extend(f2b(light["color"]["b"]))
        out.extend(f2b(1.0))
        out.extend(f2b(light["brightness"] * 1500000))
        out.extend(f2b(light["range"]))
        out.extend(f2b(light.get("angle", 90)))
        face_idx = FACE_ID.get(light.get("face", "Front"), 0)
        out.extend([face_idx & 0xFF, (face_idx >> 8) & 0xFF,
                    (face_idx >> 16) & 0xFF, (face_idx >> 24) & 0xFF])
        wrote_spots = True

    if not wrote_spots:
        for light in (part_obj.get("point_lights") or []):
            if not light.get("enabled", True):
                continue
            out.append(1)
            out.extend(f2b(light["color"]["r"]))
            out.extend(f2b(light["color"]["g"]))
            out.extend(f2b(light["color"]["b"]))
            out.extend(f2b(1.0))
            out.extend(f2b(light["brightness"] * 1500000))
            out.extend(f2b(light["range"]))

    out.extend([0] * 12)
    while len(out) % 8 != 0:
        out.append(0)

    return " ".join(f"{b:02X}" for b in out)


# =========================================================
#  PART / SCRIPT / LIGHT CONVERTERS
# =========================================================
def convert_light(item, kind):
    enabled = get_bool(item, "Enabled", True)
    color_el = _find_prop(item, "Color")
    if color_el is not None:
        cr = float(color_el.find("R").text)
        cg = float(color_el.find("G").text)
        cb = float(color_el.find("B").text)
    else:
        cr = cg = cb = 1.0

    entry = {
        "color": {"r": r3(cr), "g": r3(cg), "b": r3(cb)},
        "brightness": r3(get_float(item, "Brightness", 1.0)),
        "range": r3(get_float(item, "Range", 8.0)),
        "enabled": enabled,
    }
    if kind in ("spot", "surface"):
        entry["angle"] = r3(get_float(item, "Angle", 90.0))
        face_token = get_int(item, "Face", 0)
        entry["face"] = NORMAL_ID_TO_VORTEX_FACE.get(face_token, "Front")
    return entry


def convert_script(item, parent_id, parent_name, parent_kind):
    cls = item.get("class")
    type_id = SCRIPT_CLASSES[cls]
    is_source = cls in SOURCE_SCRIPT_CLASSES

    name = get_str(item, "Name", cls)
    source = get_str(item, "Source", "") if is_source else ""
    disabled = get_bool(item, "Disabled", False)

    return {
        "type_id": type_id,
        "class": cls,
        "name": name,
        "kind": "script",
        "enabled": not disabled,
        "parent_id": parent_id,
        "parent_name": parent_name,
        "parent_kind": parent_kind,
        "marker": 1 if is_source else 0,
        "source": source,
        "trailing_hex": "01 00 00 00 00 00 00 00 00 00" if is_source else "00",
    }


def convert_part(item, parent_id, group_json_idx):
    name = get_str(item, "Name", "Part")
    pos, quat = get_cframe(item, "CFrame")
    size = get_vec3(item, "size")
    color_u32 = get_int(item, "Color3uint8", 0xFF808080)
    cr, cg, cb = decode_color3uint8(color_u32)
    transparency = get_float(item, "Transparency", 0.0)

    mat_token = get_int(item, "Material", 256)
    roblox_mat = MATERIAL_TOKENS.get(mat_token, "Plastic")
    vortex_mat = map_material(roblox_mat)

    anchored   = get_bool(item, "Anchored", False)
    can_collide = get_bool(item, "CanCollide", True)
    cast_shadow = get_bool(item, "CastShadow", True)
    locked     = get_bool(item, "Locked", False)

    cls = item.get("class")
    is_spawn = (cls == "SpawnLocation")
    is_truss = (cls == "TrussPart")
    is_baseplate = locked and name.lower() == "baseplate"

    # Textures from surfaces + Decal/Texture children
    textures = []
    for surface_name in ("TopSurface", "BottomSurface", "LeftSurface",
                         "RightSurface", "FrontSurface", "BackSurface"):
        token = get_int(item, surface_name, 0)
        if token in SURFACE_TYPE_TO_TEXTURE:
            face = surface_name.replace("Surface", "")
            textures.append({"face": face, "kind": SURFACE_TYPE_TO_TEXTURE[token]})
    for sub in item.findall("Item"):
        if sub.get("class") in ("Texture", "Decal"):
            face_token = get_int(sub, "Face", 0)
            face_name = NORMAL_ID_TO_VORTEX_FACE.get(face_token)
            if face_name and not any(t["face"] == face_name for t in textures):
                textures.append({"face": face_name, "kind": "Inlets"})

    # Child lights
    pts, sps, surfs = [], [], []
    for sub in item.findall("Item"):
        c = sub.get("class")
        if c == "PointLight":
            pts.append(convert_light(sub, "point"))
        elif c == "SpotLight":
            sps.append(convert_light(sub, "spot"))
        elif c == "SurfaceLight":
            surfs.append(convert_light(sub, "surface"))

    part_obj = {
        "type_id": 2,
        "class": "TrussPart" if is_truss else "Part",
        "name": name,
        "kind": "part",
        "enabled": True,
        "parent_id": parent_id,
        "flag2": 1,
        "inner_name": name,
        "position": pos,
        "rotation": quat,
        "size": [r3(size[0]), r3(size[1]), r3(size[2])],
        "color": {"r": r3(cr), "g": r3(cg), "b": r3(cb), "a": r3(1.0 - transparency)},
        "transparency": r3(transparency),
        "material_id": MATERIAL_IDS[vortex_mat],
        "material": vortex_mat,
        "flags": [
            0,
            1 if cast_shadow else 0,
            1 if anchored else 0,
            1 if can_collide else 0,
            1 if is_spawn else 0,
            1 if is_baseplate else 0,
        ],
        "truss": is_truss,
        "group": group_json_idx,
        "textures": textures,
        "point_lights": pts,
        "spot_lights": sps,
        "surface_lights": surfs,
    }
    part_obj["child_blob_hex"] = build_child_blob(part_obj)
    return part_obj


# =========================================================
#  MAIN CONVERTER
# =========================================================
class Converter:
    def __init__(self):
        self.objects = []
        self.scripts = []
        self.groups = []

    def emit_service(self, name, type_id):
        self.objects.append({
            "type_id": type_id,
            "name": name,
            "class": name,
            "kind": "service",
            "payload_hex": "00 00 00 00 00 00 00 00 00 00 00 00 00 00",
        })

    def emit_group(self, model_item, parent_obj_idx, parent_group_idx):
        name = get_str(model_item, "Name", "Model")
        g_idx = len(self.groups)
        self.groups.append({"name": name, "parent_group": parent_group_idx})

        obj_idx = len(self.objects)
        self.objects.append({
            "type_id": 3,
            "name": name,
            "class": "Group",
            "kind": "group",
            "enabled": True,
            "parent_id": parent_obj_idx,
            "padding_hex": "00 00 00 00 00 00 00 00 00 00 00 00 00",
        })
        return obj_idx, g_idx

    def walk(self, container_item, parent_obj_idx, parent_group_idx, skip_direct_scripts=False):
        """Walk children. Returns index of first part found (for model-script parenting)."""
        first_part_idx = None

        for child in container_item.findall("Item"):
            cls = child.get("class")
            if cls is None:
                continue

            if cls in PART_CLASSES:
                part_obj = convert_part(child, parent_obj_idx, parent_group_idx)
                obj_idx = len(self.objects)
                self.objects.append(part_obj)
                if first_part_idx is None:
                    first_part_idx = obj_idx

                # Scripts directly attached to this part
                for sub in child.findall("Item"):
                    if sub.get("class") in SCRIPT_CLASSES:
                        s = convert_script(sub, obj_idx, part_obj["name"], "part")
                        self.objects.append(s)
                        self.scripts.append(s)

            elif cls == "Model":
                g_obj_idx, g_json_idx = self.emit_group(child, parent_obj_idx, parent_group_idx)

                # Direct scripts on the model
                direct_scripts = [s for s in child.findall("Item")
                                  if s.get("class") in SCRIPT_CLASSES]

                # Recurse into model's other children
                inner_first = self.walk(child, g_obj_idx, g_json_idx,
                                        skip_direct_scripts=True)
                if first_part_idx is None:
                    first_part_idx = inner_first

                # Attach model's direct scripts to the first part
                if inner_first is not None:
                    model_name = get_str(child, "Name", "Model")
                    for sub in direct_scripts:
                        s = convert_script(sub, inner_first, model_name, "part")
                        self.objects.append(s)
                        self.scripts.append(s)

            elif cls == "Folder":
                inner_first = self.walk(child, parent_obj_idx, parent_group_idx)
                if first_part_idx is None:
                    first_part_idx = inner_first

            elif cls in SCRIPT_CLASSES:
                if skip_direct_scripts:
                    continue
                parent_name = self.objects[parent_obj_idx].get("name", "?")
                parent_kind = "service" if parent_obj_idx < 5 else "part"
                s = convert_script(child, parent_obj_idx, parent_name, parent_kind)
                self.objects.append(s)
                self.scripts.append(s)

        return first_part_idx


def build_lighting(lighting_item):
    if lighting_item is None:
        return default_lighting()

    amb_el = _find_prop(lighting_item, "Ambient")
    if amb_el is not None:
        ar = float(amb_el.find("R").text)
        ag = float(amb_el.find("G").text)
        ab = float(amb_el.find("B").text)
    else:
        ar = ag = ab = 0.5

    out_amb = _find_prop(lighting_item, "OutdoorAmbient")
    if out_amb is not None:
        sr = float(out_amb.find("R").text)
        sg = float(out_amb.find("G").text)
        sb = float(out_amb.find("B").text)
    else:
        sr = sg = sb = 1.0

    brightness = get_float(lighting_item, "Brightness", 2.0)
    global_shadows = get_bool(lighting_item, "GlobalShadows", True)

    time_str = get_str(lighting_item, "TimeOfDay", "14:00:00")
    try:
        hh, mm, ss = time_str.split(":")
        clock = float(hh) + float(mm) / 60.0 + float(ss) / 3600.0
    except ValueError:
        clock = 14.0

    angle = math.radians((clock - 6) * 15)
    ca = math.cos(-angle)
    sa = math.sin(-angle)
    # Rotation around X by -angle:
    # [[1, 0, 0],
    #  [0, ca, -sa],
    #  [0, sa, ca]]
    quat = matrix_to_quat(1, 0, 0, 0, ca, -sa, 0, sa, ca)

    return {
        "ambient_color": {"r": r3(ar), "g": r3(ag), "b": r3(ab)},
        "ambient_alpha": 1.0,
        "ambient_brightness": 2500,
        "sun_color": {"r": r3(sr), "g": r3(sg), "b": r3(sb)},
        "sun_alpha": 1.0,
        "sun_brightness": r3((1 + brightness * 2) * 1000),
        "sun_shadows": global_shadows,
        "sun_rotation": {"x": quat[0], "y": quat[1], "z": quat[2], "w": quat[3]},
        "raw_hex": "",
    }


def default_lighting():
    return {
        "ambient_color": {"r": 0.5, "g": 0.5, "b": 0.5},
        "ambient_alpha": 1.0,
        "ambient_brightness": 2500,
        "sun_color": {"r": 1.0, "g": 1.0, "b": 1.0},
        "sun_alpha": 1.0,
        "sun_brightness": 2000,
        "sun_shadows": True,
        "sun_rotation": {"x": -0.488621, "y": 0.0, "z": 0.0, "w": 0.872496},
        "raw_hex": "",
    }


def run(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    services = {}
    for item in root.findall("Item"):
        cls = item.get("class")
        if cls:
            services[cls] = item

    conv = Converter()

    # 1. Emit the five Vortex services in canonical order
    for svc_name, svc_id in SERVICE_ORDER:
        conv.emit_service(svc_name, svc_id)

    # 2. Walk Workspace
    ws = services.get("Workspace")
    if ws is not None:
        conv.walk(ws, 0, None)

    # 3. Walk ReplicatedStorage
    rs = services.get("ReplicatedStorage")
    if rs is not None:
        conv.walk(rs, 2, None)

    # 4. Walk ServerScriptService
    sss = services.get("ServerScriptService")
    if sss is not None:
        conv.walk(sss, 3, None)

    # 5. Walk StarterPlayer -> StarterPlayerScripts
    sp = services.get("StarterPlayer")
    if sp is not None:
        for child in sp.findall("Item"):
            if child.get("class") == "StarterPlayerScripts":
                conv.walk(child, 4, None)
                break

    lighting = build_lighting(services.get("Lighting"))

    output = {
        "version": 1,
        "uuid": uuid.uuid4().hex,
        "object_count": len(conv.objects),
        "scripts": conv.scripts,
        "lighting": lighting,
        "groups": conv.groups,
        "objects": conv.objects,
    }
    return output


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    verbose = any(f in ("-v", "--verbose") for f in flags)

    if not args:
        print("Usage: py RBXLX_to_JSON.py input.rbxlx [output.json] [--verbose]")
        sys.exit(1)

    in_path = Path(args[0])
    out_path = Path(args[1]) if len(args) > 1 else in_path.with_suffix(".json")

    data = run(str(in_path))
    text = json.dumps(data, indent=2)
    out_path.write_text(text, encoding="utf-8")

    parts   = sum(1 for o in data["objects"] if o.get("kind") == "part")
    scripts = len(data["scripts"])
    groups  = len(data["groups"])

    print(f"Saved: {out_path}")
    print(f"  services : 5")
    print(f"  parts    : {parts}")
    print(f"  groups   : {groups}")
    print(f"  scripts  : {scripts}")
    print(f"  total    : {len(data['objects'])}")

    if verbose:
        print("\n" + "=" * 60)
        print(text)
        print("=" * 60)
