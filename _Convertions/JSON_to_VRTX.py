import io
import json
import struct
from pathlib import Path
import zstandard as zstd

# =========================================================
#  VERSIONING
# =========================================================
SUPPORTED_JSON_VERSION     = 1   # the "version" field this converter supports
CONTAINER_VERSION_TO_WRITE = 4   # byte we write after "VRTX" in the output file
DOWNLOAD_URL = "https://github.com/YOUR-REPO/vortex-converter/releases/latest"


def _check_json_version(data):
    v = int(data.get("version", 1))
    if v < SUPPORTED_JSON_VERSION:
        raise SystemExit(
            f"[JSON] File version {v} is older than this converter supports ({SUPPORTED_JSON_VERSION}).\n"
            f"  This JSON was produced by an older plugin or converter.\n"
            f"  Regenerate it with the current plugin."
        )
    if v > SUPPORTED_JSON_VERSION:
        raise SystemExit(
            f"[JSON] File version {v} is newer than this converter supports ({SUPPORTED_JSON_VERSION}).\n"
            f"  Download a newer converter: {DOWNLOAD_URL}"
        )


# =========================================================
#  CONSTANTS
# =========================================================
SERVICE_TYPES = {
    0: "Workspace",
    1: "Lighting",
    10: "ReplicatedStorage",
    11: "StarterPlayerScripts",
    12: "ServerScriptService",
}
SCRIPT_TYPES = {
    7: "LocalScript",
    8: "Script",
    13: "RemoteEvent",
    14: "BindableEvent",
    15: "RemoteFunction",
}
MATERIAL_NAMES = {
    "Smooth": 0, "Plastic": 1, "Wood": 2, "Metal": 3,
    "Grass": 4, "Ice": 5, "Paint": 6,
}
DEFAULT_SCRIPT_TRAILING = {
    7:  "01 00 00 00 00 00 00 00 00 00",
    8:  "01 00 00 00 00 00 00 00 00 00",
    13: "00",
    14: "00",
    15: "00",
}
SCRIPT_MARKER_BYTES_SCRIPT = 0x01000000
SCRIPT_MARKER_BYTES_REMOTE = 0


def normalize_marker(marker, type_id):
    default = SCRIPT_MARKER_BYTES_SCRIPT if type_id in (7, 8) else SCRIPT_MARKER_BYTES_REMOTE
    if marker is None:
        return default
    marker = int(marker)
    if marker == 1:
        return SCRIPT_MARKER_BYTES_SCRIPT
    if marker == 0:
        return SCRIPT_MARKER_BYTES_REMOTE
    return marker


# =========================================================
#  BUILD
# =========================================================
def build_vrtx(data):
    _check_json_version(data)

    version = int(data.get("version", 1))
    uuid = data["uuid"]
    objects = data.get("objects", [])
    lighting = data.get("lighting")

    out = bytearray()
    out.append(version)
    uuid_bytes = uuid.encode("utf-8")
    out += struct.pack("<Q", len(uuid_bytes))
    out += uuid_bytes
    out += struct.pack("<Q", len(objects))

    for obj in objects:
        kind = obj.get("kind")
        type_id = int(obj["type_id"])
        name = obj.get("name", "").encode("utf-8")

        out += struct.pack("<I", type_id)
        out += struct.pack("<Q", len(name))
        out += name

        # ---------- SERVICES ----------
        if kind == "service":
            ph = obj.get("payload_hex", "00 " * 14).replace(" ", "")
            if len(ph) != 28:
                ph = "00" * 14
            out += bytes.fromhex(ph)
        # ---------- GROUPS ----------
        elif kind == "group":
            out.append(1)  # enabled/flag
            out += struct.pack("<Q", int(obj.get("parent_id", 0)))
            out += b"\x00" * 13  # reserved
        # ---------- PARTS ----------
        elif kind == "part":
            out.append(1 if obj.get("enabled", True) else 0)
            out += struct.pack("<Q", int(obj.get("parent_id", 0)))
            out.append(int(obj.get("flag2", 1)) & 0xFF)

            inner_name = obj.get("inner_name", obj.get("name", "")).encode("utf-8")
            out += struct.pack("<Q", len(inner_name))
            out += inner_name

            pos   = obj.get("position", [0.0, 0.0, 0.0])
            rot   = obj.get("rotation", [0.0, 0.0, 0.0, 1.0])
            size  = obj.get("size", [1.0, 1.0, 1.0])
            color = obj.get("color", {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0})

            out += struct.pack("<3f", float(pos[0]), float(pos[1]), float(pos[2]))
            out += struct.pack("<4f", float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3]))
            out += struct.pack("<3f", float(size[0]), float(size[1]), float(size[2]))
            out += struct.pack("<4f",
                float(color.get("r", 1)), float(color.get("g", 1)),
                float(color.get("b", 1)), float(color.get("a", 1)))

            mat_name = obj.get("material", "Plastic")
            mat_id = int(obj.get("material_id", MATERIAL_NAMES.get(mat_name, 1)))
            out += struct.pack("<I", mat_id)

            flags = obj.get("flags", [0, 1, 1, 1, 0, 0])
            for i in range(6):
                out.append((flags[i] if i < len(flags) else 0) & 0xFF)

            cb_hex = obj.get("child_blob_hex", "").replace(" ", "")
            if cb_hex:
                out += bytes.fromhex(cb_hex)

        # ---------- SCRIPTS / REMOTES ----------
        elif kind == "script":
            out.append(1 if obj.get("enabled", True) else 0)
            out += struct.pack("<Q", int(obj.get("parent_id", 5)))

            marker_val = normalize_marker(obj.get("marker", None), type_id)
            out += struct.pack("<I", marker_val)

            source = (obj.get("source") or "").encode("utf-8")
            out += struct.pack("<Q", len(source))
            out += source

            th = obj.get("trailing_hex", "").replace(" ", "")
            if th:
                out += bytes.fromhex(th)
            else:
                default = DEFAULT_SCRIPT_TRAILING.get(type_id, "00")
                out += bytes.fromhex(default.replace(" ", ""))

        else:
            raise ValueError(f"Unknown object kind: {kind!r} (type_id={type_id})")

    # ---------- LIGHTING ----------
    if lighting:
        amb = lighting.get("ambient_color", {"r": 1, "g": 1, "b": 1})
        sun = lighting.get("sun_color", {"r": 1, "g": 1, "b": 1})
        sr  = lighting.get("sun_rotation", {"x": 0, "y": 0, "z": 0, "w": 1})
        out += struct.pack("<4f",
            float(amb.get("r", 1)), float(amb.get("g", 1)), float(amb.get("b", 1)),
            float(lighting.get("ambient_alpha", 1)))
        out += struct.pack("<f", float(lighting.get("ambient_brightness", 0)))
        out += struct.pack("<4f",
            float(sun.get("r", 1)), float(sun.get("g", 1)), float(sun.get("b", 1)),
            float(lighting.get("sun_alpha", 1)))
        out += struct.pack("<f", float(lighting.get("sun_brightness", 0)))
        out.append(1 if lighting.get("sun_shadows", True) else 0)
        out += struct.pack("<4f",
            float(sr.get("x", 0)), float(sr.get("y", 0)),
            float(sr.get("z", 0)), float(sr.get("w", 1)))
    else:
        out += struct.pack("<4f", 1.0, 1.0, 1.0, 1.0)
        out += struct.pack("<f", 0.0)
        out += struct.pack("<4f", 1.0, 1.0, 1.0, 1.0)
        out += struct.pack("<f", 0.0)
        out.append(1)
        out += struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)

    # ---------- COMPRESSION ----------
    # Compress normally, then rewrite the zstd frame header to match Vortex's format.
    # Vortex writes:  28 B5 2F FD  00  68  <blocks>
    #   FHD = 0x00  →  FCS_flag=0, single_segment=0, no checksum
    #   WD  = 0x68  →  window_log = 23 (8 MB)
    cctx = zstd.ZstdCompressor(write_content_size=False)
    raw = cctx.compress(bytes(out))

    fhd = raw[4]
    single_segment = (fhd >> 5) & 1
    header_len = 5 + (0 if single_segment else 1)

    tail = raw[header_len:]
    compressed = b"\x28\xB5\x2F\xFD" + b"\x00\x68" + tail

    return b"VRTX" + bytes([CONTAINER_VERSION_TO_WRITE]) + compressed


# =========================================================
#  ENTRYPOINT
# =========================================================
if __name__ == "__main__":
    import sys
    import traceback

    # Parse args: positional files, optional --verbose / -v flag anywhere
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    verbose = any(f in ("-v", "--verbose") for f in flags)

    if not args:
        print("Usage: py JSON_to_VRTX.py input.json [output.vrtx] [--verbose]")
        sys.exit(1)

    input_path = Path(args[0])
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    output_path = Path(args[1]) if len(args) > 1 else input_path.with_suffix(".vrtx")

    try:
        file_bytes = build_vrtx(data)
    except SystemExit:
        raise
    except Exception:
        print("=== BUILD FAILED ===")
        traceback.print_exc()
        sys.exit(1)

    with open(output_path, "wb") as f:
        f.write(file_bytes)

    # ---- summary ----
    objects = data.get("objects", [])
    services = sum(1 for o in objects if o.get("kind") == "service")
    parts    = sum(1 for o in objects if o.get("kind") == "part")
    scripts  = sum(1 for o in objects if o.get("kind") == "script")

    print(f"Saved: {output_path}  ({len(file_bytes)} bytes)")
    print(f"  services : {services}")
    print(f"  parts    : {parts}")
    print(f"  scripts  : {scripts}")
    print(f"  total    : {len(objects)}")

    if verbose:
        print("\n" + "=" * 60)
        # Dump the raw .vrtx bytes as text (garbage chars expected — it's binary)
        print(file_bytes.decode("utf-8", errors="replace"))
        print("=" * 60)
