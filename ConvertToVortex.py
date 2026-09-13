#!/usr/bin/env python3
"""
ConvertToVortex.py

Converts a Roblox `.rbxlx` file to a Vortex `.vrtx` file in two steps:
    1. RBXLX_to_JSON.py  (rbxlx → json)
    2. JSON_to_VRTX.py   (json → vrtx)

Search order (same layout rule for both folders):

    Converters:
      1. HERE / "_Convertions"
      2. HERE.parent / "_Convertions"
      3. HERE
      4. HERE.parent

    Target files:
      1. HERE / "TargetFiles"
      2. HERE.parent / "TargetFiles"
      3. HERE
      4. HERE.parent

Usage:
    py ConvertToVortex.py [filename.rbxlx] [output.vrtx] [--verbose] [--keep-json]

If no filename is given, the script lists every `.rbxlx` in the first
`TargetFiles` folder it finds and asks which one to convert.
"""

import sys
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent

CONVERTER_CANDIDATES = [
    HERE / "_Convertions",
    HERE.parent / "_Convertions",
    HERE,
    HERE.parent,
]

TARGET_CANDIDATES = [
    HERE / "TargetFiles",
    HERE.parent / "TargetFiles",
    HERE,
    HERE.parent,
]


def find_converters_dir():
    for c in CONVERTER_CANDIDATES:
        if (c / "RBXLX_to_JSON.py").exists() and (c / "JSON_to_VRTX.py").exists():
            return c
    return None


def find_targets_dir():
    for c in TARGET_CANDIDATES:
        if c.is_dir():
            return c
    return None


def list_targets(folder, ext):
    return sorted(folder.glob(f"*{ext}"))


def pick_target(folder, ext):
    files = list_targets(folder, ext)
    if not files:
        print(f"No {ext} files found in {folder}")
        sys.exit(1)

    if len(files) == 1:
        print(f"Found one file: {files[0].name}")
        return files[0]

    print(f"\nFound {len(files)} {ext} files in {folder}:")
    for i, f in enumerate(files, 1):
        print(f"  [{i}] {f.name}")

    while True:
        try:
            choice = input("\nPick a number (or 'q' to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if choice.lower() == "q":
            sys.exit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            return files[int(choice) - 1]
        print("Invalid choice, try again.")


def run(cmd, verbose):
    if verbose:
        subprocess.run(cmd, check=True)
    else:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)


def main():
    args  = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]

    verbose   = any(f in ("-v", "--verbose") for f in flags)
    keep_json = "--keep-json" in flags

    converters_dir = find_converters_dir()
    if converters_dir is None:
        print("Error: couldn't find the converter scripts.")
        print("Looked in:")
        for c in CONVERTER_CANDIDATES:
            print(f"  {c}")
        print("Expected to find RBXLX_to_JSON.py and JSON_to_VRTX.py there.")
        sys.exit(1)

    targets_dir = find_targets_dir()
    if targets_dir is None:
        print("Error: couldn't find a TargetFiles folder.")
        print("Looked in:")
        for c in TARGET_CANDIDATES:
            print(f"  {c}")
        sys.exit(1)

    if args:
        first = Path(args[0])
        resolved = first.resolve()
        if resolved.exists():
            in_path = resolved
        else:
            found = None
            for c in TARGET_CANDIDATES:
                candidate = c / first.name
                if candidate.exists():
                    found = candidate.resolve()
                    break
            if not found:
                print(f"Error: '{first.name}' not found.")
                print("Looked in:")
                for c in TARGET_CANDIDATES:
                    print(f"  {c}")
                sys.exit(1)
            in_path = found
    else:
        in_path = pick_target(targets_dir, ".rbxlx")

    if not in_path.exists():
        print(f"Error: {in_path} not found")
        sys.exit(1)

    if in_path.suffix.lower() != ".rbxlx":
        print(f"Warning: input is not a .rbxlx file ({in_path.suffix}), continuing anyway")

    json_path = in_path.with_suffix(".json")
    out_path  = Path(args[1]).resolve() if len(args) > 1 else in_path.with_suffix(".vrtx")

    print(f"Converters : {converters_dir}")
    print(f"Target     : {in_path.name}")
    print(f"[1/2] {in_path.name} -> {json_path.name}")
    try:
        run([sys.executable, str(converters_dir / "RBXLX_to_JSON.py"), str(in_path)], verbose)
    except subprocess.CalledProcessError as e:
        print("RBXLX_to_JSON.py failed:")
        if e.stderr:
            print(e.stderr.decode(errors="replace"))
        sys.exit(1)

    print(f"[2/2] {json_path.name} -> {out_path.name}")
    try:
        run([sys.executable, str(converters_dir / "JSON_to_VRTX.py"),
             str(json_path), str(out_path)], verbose)
    except subprocess.CalledProcessError as e:
        print("JSON_to_VRTX.py failed:")
        if e.stderr:
            print(e.stderr.decode(errors="replace"))
        sys.exit(1)

    if not keep_json and json_path.exists():
        try:
            json_path.unlink()
        except OSError:
            pass

    print(f"\nDone. Output: {out_path}")


if __name__ == "__main__":
    main()
