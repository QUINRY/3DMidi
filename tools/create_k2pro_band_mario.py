"""Map Mario's lead contour into user-selected directional sound bands.

The mapping preserves rhythm and fits speed to the selected band. It does
not preserve original pitch intervals or establish an audible pitch model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from convert_midi_k2pro import render, reference_manifest, music_limits, FINISH_LIMITS
from convert_poly_midi_u1 import PROFILES, PolyProfile, arrange, read_poly, simulate
from convert_midi_u1 import note_name
from validate_k2pro import kinematics
from validate_u1_gcode import load_planner, require


BANDS = {
    "x12_16": {"axis": 0, "minimum": 12.0, "maximum": 16.0, "observations": ["A07", "A08"]},
    "y025_05": {"axis": 1, "minimum": 0.25, "maximum": 0.5, "observations": ["B01", "B02"]},
}
REFERENCE_LOW, REFERENCE_HIGH = 64, 81  # E4..A5, full range of the first eight seconds


def speed_for(pitch: int, band: dict) -> tuple[int, float]:
    folded = pitch
    while folded < REFERENCE_LOW:
        folded += 12
    while folded > REFERENCE_HIGH:
        folded -= 12
    fraction = (folded - REFERENCE_LOW) / (REFERENCE_HIGH - REFERENCE_LOW)
    return folded, band["minimum"] * (band["maximum"] / band["minimum"]) ** fraction


def route(events: list[dict], lengths: list[float], band: dict) -> list[dict]:
    position, result, i = 135.0, [], 0
    for event in events:
        item = dict(event)
        if item["kind"] == "move":
            position += item["direction"] * lengths[i]
            item["x"], item["y"] = (position, 135.0) if band["axis"] == 0 else (135.0, position)
            i += 1
        result.append(item)
    return result


def plan(frames: list[dict], duration: float, band: dict, planner: dict, profile: PolyProfile):
    events, now, previous, direction, position = [], 0.0, None, 1, 135.0
    for frame in frames:
        if frame["start"] > now + 1e-7:
            events.append({"kind": "rest", "duration": frame["start"] - now})
            previous = None
        source_pitch = frame["target_pitches"][0]
        folded, speed = speed_for(source_pitch, band)
        length = speed * (frame["end"] - frame["start"])
        if previous == source_pitch:
            direction *= -1
        if not 70 <= position + direction * length <= 200:
            direction *= -1
        position += direction * length
        events.append({"kind": "move", "frame": frame["index"], "source_lead": source_pitch,
                       "folded_pitch": folded, "speed": speed, "duration": frame["end"] - frame["start"],
                       "direction": direction, "targets": [source_pitch, source_pitch]})
        now, previous = frame["end"], source_pitch
    if duration > now + 1e-7:
        events.append({"kind": "rest", "duration": duration - now})
    musical = [i for i in events if i["kind"] == "move"]
    lengths = [i["speed"] * i["duration"] for i in musical]
    for iteration in range(100):
        instructions = route(events, lengths, band)
        actual = simulate(instructions, planner, profile)
        require(len(actual) == len(musical), "Reference planner dropped a move")
        errors = [i["duration"] - (m.accel_t + m.cruise_t + m.decel_t) for i, m in zip(musical, actual)]
        if max(abs(e) for e in errors) < 0.000005 and abs(sum(errors)) < 0.001:
            break
        for i, (event, error) in enumerate(zip(musical, errors)):
            speed, time = event["speed"], event["duration"]
            minimum = speed * (time - speed / profile.acceleration)
            lengths[i] = min(speed * time, max(minimum, lengths[i] + 0.85 * speed * error))
    else:
        raise ValueError("Directional timing solver failed")
    for item, move in zip(musical, actual):
        require(abs(move.cruise_v - item["speed"]) < 1e-6, "Note did not reach selected band speed")
    require(all(55 <= item[axis] <= 215 for item in instructions if item["kind"] == "move" for axis in ("x", "y")), "Routing outside music area")
    return instructions, {"iterations": iteration + 1, "max_interval_error_s": max(abs(e) for e in errors)}


def render_band(source: str, frames: list[dict], instructions: list[dict], duration: float,
                band: dict, profile: PolyProfile) -> str:
    text = render(source, frames, instructions, duration, profile)
    text = text.replace("two-voice cold motor music", "directional sound-band melody trial")
    text = text.replace("; Source melody/bass register retained in the selected cadence model",
                        "; Lead only: E4..A5 contour compressed into speed band; outside notes octave-folded")
    text = text.replace("; Pulse-pitch mode is an acoustic hypothesis, not a measured resonance calibration",
                        "; User-selected loudness band; original pitch intervals and audible pitch are NOT established")
    text = re.sub(r"; Acoustic model:[^\n]+", "; Mapping: logarithmic speed contour; not a STEP-to-audible-note calibration", text)
    lookup = {i["frame"]: i for i in instructions if i["kind"] == "move"}
    def event_line(match):
        i = lookup[int(match.group(1))]
        return f"; EVENT {i['frame']:03d} source_lead={note_name(i['source_lead'])} speed={i['speed']:.8f}mm/s"
    return re.sub(r"; EVENT (\d+) targets=[^\n]+", event_line, text)


def validate(path: Path, section: dict, source_notes: list, band: dict, profile: PolyProfile, planner: dict) -> dict:
    text = path.read_text(encoding="ascii")
    before, rest = text.split("; MELODY_BEGIN\n")
    music, after = rest.split("; MELODY_END\n")
    code = lambda s: [l.split(";", 1)[0].strip() for l in s.splitlines() if l.split(";", 1)[0].strip()]
    prefix = code(before)
    require(prefix == ["TURN_OFF_HEATERS", "SAVE_GCODE_STATE NAME=K2PRO_MIDI", "G21", "G90", "M220 S100", "M204 S300",
                       "BED_MESH_CLEAR", "G28 X Y", "M400", "BED_MESH_CLEAR", "G90", "M204 S300",
                       "G1 X135.0000000 Y135.0000000 F1800", "M400", music_limits(profile), "G4 P1000"], "Unsafe startup")
    require(code(after) == ["M400", "M204 S300", "G1 X135.0000000 Y135.0000000 F1800", "M400", FINISH_LIMITS,
                            "RESTORE_GCODE_STATE NAME=K2PRO_MIDI MOVE=0", "TURN_OFF_HEATERS"], "Unsafe finish")
    frames = {f["index"]: f for f in section["frames"]}
    events, targets, parsed, position, event_id = [], [], [], [135.0, 135.0, 20.0, 0.0], None
    kin = kinematics()
    for raw in music.splitlines():
        if raw.startswith("; EVENT "):
            event_id = int(raw.split()[2])
            require(event_id in frames, "Unexpected event")
            events.append(event_id)
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        command, *args = line.split()
        if command == "G4":
            require(len(args) == 1 and args[0].startswith("P"), "Malformed rest")
            delay = float(args[0][1:]) / 1000
            require(0 < delay < 5, "Incorrect rest")
            parsed.append({"kind": "rest", "duration": delay})
            continue
        require(command == "G1" and len(args) == 3, "Unexpected command in music")
        values = {a[0]: float(a[1:]) for a in args}
        require(set(values) == {"X", "Y", "F"} and all(math.isfinite(v) for v in values.values()), "Z, extrusion or invalid motion")
        speed = values["F"] / 60
        require(band["minimum"] - 1e-8 <= speed <= band["maximum"] + 1e-8, "Selected sound band exceeded")
        source_pitch = max(source_notes[i]["pitch"] for i in frames[event_id]["selected_source_ids"])
        _, desired = speed_for(source_pitch, band)
        require(abs(speed - desired) < 1e-7, "Source contour mapping changed")
        end = [values["X"], values["Y"], 20.0, 0.0]
        require(end[1 - band["axis"]] == 135.0, "Directional trial changed the other axis")
        require(abs(end[band["axis"]] - position[band["axis"]]) > 0.001, "Empty motion")
        require(all(55 <= v <= 215 for v in end[:2]), "Out of central area")
        kin.check_move(SimpleNamespace(end_pos=end, axes_d=[end[i] - position[i] for i in range(4)]))
        parsed.append({"kind": "move", "x": end[0], "y": end[1], "speed": speed})
        targets.append(frames[event_id])
        position = end
    require(events == list(frames), "Source rhythm events changed")
    require(len(parsed) == len(section["instructions"]), "Extra rests or missing motion")
    for emitted, wanted in zip(parsed, section["instructions"]):
        require(emitted["kind"] == wanted["kind"], "Articulation changed")
        for key in ("x", "y", "speed") if emitted["kind"] == "move" else ("duration",):
            require(abs(emitted[key] - wanted[key]) < 1e-6, "Emitted route changed")
    actual = simulate(parsed, planner, profile)
    wanted_moves = [i for i in section["instructions"] if i["kind"] == "move"]
    require(len(actual) == len(wanted_moves), "Planner dropped notes")
    max_error = 0.0
    for move, wanted in zip(actual, wanted_moves):
        require(abs(move.cruise_v - wanted["speed"]) < 1e-6, "Selected note speed not reached")
        max_error = max(max_error, abs(move.accel_t + move.cruise_t + move.decel_t - wanted["duration"]))
    require(max_error < 0.00001, "Note interval timing changed")
    total = sum(m.accel_t + m.cruise_t + m.decel_t for m in actual) + sum(i.get("duration", 0) for i in parsed if i["kind"] == "rest")
    require(abs(total - section["duration_s"]) < 0.002, "Overall tempo changed")
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "moves": len(actual),
            "axis": "XY"[band["axis"]], "selected_speed_band_mm_s": [band["minimum"], band["maximum"]],
            "actual_cruise_range_mm_s": [min(m.cruise_v for m in actual), max(m.cruise_v for m in actual)],
            "reference_model_duration_s": total, "explicit_z_moves": 0, "heating_or_extrusion": False,
            "original_pitch_intervals_preserved": False, "audible_pitch_verified": False,
            "physical_printer_tested": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("midi", type=Path)
    parser.add_argument("--planner", type=Path, required=True)
    args = parser.parse_args()
    reference = reference_manifest()
    notes, source = read_poly(args.midi)
    source_notes = [asdict(n) for n in notes]
    frames, _ = arrange(notes, source["duration_s"], PROFILES["balanced"])
    duration = source["duration_s"] / 0.9
    cut = next(f["start"] for f in frames if f["start"] >= 8)
    planner = load_planner(args.planner)
    for name, band in BANDS.items():
        profile = PolyProfile(name, 600, band["maximum"], band["maximum"], 0.9, False, 80)
        report = {"source": source, "source_notes": source_notes, "reference": reference, "band": band,
                  "profile": asdict(profile), "mapping": {"kind": "log_speed_contour", "reference_midi_range": [64, 81],
                  "outside_notes": "octave-folded into E4..A5", "original_pitch_intervals_preserved": False,
                  "user_feedback": "A07 A08 B01 B02 sound good; pitch response not specified"},
                  "physical_printer_tested": False}
        for label, section, section_duration, suffix in [("full", frames, duration, ""),
                ("test", [f for f in frames if f["start"] < cut], cut, "_test")]:
            path = Path(f"mario_k2pro_{name}{suffix}.gcode")
            instructions, stats = plan(section, section_duration, band, planner, profile)
            text = render_band(args.midi.name, section, instructions, section_duration, band, profile)
            path.write_text(text, encoding="ascii")
            data = {"file": path.name, "duration_s": section_duration, "frames": section, "instructions": instructions,
                    "planning": stats}
            data["validation"] = validate(path, data, source_notes, band, profile, planner)
            report[label] = data
            print(json.dumps(data["validation"]))
        Path(f"mario_k2pro_{name}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
