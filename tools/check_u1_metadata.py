"""Check a file using the official U1 Moonraker metadata parser, offline."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path


PARSER_SHA256 = "07c1e72d9f0cbcc2d6dfc3021c1b1bd9c6727ec20c2623463e1722cd3e756c7a"


def load_parser(path: Path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != PARSER_SHA256:
        raise ValueError("Unexpected U1 metadata parser source")
    spec = importlib.util.spec_from_file_location("u1_official_metadata", path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    return parser


def check(parser, path: Path, cold: bool = False, identity_only: bool = False) -> dict:
    slicer, identity = parser.get_slicer(str(path))
    identity = identity or {"slicer": "unknown"}
    known = identity.get("slicer", "unknown").lower() != "unknown"
    result = {"file": path.name, "identity": identity, "known_gcode_type": known}
    if not known:
        result["error"] = "Unrecognized Gcode type"
        return result
    if identity_only:
        return result
    try:
        metadata = result["metadata"] = parser.extract_metadata(str(path), False)
        if cold:
            text = path.read_text(encoding="ascii")
            expected = {
                "slicer": "SnapmakerOrca", "filament_type": "PLA",
                "filament_total": 0.0, "filament_weight_total": 0.0,
                "first_layer_extr_temp": 0.0, "first_layer_bed_temp": 0.0,
                "chamber_temp": 0.0, "layer_count": 1,
                "filament_used_mm": [0.0], "nozzle_temp": [0.0],
                "nozzle_diameter_list": [0.4, 0.4, 0.4, 0.4],
            }
            for key, value in expected.items():
                if metadata.get(key) != value:
                    raise ValueError(f"Invalid cold-motion metadata: {key}={metadata.get(key)!r}")
            for block in ["HEADER", "EXECUTABLE", "CONFIG"]:
                if text.count(f"; {block}_BLOCK_START") != 1 or text.count(f"; {block}_BLOCK_END") != 1:
                    raise ValueError(f"Missing/duplicate {block} block")
            density = re.search(r"^; filament_density = ([0-9.]+)$", text, re.M)
            if density is None or float(density.group(1)) <= 0:
                raise ValueError("Missing or zero filament density")
            before, rest = text.split("; EXECUTABLE_BLOCK_START\n", 1)
            _, after = rest.split("; EXECUTABLE_BLOCK_END\n", 1)
            if any(line.strip() and not line.startswith(";") for line in (before + after).splitlines()):
                raise ValueError("Executable command outside executable block")
            result["cold_motion_metadata"] = "passed"
    except Exception as error:
        result["error"] = str(error)
    return result


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("gcode", nargs="+", type=Path)
    args.add_argument("--metadata-source", type=Path, required=True)
    args.add_argument("--cold", action="store_true", help="Check the cold-motion metadata contract")
    args.add_argument("--identity-only", action="store_true", help="Identify a reference without extracting thumbnails")
    options = args.parse_args()
    parser = load_parser(options.metadata_source)
    results = [check(parser, path.resolve(), options.cold, options.identity_only) for path in options.gcode]
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r["known_gcode_type"] and "error" not in r for r in results) else 1)


if __name__ == "__main__":
    main()
