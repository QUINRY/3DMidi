"""Check Bambu catalog facts against pinned official preset snapshots."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = Path(__file__).resolve().parent
catalog = json.loads((ROOT / "app/bambu_catalog.json").read_text(encoding="utf-8"))


def checked_source(source):
    assert source["commit"] == catalog["source_commit"]
    data = (ROOT / source["snapshot"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == source["snapshot_sha256"], source["snapshot"]
    assert source["url"].startswith("https://github.com/bambulab/BambuStudio/blob/")
    return json.loads(data)


def resolve(stem):
    data = json.loads((SNAPSHOTS / (stem + ".json")).read_text(encoding="utf-8"))
    parent = data.get("inherits")
    result = resolve(parent) if parent else {}
    result.update(data)
    return result


ids = set()
available = 0
for profile in catalog["profiles"]:
    assert profile["id"] not in ids
    ids.add(profile["id"])
    source = checked_source(profile["source"])
    start = checked_source(profile["sound_source"])["machine_start_gcode"]
    checked_source(profile["end_source"])
    if isinstance(start, list):
        start = "\n".join(start)
    commands = [line.split(";", 1)[0].strip() for line in start.splitlines()]
    tones = [line for line in commands if re.match(r"^M1006(?:\s|$)", line)]
    present = "M1006 S1" in tones and "M1006 W" in tones
    assert present == profile["selectable"]
    assert present == profile["native_music"]["present_in_official_startup"]
    assert len(tones) == profile["native_music"]["source_startup_active_M1006_count"]
    assert profile["firmware_family"] == "bambu"
    assert profile["music_mode"] == "bambu_native"
    assert profile["native_music"]["channels"] == ["X", "Y"]
    assert profile["native_music"]["muted_channels"] == ["Z"]
    assert "x" not in profile and "y" not in profile
    complete = resolve(source["name"])
    vertices = [tuple(map(float, xy.strip().split("x"))) for xy in complete["printable_area"]]
    xs, ys = zip(*vertices)
    assert profile["build_volume_mm"] == [max(xs) - min(xs), max(ys) - min(ys), float(complete["printable_height"])]
    assert profile["max_velocity_mm_s"] == min(float(complete["machine_max_speed_x"][0]), float(complete["machine_max_speed_y"][0]))
    assert profile["max_accel_mm_s2"] == min(float(complete["machine_max_acceleration_x"][0]), float(complete["machine_max_acceleration_y"][0]))
    available += present
for source in catalog["inherited_sources"]:
    checked_source(source)
assert len(ids) == 15 and available == 12
print(f"Validated {len(ids)} official Bambu profiles: {available} native sound, {len(ids) - available} unverified/disabled.")
