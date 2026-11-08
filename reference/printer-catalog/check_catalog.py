"""Check pinned catalog numbers against saved official snapshots (read-only check)."""
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "app" / "printer_catalog.json"
catalog = json.loads(path.read_text(encoding="utf-8"))
assert len({p["id"] for p in catalog["profiles"]}) == len(catalog["profiles"])
assert next(p for p in catalog["profiles"] if p["id"] == catalog["default_id"])["selectable"]

def parse(text):
    result = {}
    section = None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"\[([^]]+)\]", line)
        if match:
            section = match[1]
            result.setdefault(section, {})
        elif section and ":" in line:
            key, value = line.split(":", 1)
            result[section][key.strip()] = value.strip()
    return result

verified = 0
for profile in catalog["profiles"]:
    if not profile["selectable"]:
        assert profile["status"] in {"requires_config", "unsupported_kinematics"}
        continue
    verified += 1
    source = profile["source"]
    data = (ROOT / source["snapshot"]).read_bytes()
    if source.get("snapshot_sha256"):
        assert hashlib.sha256(data).hexdigest() == source["snapshot_sha256"]
    cfg = parse(data.decode("utf-8"))
    assert cfg["printer"]["kinematics"] == profile["kinematics"]
    for axis in ("x", "y"):
        values = cfg["stepper_" + axis]
        for dst, src, default in (
            ("min", "position_min", 0),
            ("max", "position_max", None),
            ("rotation_distance", "rotation_distance", None),
            ("microsteps", "microsteps", None),
            ("full_steps_per_rotation", "full_steps_per_rotation", 200),
        ):
            expected = float(values[src]) if src in values else default
            assert math.isclose(profile[axis][dst], expected), (profile["id"], axis, dst)
        assert profile[axis]["min"] < profile[axis]["max"]
        assert profile[axis]["rotation_distance"] > 0
        assert profile[axis]["microsteps"] > 0
        assert profile[axis]["full_steps_per_rotation"] > 0
    for field, source_field in (("max_velocity_mm_s", "max_velocity"), ("max_accel_mm_s2", "max_accel")):
        assert math.isclose(profile[field], float(cfg["printer"][source_field]))
        assert math.isfinite(profile[field]) and profile[field] > 0
    assert 0 < profile["music_max_velocity_mm_s"] <= profile["max_velocity_mm_s"]
    assert 0 < profile["music_max_accel_mm_s2"] <= profile["max_accel_mm_s2"]
    for field, source_field in (("square_corner_velocity_mm_s", "square_corner_velocity"),
                                 ("max_accel_to_decel_mm_s2", "max_accel_to_decel"),
                                 ("minimum_cruise_ratio", "minimum_cruise_ratio")):
        if field in profile:
            assert math.isclose(profile[field], float(cfg["printer"][source_field]))
    if profile["id"] != "snapmaker_u1":
        assert profile["startup"] == ("ke_auto_home_slow_z" if profile["id"] == "creality_ender3_v3_ke" else "prepared_only")
print(f"Validated {verified} official-source profiles; {len(catalog['profiles']) - verified} gated catalog entries.")

