"""Create a gentle, labelled XY sound scan and replay its emitted moves offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

from convert_midi_k2pro import render, music_limits, reference_manifest
from convert_poly_midi_u1 import PolyProfile
from validate_k2pro import kinematics
from validate_u1_gcode import require


SCAN_PROFILE = PolyProfile("sound_scan", 600, 16, 16, 1, True, 80)
SPEEDS = (0.25, 0.5, 1, 2, 4, 8, 12, 16)


def stopped_move_time(distance: float, speed: float, acceleration: float = 600) -> float:
    if distance < speed * speed / acceleration:
        return 2 * math.sqrt(distance / acceleration)
    return distance / speed + speed / acceleration


def create() -> tuple[str, list[dict]]:
    lines, stages, elapsed = [], [], 0.0

    def stage(code: str, label: str):
        lines.extend(["M400", f"; STAGE {code}: {label}", f"M117 {code} {label}"])
        stages.append({"code": code, "label": label, "start_s": elapsed})

    def wait(seconds: float):
        nonlocal elapsed
        lines.append(f"G4 P{seconds * 1000:.6f}")
        elapsed += seconds

    def pair(direction: tuple[float, float], motor_speed: float, seconds: float):
        nonlocal elapsed
        ratio = math.hypot(*direction)
        speed = motor_speed * ratio
        motor_distance = motor_speed * (seconds - speed / SCAN_PROFILE.acceleration)
        x, y = (135 + motor_distance * v for v in direction)
        for ex, ey in ((x, y), (135.0, 135.0)):
            lines.append(f"G1 X{ex:.9f} Y{ey:.9f} F{speed * 60:.7f}")
            lines.append("M400")
            elapsed += seconds

    stage("S00", "stationary baseline")
    wait(2)
    for prefix, name, direction in [
        ("A", "X", (1.0, 0.0)), ("B", "Y", (0.0, 1.0)),
        ("C", "CoreXY_A", (0.5, 0.5)), ("D", "CoreXY_B", (0.5, -0.5)),
    ]:
        for i, speed in enumerate(SPEEDS, 1):
            stage(f"{prefix}{i:02}", f"{name} motor={speed:g}mm/s nominalSTEP={speed * 80:g}Hz")
            pair(direction, speed, 1.0)
            wait(0.35)
    for index, (axis, distance) in enumerate(((0, 0.1), (1, 0.1), (0, 1.0), (1, 1.0)), 1):
        stage(f"P{index:02}", f"{'XY'[axis]} jog={distance:g}mm feed=10mm/s")
        for i in range(6):
            target = [135.0, 135.0]
            if i % 2 == 0:
                target[axis] += distance
            lines.extend([f"G1 X{target[0]:.9f} Y{target[1]:.9f} F600.0000000", "M400"])
            elapsed += stopped_move_time(distance, 10)
            wait(0.2)
    stage("S99", "stationary baseline")
    wait(2)
    lines.extend(["M400", "M117"])
    for i, item in enumerate(stages):
        item["end_s"] = stages[i + 1]["start_s"] if i + 1 < len(stages) else elapsed
    template = render("XY sound diagnostic - no MIDI", [], [], elapsed, SCAN_PROFILE)
    before, tail = template.split("; MELODY_BEGIN\n", 1)
    _, after = tail.split("; MELODY_END\n", 1)
    before = before.replace("; Source melody/bass register retained in the selected cadence model",
                            "; Diagnostic scan: no assumption that audible pitch follows STEP input")
    before = before.replace("two-voice cold motor music", "labelled low-speed XY sound scan")
    before = before.replace("music estimate", "scan estimate")
    before = before.replace("; Pulse-pitch mode is an acoustic hypothesis, not a measured resonance calibration",
                            "; Observe whether audible pitch changes with speed or stays fixed")
    text = before + "; SOUND_SCAN_BEGIN\n" + "\n".join(lines) + "\n; SOUND_SCAN_END\n" + after
    return text, stages


def validate(text: str, stages: list[dict]) -> dict:
    prefix, rest = text.split("; SOUND_SCAN_BEGIN\n")
    scan, suffix = rest.split("; SOUND_SCAN_END\n")
    require(music_limits(SCAN_PROFILE) in prefix, "Wrong scan limits")
    require(prefix.count("G28 X Y\n") == 1, "Missing native XY homing")
    require("BED_MESH_CLEAR\nG28 X Y" in prefix and "G28 X Y\nM400\nBED_MESH_CLEAR" in prefix, "Missing mesh isolation")
    require("RESTORE_GCODE_STATE NAME=K2PRO_MIDI MOVE=0" in suffix, "Moving restore")
    allowed = {"TURN_OFF_HEATERS", "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE", "G21", "G90", "M220", "M204",
               "BED_MESH_CLEAR", "G28", "M400", "G1", "G4", "SET_VELOCITY_LIMIT", "M117"}
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        command, *args = line.split()
        require(command in allowed, "Unexpected scan command")
        if command == "G28":
            require(args == ["X", "Y"], "Unexpected Z homing")
        elif command == "G1":
            require(len(args) == 3 and {a[0] for a in args} == {"X", "Y", "F"}, "Z or extrusion in file")
    elapsed, move_count, measured, position, stage_code = 0.0, 0, [], [135.0, 135.0], None
    bounds = [[135.0], [135.0]]
    kin = kinematics()
    at_rest = True
    for raw in scan.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        command, *args = line.split()
        if command == "M117" and args:
            stage_code = args[0]
            measured.append({"code": stage_code, "start_s": elapsed})
        elif command == "G1":
            require(at_rest, "Scan moves must start at rest")
            values = {a[0]: float(a[1:]) for a in args}
            end = [values["X"], values["Y"]]
            require(all(110 <= v <= 160 for v in end), "Scan left central area")
            speed = values["F"] / 60
            require(0 < speed <= 16, "Scan too fast")
            dx, dy = end[0] - position[0], end[1] - position[1]
            distance = math.hypot(dx, dy)
            move = SimpleNamespace(end_pos=[*end, 20, 0], axes_d=[dx, dy, 0, 0])
            kin.check_move(move)
            if stage_code.startswith(tuple("ABCD")):
                requested = SPEEDS[int(stage_code[1:]) - 1]
                motor_speeds = sorted(abs(d) / distance * speed for d in (dx + dy, dx - dy))
                require(abs(motor_speeds[-1] - requested) < 1e-6, "Incorrect scan motor speed")
                if stage_code.startswith(("A", "B")):
                    require(abs(motor_speeds[0] - requested) < 1e-6, "Axis scan should move both motors")
                else:
                    require(motor_speeds[0] < 1e-6, "Diagonal should isolate one CoreXY motor")
            elapsed += stopped_move_time(distance, speed)
            for i in (0, 1):
                bounds[i].append(end[i])
            position = end
            move_count += 1
            at_rest = False
        elif command == "G4":
            elapsed += float(args[0][1:]) / 1000
            at_rest = True
        elif command == "M400":
            at_rest = True
    require(position == [135, 135], "Scan did not return to centre")
    require(len(measured) == len(stages), "Missing labelled scan stage")
    for actual, expected in zip(measured, stages):
        require(actual["code"] == expected["code"] and abs(actual["start_s"] - expected["start_s"]) < 0.002, "Scan timeline changed")
    return {"estimated_scan_duration_s": elapsed, "xy_moves": move_count, "explicit_z_moves": 0,
            "heating_or_extrusion": False, "x_range_mm": [min(bounds[0]), max(bounds[0])],
            "y_range_mm": [min(bounds[1]), max(bounds[1])], "labelled_stages": len(stages),
            "physical_printer_tested": False, "native_creality_motion_planner_executed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("k2pro_xy_ses_tarama.gcode"))
    args = parser.parse_args()
    reference_manifest()
    text, stages = create()
    validation = validate(text, stages)
    for axis in "XY":
        low, high = validation[axis.lower() + "_range_mm"]
        text = re.sub(rf";MIN{axis}:[^\n]+", f";MIN{axis}:{low:.3f}", text)
        text = re.sub(rf";MAX{axis}:[^\n]+", f";MAX{axis}:{high:.3f}", text)
    args.output.write_text(text, encoding="ascii")
    report = {"file": args.output.name, "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
              "timeline_origin": "S00 after native homing and initial position; timings approximate",
              "stages": stages, "validation": validation}
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    table = ["K2 Pro ses taraması — S00 başlangıcından itibaren yaklaşık süreler", ""]
    table += [f"{s['code']}  {s['start_s']:6.2f}–{s['end_s']:6.2f} sn  {s['label']}" for s in stages]
    args.output.with_name("K2PRO_SES_TARAMA_ASAMALARI.txt").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
