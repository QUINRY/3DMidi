"""Reject fast-profile Z moves and any Z motion after fast XY starts."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def check_z_isolation(path: Path, prepared_start: bool = False, xy_home: bool = False,
                      *, xy_home_zero_hop: bool | None = None) -> dict:
    # Keep callers using the former keyword working, without accepting that
    # firmware-specific G-code argument or promising any physical hop height.
    if xy_home_zero_hop is not None:
        xy_home = xy_home or xy_home_zero_hop
    accel = None
    fast_xy_started = False
    z_moves = 0
    xy_homes = 0
    xy_motion_started = False
    for number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        command, *args = code.split()
        if prepared_start and command == "G28":
            if not xy_home or args != ["X", "Y"]:
                raise ValueError(f"Line {number}: only standard G28 X Y homing is permitted")
            if accel != 300.0 or fast_xy_started or xy_motion_started or xy_homes:
                raise ValueError(f"Line {number}: XY homing must run once under the slow startup profile")
            xy_homes += 1
        if prepared_start and command in {"M18", "M84", "PRINT_START", "PRINT_END"}:
            raise ValueError(f"Line {number}: prepared-start file must not disable motors or invoke print macros")
        if prepared_start and re.fullmatch(r"T\d+", command):
            raise ValueError(f"Line {number}: prepared-start file must not change tools")
        if command == "M204":
            accel = float(next(a[1:] for a in args if a.startswith("S")))
            fast_xy_started |= accel > 300.0
        if command in {"G0", "G1"} and any(a.startswith(("X", "Y")) for a in args):
            if xy_home and xy_homes != 1:
                raise ValueError(f"Line {number}: XY movement before homing")
            xy_motion_started = True
        if command in {"G0", "G1"} and any(a.startswith("Z") for a in args):
            if prepared_start:
                raise ValueError(f"Line {number}: any explicit Z move is forbidden in prepared-start mode")
            values = {a[0]: float(a[1:]) for a in args}
            if fast_xy_started:
                raise ValueError(f"Line {number}: Z command after fast XY profile started")
            if accel is None or accel > 300 or not 0 < values.get("F", 0) <= 300:
                raise ValueError(f"Line {number}: Z must explicitly use <=5 mm/s and <=300 mm/s^2")
            if set(values) != {"Z", "F"}:
                raise ValueError(f"Line {number}: setup Z must move separately from XY")
            z_moves += 1
        if command == "G28" and fast_xy_started:
            raise ValueError(f"Line {number}: homing after fast XY started")
        if command in {"SET_MAX_Z_ACCEL", "SET_MAX_Z_VELOCITY", "FORCE_MOVE", "SET_KINEMATIC_POSITION"}:
            raise ValueError(f"Line {number}: forbidden Z/limit override")
    if prepared_start:
        if z_moves:
            raise ValueError("Prepared-start mode contains Z motion")
        if xy_home and xy_homes != 1:
            raise ValueError("Missing XY endstop homing")
        return {"file": path.name, "startup_mode": "xy_home" if xy_home else "already_homed_and_clear",
                "explicit_z_moves": 0, "xy_homing_commands": xy_homes, "z_hop_mm": None,
                "homing_z_behavior": "firmware_default" if xy_home else "not_invoked",
                "firmware_macro_side_effects_verified": False,
                "required_clearance_mm": 20, "clearance_checked_by_file": False}
    if z_moves != 1:
        raise ValueError(f"Expected one slow setup Z move, found {z_moves}")
    return {"file": path.name, "slow_setup_z_moves": z_moves, "z_max_feed_mm_s": 5, "z_setup_accel_mm_s2": 300, "z_after_fast_xy": 0}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("gcode", type=Path, nargs="+")
    p.add_argument("--prepared-start", action="store_true")
    p.add_argument("--xy-home", "--xy-home-zero-hop", dest="xy_home", action="store_true")
    args = p.parse_args()
    for path in args.gcode:
        print(check_z_isolation(path, args.prepared_start or args.xy_home, args.xy_home))
