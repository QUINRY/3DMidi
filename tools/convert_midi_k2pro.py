"""Create cold XY-only Mario motion for the stock Creality K2 Pro profile.

Uses the existing two-voice arrangement and a Klipper reference look-ahead
model. Creality's compiled native motion planner and servo acoustics are
not executed or validated by that model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

from convert_midi_u1 import note_name
from convert_poly_midi_u1 import PROFILES, PolyProfile, arrange, plan, read_poly
from validate_u1_gcode import load_planner


REFERENCE_COMMIT = "bc0a52078ace1e4d82995e396b38457b9f441024"
REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "k2pro-bc0a52078ace"
PROFILE = PROFILES["balanced"]
K2_PROFILES = {
    "balanced": PROFILE,
    "pulse-pitch": PolyProfile("pulse_pitch", 600.0, 12.0, 15.0, 0.9, True, 80.0),
}
MUSIC_LIMITS = "SET_VELOCITY_LIMIT VELOCITY=180 ACCEL=7000 ACCEL_TO_DECEL=3500 SQUARE_CORNER_VELOCITY=8"
FINISH_LIMITS = "SET_VELOCITY_LIMIT VELOCITY=600 ACCEL=5000 ACCEL_TO_DECEL=5000 SQUARE_CORNER_VELOCITY=10"


def reference_manifest() -> dict:
    manifest = json.loads((REFERENCE / "manifest.json").read_text(encoding="utf-8"))
    if manifest["commit"] != REFERENCE_COMMIT:
        raise ValueError("Unexpected K2 reference commit")
    for name, sha256 in manifest["sha256"].items():
        if hashlib.sha256((REFERENCE / name).read_bytes()).hexdigest() != sha256:
            raise ValueError("Changed K2 reference: " + name)
    return manifest


def music_limits(profile: PolyProfile) -> str:
    return (f"SET_VELOCITY_LIMIT VELOCITY={profile.max_speed:g} ACCEL={profile.acceleration:g} "
            f"ACCEL_TO_DECEL={profile.acceleration / 2:g} SQUARE_CORNER_VELOCITY=8")


def render(source: str, frames: list[dict], instructions: list[dict], duration: float,
           profile: PolyProfile = PROFILE) -> str:
    moves = [i for i in instructions if i["kind"] == "move"]
    xvalues = [135.0] + [i["x"] for i in moves]
    yvalues = [135.0] + [i["y"] for i in moves]
    lines = [
        "; Generator: KlipperMIDI - two-voice cold motor music",
        "; Printer: Creality K2 Pro (300 x 300 x 300 mm), F012 stock profile",
        "; Source: " + json.dumps(source, ensure_ascii=True),
        ";TIME:" + str(math.ceil(duration)),
        "; Time above is the music estimate; native XY homing takes additional time",
        ";Machine Height:300", ";Machine Width:300", ";Machine Depth:300",
        f";MINX:{min(xvalues):.3f}", f";MINY:{min(yvalues):.3f}", ";MINZ:20.000",
        f";MAXX:{max(xvalues):.3f}", f";MAXY:{max(yvalues):.3f}", ";MAXZ:20.000",
        "; Z metadata is a preview reference only; this file does not position Z",
        ";LAYER_COUNT:1", ";Layer height:0.2",
        "; One virtual layer for job metadata; no printing or material consumption",
        ";Material Type:PLA", ";Material Name:Motor music - zero material usage",
        ";Filament used:0.0m", ";Filament Weight:0.0",
        ";Print Temperature:0", ";Bed Temperature:0",
        "; REQUIRE: idle cold printer, empty plate, normal speed mode",
        "; REQUIRE: Z already homed using stock controls, motors still enabled, clearance >=20 mm",
        "; Native G28 X Y may move Z when that prerequisite is not met",
        "; No Z positioning, heating, extrusion, tool change or PRINT_START/END calls in this file",
        "; XY rotation_distance=40 mm; 200 configured full steps/rev; microsteps=16",
        f"; Acoustic model: nominal {'STEP-input' if profile.cadence_per_mm == 80 else 'full-step'} cadence {profile.cadence_per_mm:g}/mm; audible tone unverified",
        f"; Profile {profile.name}: XY <={profile.max_speed:g} mm/s, acceleration {profile.acceleration:g} mm/s^2, tempo {profile.tempo_ratio:.0%}",
        "; Source melody/bass register retained in the selected cadence model",
        "; Pulse-pitch mode is an acoustic hypothesis, not a measured resonance calibration",
        "; Timing uses a Klipper reference model, not the compiled Creality planner",
        "; Motion settings are temporary; finish selects 600 mm/s, 5000 mm/s^2, SCV=10",
        "; Firmware source: https://github.com/CrealityOfficial/K2_Series_Klipper/tree/" + REFERENCE_COMMIT,
        "; EXECUTABLE_BEGIN",
        "TURN_OFF_HEATERS", "SAVE_GCODE_STATE NAME=K2PRO_MIDI", "G21", "G90", "M220 S100", "M204 S300",
        "BED_MESH_CLEAR", "G28 X Y", "M400", "BED_MESH_CLEAR", "G90", "M204 S300",
        "G1 X135.0000000 Y135.0000000 F1800", "M400", music_limits(profile), "G4 P1000", "; MELODY_BEGIN",
    ]
    previous_frame = None
    coordinate_digits, feed_digits = (9, 7) if profile.cadence_per_mm == 80 else (7, 5)
    for item in instructions:
        if item["kind"] == "rest":
            lines.append(f"G4 P{item['duration'] * 1000:.6f}")
        else:
            if item["frame"] != previous_frame:
                a, b = item["targets"]
                lines.append(f"; EVENT {item['frame']:03d} targets={note_name(a)},{note_name(b)}")
                previous_frame = item["frame"]
            lines.append(f"G1 X{item['x']:.{coordinate_digits}f} Y{item['y']:.{coordinate_digits}f} F{item['speed'] * 60:.{feed_digits}f}")
    lines += [
        "; MELODY_END", "M400", "M204 S300", "G1 X135.0000000 Y135.0000000 F1800", "M400",
        FINISH_LIMITS, "RESTORE_GCODE_STATE NAME=K2PRO_MIDI MOVE=0", "TURN_OFF_HEATERS", "; EXECUTABLE_END",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("midi", type=Path)
    parser.add_argument("--planner", type=Path, required=True, help="Pinned Klipper reference planner, not native K2 binary")
    parser.add_argument("--profile", choices=K2_PROFILES, default="balanced")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    profile = K2_PROFILES[args.profile]
    args.output = args.output or Path(f"mario_k2pro_xy_{profile.name}.gcode")
    manifest = reference_manifest()
    notes, source = read_poly(args.midi)
    frames, arrangement = arrange(notes, source["duration_s"], profile)
    planner = load_planner(args.planner)
    duration = source["duration_s"] / profile.tempo_ratio
    cut = next((f["start"] for f in frames if f["start"] >= 8.0), duration)
    report = {
        "printer": "Creality K2 Pro", "reference": manifest, "source": source,
        "source_notes": [asdict(n) for n in notes], "profile": asdict(profile), "arrangement": arrangement,
        "acoustic_hypothesis": {"cadence_per_mm": profile.cadence_per_mm,
                                "basis": "nominal_STEP_input" if profile.cadence_per_mm == 80 else "nominal_full_step",
                                "configured_steps_per_mm": 200 * 16 / 40,
                                "confirmed_by_recording": False},
        "startup": {"command": "G28 X Y", "requires_previously_homed_z": True,
                    "requires_enabled_motors": True, "requires_normal_speed_mode": True,
                    "required_clearance_mm": 20, "clearance_measured_by_file": False,
                    "stock_macro_can_move_z_if_unprepared": True},
        "timing_model": {"kind": "Klipper reference look-ahead; not the compiled Creality motion planner",
                         "source_sha256": hashlib.sha256(args.planner.read_bytes()).hexdigest(),
                         "max_accel_to_decel_mm_s2": profile.acceleration / 2, "square_corner_velocity_mm_s": 8},
        "physical_printer_tested": False, "servo_acoustics_verified": False,
    }
    outputs = []
    for label, section, section_duration, path in [
        ("full", frames, duration, args.output),
        ("test", [f for f in frames if f["start"] < cut], cut, args.output.with_name(args.output.stem + "_test.gcode")),
    ]:
        instructions, stats = plan(section, section_duration, planner, profile)
        text = render(args.midi.name, section, instructions, section_duration, profile)
        report[label] = {"file": path.name, "duration_s": section_duration, "frames": section,
                         "instructions": instructions, "reference_model_planning": stats}
        outputs.append((path, text))
        print(json.dumps({"section": label, "music_duration_s": section_duration, "moves": stats["moves"]}))
    for path, text in outputs:
        path.write_text(text, encoding="ascii")
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
