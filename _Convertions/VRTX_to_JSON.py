from pathlib import Path
import zstandard as zstd
import io
import struct
import json
import pyperclip

# =========================================================
#  VERSIONING
# =========================================================
SUPPORTED_VRTX_CONTAINER_VERSION = 4
SUPPORTED_JSON_PAYLOAD_VERSION   = 1
DOWNLOAD_URL = "https://github.com/YOUR-REPO/vortex-converter/releases/latest"


def _check_version(label, found, supported, older_hint):
    if found > supported:
        raise SystemExit(
            f"[{label}] File version is {found}, but this converter only supports up to {supported}.\n"
            f"  Download a newer converter: {DOWNLOAD_URL}"
        )
    if found < supported:
        print(
            f"[{label}] WARNING: file is version {found}, converter expects {supported}.\n"
            f"  Trying anyway. If parsing fails, {older_hint.lower()}"
        )


# =========================================================
#  TYPE TABLES (v0.4 format)
# =========================================================
SERVICE_TYPES = {
    0:  "Workspace",
    1:  "Lighting",
    10: "ReplicatedStorage",
    11: "StarterPlayerScripts",
    12: "ServerScriptService",
}
SCRIPT_TYPES = {
    7:  "LocalScript",
    8:  "Script",
    13: "RemoteEvent",
    14: "BindableEvent",
    15: "RemoteFunction",
}
MATERIAL_NAMES = {
    0: "Smooth", 1: "Plastic", 2: "Wood", 3: "Metal",
    4: "Grass", 5: "Ice", 6: "Paint",
}
SCRIPT_TRAILING_LEN = {"Script": 10, "LocalScript": 10,
                       "RemoteEvent": 1, "BindableEvent": 1, "RemoteFunction": 1}
PARENT_IDS = {
    0: "Workspace", 1: "Lighting", 2: "ReplicatedStorage",
    3: "ServerScriptService", 4: "StarterPlayerScripts",
}


# =========================================================
#  DECOMPRESSION + VERSION CHECK
# =========================================================
def decompress_vrtx(path):
    data = Path(path).read_bytes()
    magic = bytes([0x28, 0xB5, 0x2F, 0xFD])
    pos = data.find(magic)
    if pos == -1:
        raise SystemExit("Zstd magic not found")

    if pos >= 1:
        _check_version(
            "VRTX", data[pos - 1], SUPPORTED_VRTX_CONTAINER_VERSION,
            "Re-save the project in Vortex Studio by making a small edit."
        )

    dctx = zstd.ZstdDecompressor()
    with dctx.stream_reader(io.BytesIO(data[pos:])) as reader:
        dec = reader.read()

    if len(dec) >= 1:
        _check_version(
            "VRTX-Payload", dec[0], SUPPORTED_JSON_PAYLOAD_VERSION,
            "Re-save the project in Vortex Studio."
        )

    return dec


# =========================================================
#  NEXT-OBJECT SEARCH (used to end a Part's child blob)
# =========================================================
def find_next_object_header(dec, start, end):
    """Scan for the next plausible (type_id, name_len, name) triple."""
    VALID = set(SERVICE_TYPES.keys()) | set(SCRIPT_TYPES.keys()) | {2, 3}
    for q in range(start, end - 12):
        t = struct.unpack("<I", dec[q:q+4])[0]
        if t not in VALID:
            continue
        n = struct.unpack("<Q", dec[q+4:q+12])[0]
        if not (1 <= n <= 200):
            continue
        if q + 12 + n > end:
            continue
        name_bytes = dec[q+12:q+12+n]
        if all(32 <= b < 127 for b in name_bytes):
            return q
    return None


# =========================================================
#  LIGHTING (last 57 bytes)
# =========================================================
def parse_lighting(dec):
    if len(dec) < 57:
        return None
    block = dec[-57:]
    amb_r, amb_g, amb_b, amb_a, amb_br = struct.unpack("<5f", block[0:20])
    sun_r, sun_g, sun_b, sun_a, sun_br = struct.unpack("<5f", block[20:40])
    shadows = block[40]
    rot = struct.unpack("<4f", block[41:57])
    return {
        "ambient_color": {"r": amb_r, "g": amb_g, "b": amb_b},
        "ambient_alpha": amb_a,
        "ambient_brightness": amb_br,
        "sun_color": {"r": sun_r, "g": sun_g, "b": sun_b},
        "sun_alpha": sun_a,
        "sun_brightness": sun_br,
        "sun_shadows": bool(shadows),
        "sun_rotation": {"x": rot[0], "y": rot[1], "z": rot[2], "w": rot[3]},
        "raw_hex": block.hex(" ").upper(),
    }


# =========================================================
#  MAIN PARSER
# =========================================================
def parse_vrtx(path):
    dec = decompress_vrtx(path)

    p = 0
    version = dec[p]; p += 1
    uuid_len = struct.unpack("<Q", dec[p:p+8])[0]; p += 8
    uuid = dec[p:p+uuid_len].decode("ascii", "replace"); p += uuid_len
    object_count = struct.unpack("<Q", dec[p:p+8])[0]; p += 8

    data_end = len(dec) - 57

    objects = []
    scripts = []

    for i in range(object_count):
        if p + 12 > data_end:
            break

        type_id = struct.unpack("<I", dec[p:p+4])[0]; p += 4
        name_len = struct.unpack("<Q", dec[p:p+8])[0]; p += 8

        if not (1 <= name_len <= 200) or p + name_len > data_end:
            print(f"[warn] object {i}: bad name_len={name_len} at 0x{p-8:X}")
            break

        name = dec[p:p+name_len].decode("utf-8", "replace"); p += name_len

        obj = {"type_id": type_id, "name": name}

        # ---------- SERVICES ----------
        if type_id in SERVICE_TYPES:
            obj["kind"] = "service"
            obj["class"] = SERVICE_TYPES[type_id]
            obj["payload_hex"] = dec[p:p+14].hex(" ").upper()
            p += 14

        # ---------- PARTS ----------
        elif type_id == 2:
            obj["kind"] = "part"
            obj["class"] = "Part"
            obj["enabled"] = bool(dec[p]); p += 1
            obj["parent_id"] = struct.unpack("<Q", dec[p:p+8])[0]; p += 8
            obj["flag2"] = dec[p]; p += 1

            inner_name_len = struct.unpack("<Q", dec[p:p+8])[0]; p += 8
            obj["inner_name"] = dec[p:p+inner_name_len].decode("utf-8", "replace")
            p += inner_name_len

            floats = struct.unpack("<14f", dec[p:p+56])
            obj["position"] = list(floats[0:3])
            obj["rotation"] = list(floats[3:7])
            obj["size"]     = list(floats[7:10])
            obj["color"]    = {"r": floats[10], "g": floats[11],
                               "b": floats[12], "a": floats[13]}
            obj["transparency"] = 1.0 - floats[13]
            p += 56

            material_id = struct.unpack("<I", dec[p:p+4])[0]; p += 4
            obj["material_id"] = material_id
            obj["material"] = MATERIAL_NAMES.get(material_id, f"Unknown({material_id})")

            obj["flags"] = list(dec[p:p+6]); p += 6

            # child blob ends where the next object begins
            next_p = find_next_object_header(dec, p, data_end)
            if next_p is None:
                next_p = data_end
            obj["child_blob_hex"] = dec[p:next_p].hex(" ").upper()
            p = next_p
        # ---------- GROUPS ----------
        elif type_id == 3:
            obj["kind"] = "group"
            obj["class"] = "Group"
            obj["enabled"] = bool(dec[p]); p += 1
            obj["parent_id"] = struct.unpack("<Q", dec[p:p+8])[0]; p += 8
            obj["padding_hex"] = dec[p:p+13].hex(" ").upper(); p += 13

        # ---------- SCRIPTS / REMOTES ----------
        elif type_id in SCRIPT_TYPES:
            obj["kind"] = "script"
            obj["class"] = SCRIPT_TYPES[type_id]
            obj["enabled"] = bool(dec[p]); p += 1
            obj["parent_id"] = struct.unpack("<Q", dec[p:p+8])[0]; p += 8
            obj["parent_name"] = PARENT_IDS.get(obj["parent_id"])

            obj["marker"] = struct.unpack("<I", dec[p:p+4])[0]; p += 4

            source_len = struct.unpack("<Q", dec[p:p+8])[0]; p += 8
            obj["source"] = dec[p:p+source_len].decode("utf-8", "replace"); p += source_len

            trailing = SCRIPT_TRAILING_LEN.get(obj["class"], 0)
            obj["trailing_hex"] = dec[p:p+trailing].hex(" ").upper(); p += trailing

            scripts.append(obj)

        else:
            obj["kind"] = "unknown"
            obj["class"] = f"Unknown({type_id})"
            print(f"[warn] unknown type_id={type_id} at object {i}")

        objects.append(obj)

    lighting = parse_lighting(dec)

    # ---- Build groups array and set per-part group index ----
    obj_to_group_idx = {}
    groups_out = []
    for i, obj in enumerate(objects):
        if obj.get("kind") == "group":
            obj_to_group_idx[i] = len(groups_out)
            groups_out.append({
                "name": obj["name"],
                "parent_group": None,
                "_raw_parent_id": obj.get("parent_id", 0),
            })

    for g in groups_out:
        pid = g.pop("_raw_parent_id")
        g["parent_group"] = obj_to_group_idx.get(pid)

    for obj in objects:
        if obj.get("kind") == "part":
            pid = obj.get("parent_id")
            obj["group"] = obj_to_group_idx.get(pid) if pid is not None else None

    return {
        "version": version,
        "uuid": uuid,
        "object_count": object_count,
        "scripts": scripts,
        "lighting": lighting,
        "groups": groups_out,      # ← new (was missing)
        "objects": objects,
    }


if __name__ == "__main__":
    import sys

    # Parse args: positional file, optional --verbose / -v flag anywhere
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    verbose = any(f in ("-v", "--verbose") for f in flags)

    file = args[0] if args else "showcase.vrtx"
    result = parse_vrtx(file)

    out_path = Path(file).with_suffix(".json")
    json_text = json.dumps(result, indent=2)
    out_path.write_text(json_text)
    pyperclip.copy(json_text)

    # ---- summary ----
    services = sum(1 for o in result["objects"] if o["kind"] == "service")
    parts    = sum(1 for o in result["objects"] if o["kind"] == "part")
    scripts  = sum(1 for o in result["objects"] if o["kind"] == "script")

    print(f"Saved: {out_path}")
    print(f"  services : {services}")
    print(f"  parts    : {parts}")
    print(f"  scripts  : {scripts}")
    print(f"  total    : {len(result['objects'])}")
    print(f"  copied to clipboard ✓")

    if verbose:
        print("\n" + "=" * 60)
        print(json_text)
        print("=" * 60)
