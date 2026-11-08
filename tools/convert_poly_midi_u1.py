"""Arrange a polyphonic MIDI for two U1 XY motors; keep Z slow and isolated."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import mido

from convert_midi_u1 import Note, frequency, note_name
from validate_u1_gcode import load_planner


BOUNDS = (70.0, 200.0)
START = (135.0, 135.0)
LEGATO_GAP = 0.230
MIN_SOUND = 0.140
CRUISE_RATIO = 0.5


@dataclass(frozen=True)
class PolyProfile:
    name: str
    acceleration: float
    max_speed: float
    max_motor_speed: float
    tempo_ratio: float
    faithful_register: bool
    cadence_per_mm: float = 5.0
    kinematics: str = "corexy"
    cadence_y_per_mm: float = 0.0
    start_xy: tuple = START
    route_bounds: tuple = (70.0, 200.0, 70.0, 200.0)
    physical_bounds: tuple = (55.0, 215.0, 55.0, 215.0)
    firmware_max_velocity: float = 500.0
    square_corner_velocity: float = 8.0
    cruise_ratio: float = CRUISE_RATIO
    smoothing_accel: float = -1.0
    event_ramp_factor: float = 3.0
    music_axes: str = "xy"
    axis_priority: str = "balanced"
    foc_bands: tuple = ()


def motor_vector(a: int, b: int, profile: PolyProfile) -> tuple[float, float, float, float]:
    va = frequency(a) / profile.cadence_per_mm
    if profile.music_axes == "x":
        if profile.kinematics not in {"cartesian", "corexy"}:
            raise ValueError("Unsupported X-only kinematics")
        if profile.kinematics == "corexy" and not math.isclose(
                profile.cadence_per_mm, profile.cadence_y_per_mm or profile.cadence_per_mm):
            raise ValueError("X-only CoreXY melody requires equal motor cadences")
        return va, 0.0, va, va if profile.kinematics == "corexy" else 0.0
    vb = frequency(b) / (profile.cadence_y_per_mm or profile.cadence_per_mm)
    if profile.kinematics == "cartesian":
        vx, vy = va, vb
    elif profile.kinematics == "corexy":
        vx, vy = (va + vb) / 2.0, (va - vb) / 2.0
        if profile.axis_priority == "y":
            vx, vy = vy, vx
    else:
        raise ValueError("Unsupported kinematics")
    return vx, vy, va, vb


def frame_vector(pitches: list[int], profile: PolyProfile) -> tuple[float, float, float, float]:
    return motor_vector(pitches[0], pitches[-1], profile)


def piece_distance(profile: PolyProfile) -> float:
    x0, x1, y0, y1 = profile.route_bounds
    return min(60.0, (x1 - x0) / 2, (y1 - y0) / 2)


PROFILES = {
    "balanced": PolyProfile("balanced", 7000.0, 180.0, 240.0, 0.9, True),
    "fast": PolyProfile("fast", 15000.0, 350.0, 450.0, 1.0, False),
}


def read_poly(path: Path) -> tuple[list[Note], dict]:
    midi = mido.MidiFile(path)
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError("Only synchronous, beat-timed MIDI is supported")
    now, active, notes, tempos = 0.0, {}, [], []
    peak = 0
    for msg in midi:
        now += msg.time
        if msg.type == "set_tempo":
            tempos.append({"time_s": now, "bpm": mido.tempo2bpm(msg.tempo)})
        elif msg.type == "control_change" and msg.control == 64 and msg.value >= 64:
            raise ValueError("Resolve sustain pedal before arrangement")
        elif msg.type == "pitchwheel" and msg.pitch:
            raise ValueError("Resolve pitch bends before arrangement")
        elif msg.type == "note_on" and msg.velocity:
            if msg.channel == 9 or (msg.channel, msg.note) in active:
                raise ValueError("Percussion or overlapping same-pitch notes require a separate arrangement")
            active[msg.channel, msg.note] = (round(now, 9), msg.velocity)
            peak = max(peak, len(active))
        elif msg.type in {"note_off", "note_on"}:
            start, velocity = active.pop((msg.channel, msg.note))
            notes.append(Note(start, round(now, 9), msg.note, velocity, msg.channel))
    if active or not notes:
        raise ValueError("Missing note-offs or empty MIDI")
    notes.sort(key=lambda n: (n.start, n.pitch))
    return notes, {
        "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duration_s": now, "notes": len(notes), "max_polyphony": peak,
        "ticks_per_beat": midi.ticks_per_beat, "tempos": tempos,
    }


def targets(pitches: list[int], profile: PolyProfile) -> tuple[int, ...]:
    if profile.music_axes == "x":
        lead = max(pitches)
        vx, _, _, _ = motor_vector(lead, lead, profile)
        if not 0 <= lead <= 127 or vx > min(profile.max_speed, profile.max_motor_speed):
            raise ValueError("X melody exceeds the speed cap")
        return (lead,)
    if profile.faithful_register:
        # Keep the score's melody contour and bass voicing intact. Moving
        # bass notes into the melody register obscured the original tune.
        lead = max(pitches)
        bass = min(pitches) if len(pitches) > 1 else lead - 12
        if not 0 <= bass <= lead <= 127:
            raise ValueError("Original register cannot be represented")
        if lead == bass:
            bass -= 12
        vx, vy, va, vb = motor_vector(lead, bass, profile)
        if bass < 0 or max(va, vb) > profile.max_motor_speed or math.hypot(vx, vy) > profile.max_speed:
            raise ValueError("Original register exceeds the balanced speed cap")
        return lead, bass
    lead = max(pitches) + 12
    while lead < 78:
        lead += 12
    if lead > 96:
        raise ValueError("Lead exceeds the fast register")
    base = min(pitches) + 36 if len(pitches) > 1 else lead + 12
    while base > 90 and len(pitches) > 1:
        base -= 12
    while base < 78:
        base += 12
    choices = []
    for bass in range(60, 97):
        if bass % 12 != min(pitches) % 12 or bass == lead:
            continue
        vx, vy, va, vb = motor_vector(lead, bass, profile)
        speed = math.hypot(vx, vy)
        if max(va, vb) <= profile.max_motor_speed and speed <= profile.max_speed:
            choices.append((abs(bass - base), -speed, bass))
    if not choices:
        raise ValueError("No bounded two-voice register is available")
    return lead, min(choices)[2]


def arrange(notes: list[Note], duration: float, profile: PolyProfile) -> tuple[list[dict], dict]:
    groups = {}
    for i, note in enumerate(notes):
        groups.setdefault(note.start, []).append((i, note))
    onsets = sorted(groups)
    frames, retained = [], set()
    for i, start in enumerate(onsets):
        group = sorted(groups[start], key=lambda x: x[1].pitch)
        next_start = onsets[i + 1] if i + 1 < len(onsets) else duration
        original_end = max(n.end for _, n in group)
        if original_end > next_start + 1e-7:
            raise ValueError("Staggered overlapping voices require an event-sweep arrangement")
        end = next_start if next_start - original_end <= LEGATO_GAP else min(next_start, max(original_end, start + MIN_SOUND))
        selected = [group[-1]] if profile.music_axes == "x" else [group[0]] if len(group) == 1 else [group[0], group[-1]]
        retained.update(index for index, _ in selected)
        pitches = [n.pitch for _, n in selected]
        target_pitches = list(targets(pitches, profile))
        frames.append({
            "index": i, "start": start / profile.tempo_ratio, "end": end / profile.tempo_ratio,
            "original_end": original_end / profile.tempo_ratio,
            "source_pitches": [n.pitch for _, n in group],
            "selected_source_ids": [index for index, _ in selected],
            "target_pitches": target_pitches,
        })
    return frames, {
        "onset_groups": len(frames), "retained_source_notes": len(retained),
        "omitted_inner_notes": len(notes) - len(retained),
        "solo_octave_doublings": 0 if profile.music_axes == "x" else sum(len(f["source_pitches"]) == 1 for f in frames),
        "legato_gap_threshold_s": LEGATO_GAP / profile.tempo_ratio,
        "minimum_sounding_duration_s": MIN_SOUND / profile.tempo_ratio,
        "source_note_onsets_preserved": profile.tempo_ratio == 1.0,
        "source_note_onsets_uniformly_scaled": True, "tempo_ratio": profile.tempo_ratio,
        "original_melody_register_preserved": profile.faithful_register,
        "description": ("Highest active melody retained for X only; no bass or octave doubling"
                        if profile.music_axes == "x" else "Outer voices retained; inner third chord tone omitted; short gates extended legato"),
    }


def make_toolhead(process, profile: PolyProfile):
    return SimpleNamespace(
        max_accel=profile.acceleration, max_velocity=profile.firmware_max_velocity,
        max_accel_to_decel=(min(profile.smoothing_accel, profile.acceleration) if profile.smoothing_accel >= 0
                            else profile.acceleration * (1.0 - profile.cruise_ratio)),
        junction_deviation=profile.square_corner_velocity ** 2 * (math.sqrt(2.0) - 1.0) / profile.acceleration,
        print_file_line=None, is_calibrating_flow=False,
        extruder=SimpleNamespace(calc_junction=lambda *_: float("inf")),
        _process_moves=process,
    )


def simulate(instructions: list[dict], planner: dict, profile: PolyProfile) -> list:
    moves = []
    toolhead = make_toolhead(moves.extend, profile)
    queue = planner["LookAheadQueue"](toolhead)
    position = [*profile.start_xy, 20.0, 0.0]
    for item in instructions:
        if item["kind"] == "rest":
            queue.flush()
            continue
        end = [item["x"], item["y"], 20.0, 0.0]
        move = planner["Move"](toolhead, position, end, item["speed"])
        queue.add_move(move)
        position = end
    queue.flush()
    return moves


def pieces(frames: list[dict], duration: float, profile: PolyProfile) -> list[dict]:
    result, now = [], 0.0
    previous_targets = None
    for frame in frames:
        if frame["start"] > now + 1e-7:
            result.append({"kind": "rest", "duration": frame["start"] - now})
            previous_targets = None
        target_pitches = frame["target_pitches"]
        if profile.foc_bands:
            velocity = frame["band_speed"]
            vx, vy = (velocity, 0.0) if frame["music_axis"] == "x" else (0.0, velocity)
        else:
            vx, vy, _, _ = frame_vector(target_pitches, profile)
        speed = math.hypot(vx, vy)
        count = max(1, math.ceil(speed * (frame["end"] - frame["start"]) / piece_distance(profile)))
        step_time = (frame["end"] - frame["start"]) / count
        if step_time < profile.event_ramp_factor * speed / profile.acceleration:
            raise ValueError("Event too short to reach its target cruise speed")
        for part in range(count):
            result.append({
                "kind": "move", "frame": frame["index"], "part": part,
                "duration": step_time, "speed": speed,
                "ux": vx / speed, "uy": vy / speed,
                "targets": list(target_pitches),
                "retrigger": part == 0 and previous_targets == target_pitches,
            })
        now = frame["end"]
        previous_targets = target_pitches
    if duration > now + 1e-7:
        result.append({"kind": "rest", "duration": duration - now})
    return result


def route(events: list[dict], lengths: list[float], frozen: list[tuple[float, float]] | None = None,
          profile: PolyProfile | None = None) -> list[dict]:
    profile = profile or PROFILES["balanced"]
    result, x, y, previous, index = [], *profile.start_xy, None, 0
    x0, x1, y0, y1 = profile.route_bounds
    for event in events:
        item = dict(event)
        if item["kind"] == "rest":
            result.append(item)
            previous = None
            continue
        move_index, d = index, lengths[index]
        index += 1
        ux, uy = item["ux"], item["uy"]
        if profile.music_axes == "x" or profile.kinematics == "cartesian" or profile.axis_priority == "y" or profile.foc_bands:
            headings = [(sx * ux, sy * uy) for sx in (1, -1) for sy in (1, -1)]
        elif profile.cadence_y_per_mm and not math.isclose(profile.cadence_per_mm, profile.cadence_y_per_mm):
            headings = [(ux, uy), (-ux, -uy)]
        else:
            headings = [(sx * a, sy * b) for a, b in [(ux, uy), (uy, ux)] for sx in (1, -1) for sy in (1, -1)]
        valid = []
        desired = previous or (profile.start_xy[0] - x, profile.start_xy[1] - y)
        if math.hypot(*desired) < 1e-7:
            desired = (1.0, 1.0)
        for hx, hy in headings:
            ex, ey = x + hx * d, y + hy * d
            if x0 <= ex <= x1 and y0 <= ey <= y1:
                dot = hx * desired[0] + hy * desired[1]
                parallel = previous is not None and hx * previous[0] + hy * previous[1] > 0.999999
                valid.append((bool(item["retrigger"] and parallel), -dot, hx, hy, ex, ey))
        if frozen is not None:
            hx, hy = frozen[move_index]
            ex, ey = x + hx * d, y + hy * d
        elif not valid:
            raise ValueError("No bounded XY direction")
        else:
            _, _, hx, hy, ex, ey = min(valid)
        item.update({"start_x": x, "start_y": y, "x": ex, "y": ey, "heading": [hx, hy]})
        result.append(item)
        x, y, previous = ex, ey, (hx, hy)
    return result


def plan(frames: list[dict], duration: float, planner: dict, profile: PolyProfile) -> tuple[list[dict], dict]:
    events = pieces(frames, duration, profile)
    musical = [item for item in events if item["kind"] == "move"]
    lengths = [item["speed"] * item["duration"] for item in musical]
    total_iterations = 0
    for routing_pass in range(12):
        seed = route(events, lengths, profile=profile)
        frozen = [tuple(item["heading"]) for item in seed if item["kind"] == "move"]
        for iteration in range(100):
            total_iterations += 1
            instructions = route(events, lengths, frozen, profile)
            actual = simulate(instructions, planner, profile)
            errors = [item["duration"] - (m.accel_t + m.cruise_t + m.decel_t) for item, m in zip(musical, actual)]
            if len(actual) != len(musical):
                raise ValueError("Planner dropped a motion")
            worst = max(abs(e) for e in errors)
            if worst < 0.000005 and abs(sum(errors)) < 0.001:
                break
            for i, (item, error) in enumerate(zip(musical, errors)):
                speed, target = item["speed"], item["duration"]
                minimum = speed * (target - speed / profile.acceleration)
                lengths[i] = min(speed * target, max(minimum, lengths[i] + 0.85 * speed * error))
        else:
            raise ValueError(f"Continuous timing solver did not converge: worst {worst:.6f}s, total {sum(errors):.6f}s")
        x0, x1, y0, y1 = profile.physical_bounds
        if all(x0 <= item["x"] <= x1 and y0 <= item["y"] <= y1 for item in instructions if item["kind"] == "move"):
            break
    else:
        raise ValueError("No converged trajectory remains inside physical bounds")
    for item, move in zip(musical, actual):
        if abs(move.cruise_v - item["speed"]) > 1e-6:
            raise ValueError("A short event cannot reach its intended motor frequencies")
    return instructions, {
        "solver_iterations": total_iterations, "routing_passes": routing_pass + 1, "worst_piece_timing_error_s": worst,
        "total_timing_error_s": -sum(errors), "moves": len(actual),
        "musical_rests": sum(i["kind"] == "rest" for i in instructions),
        "forced_note_end_stops": 0,
    }


def envelope(template: Path, source: str, duration: float, groups: int, profile: PolyProfile, startup_mode: str) -> tuple[list[str], list[str]]:
    xy_home = startup_mode in {"xy_home", "xy_home_zero_hop"}
    text = template.read_text(encoding="ascii")
    prefix = text.split("; EXECUTABLE_BLOCK_START\n", 1)[0].splitlines()
    footer = text.split("; EXECUTABLE_BLOCK_END\n", 1)[1].splitlines()
    if any(line.strip() and not line.startswith(";") for line in prefix + footer):
        raise ValueError("Metadata template contains executable commands")
    replacements = {
        "; generated by ": "; generated by Snapmaker Orca 2.4.0 on " + datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d at %H:%M:%S"),
        "; Compatibility marker": "; Compatibility marker above; actual generator: KlipperMIDI v7 two-voice XY",
        "; Source:": "; Source: " + json.dumps(source, ensure_ascii=True),
        "; Melody:": f"; Melody: {duration:.6f} seconds, {groups} onset groups, two independent motor voices",
        "; Motion profile:": f"; Motion profile: {profile.name}; maximum toolhead speed {profile.max_speed:.0f} mm/s; tempo {profile.tempo_ratio:.0%}",
        "; Temporary acceleration:": f"; XY-only acceleration: {profile.acceleration:.0f} mm/s^2; no explicit Z positioning",
        "; Melody area:": "; Melody area: X55..215 Y55..215; Z remains at the operator-prepared height",
        "; Uses native G28": ("; Native G28 X Y; firmware-default homing/Z hop; REQUIRE >=20 mm clearance, cold printer, clear plate"
                              if xy_home else
                              "; Prepared printer required: already homed, motors enabled, cold, clear plate, clearance >=20 mm"),
        "; Every melody": "; Two independent CoreXY motor cadences; no Z words anywhere in the music block",
        "; Input shaping, motor current": ("; Music uses existing driver settings; XY homing uses the stock U1 routine"
                                          if xy_home else
                                          "; Input shaping, motor current and microstep settings are not modified"),
        "; estimated printing time": f"; estimated printing time (normal mode) = {math.ceil(duration)}s",
    }
    def replace(lines):
        return [next((replacement for key, replacement in replacements.items() if line.startswith(key)), line) for line in lines]
    return replace(prefix), replace(footer)


def render(template: Path, source: str, frames: list[dict], instructions: list[dict], duration: float, profile: PolyProfile, startup_mode: str,
           clear_mesh_before_home: bool = False) -> str:
    prefix, footer = envelope(template, source, duration, len(frames), profile, startup_mode)
    lines = prefix + [
        "; EXECUTABLE_BLOCK_START", "TURN_OFF_HEATERS",
        "SAVE_GCODE_STATE NAME=U1_MIDI", "G90", "M220 S100", "M204 S300",
        "; No full XYZ homing, explicit Z positioning, tool changes, or motor-off commands",
    ] + (["BED_MESH_CLEAR"] if clear_mesh_before_home else []) + (["G28 X Y", "M400"] if startup_mode in {"xy_home", "xy_home_zero_hop"} else []) + [
        "BED_MESH_CLEAR",
        "; Clear active mesh compensation in RAM so XY cannot introduce hidden Z corrections",
        "G1 X135.0000000 Y135.0000000 F1800", "M400",
        "; STARTUP_FINISHED - no explicit Z positioning; native homing uses firmware defaults",
        f"M204 S{profile.acceleration:.0f}", "G4 P1000", "; MELODY_BEGIN",
    ]
    previous_frame = None
    for item in instructions:
        if item["kind"] == "rest":
            lines.append(f"G4 P{item['duration'] * 1000:.6f}")
        else:
            if item["frame"] != previous_frame:
                a, b = item["targets"]
                lines.append(f"; EVENT {item['frame']:03d} targets={note_name(a)},{note_name(b)}")
                previous_frame = item["frame"]
            lines.append(f"G1 X{item['x']:.7f} Y{item['y']:.7f} F{item['speed'] * 60:.5f}")
    lines += [
        "; MELODY_END", "M400", "M204 S300", "G1 X135.0000000 Y135.0000000 F1800", "M400",
        "RESTORE_GCODE_STATE NAME=U1_MIDI MOVE=0", "TURN_OFF_HEATERS", "; EXECUTABLE_BLOCK_END",
    ] + footer
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("midi", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--profile", choices=PROFILES, default="balanced")
    p.add_argument("--startup", choices=["xy-home", "prepared"], default="xy-home")
    p.add_argument("--template", type=Path, default=Path("childomine_u1_xy_fast.gcode"))
    p.add_argument("--planner", type=Path, required=True)
    args = p.parse_args()
    profile = PROFILES[args.profile]
    startup_mode = "xy_home" if args.startup == "xy-home" else "prepared_no_z"
    suffix = "xyhome" if args.startup == "xy-home" else "noz"
    output = args.output or Path(f"mario_u1_xy_{args.profile}_{suffix}.gcode")
    notes, source = read_poly(args.midi)
    frames, arrangement = arrange(notes, source["duration_s"], profile)
    duration = source["duration_s"] / profile.tempo_ratio
    planner = load_planner(args.planner)
    cut = next((f["start"] for f in frames if f["start"] >= 8.0), duration)
    sections = [("full", frames, duration, output),
                ("test", [f for f in frames if f["start"] < cut], cut, output.with_name(output.stem + "_test.gcode"))]
    report = {"source": source, "arrangement": arrangement, "source_notes": [asdict(n) for n in notes],
              "profile": asdict(profile),
              "xy_acceleration_mm_s2": profile.acceleration, "max_xy_speed_mm_s": profile.max_speed, "max_motor_speed_mm_s": profile.max_motor_speed,
              "startup_mode": startup_mode, "explicit_z_moves": 0, "xy_homing_commands": int(args.startup == "xy-home"),
              "z_hop_mm": None, "homing_z_behavior": "firmware_default" if args.startup == "xy-home" else "no_homing",
              "required_clearance_mm": 20.0, "clearance_checked_by_file": False,
              "z_motion_during_music": False,
              "bed_mesh_compensation_during_music": "cleared in RAM; stored calibration is retained",
              "metadata_template_sha256": hashlib.sha256(args.template.read_bytes()).hexdigest(), "physical_printer_tested": False}
    outputs = []
    for label, section, section_duration, path in sections:
        instructions, stats = plan(section, section_duration, planner, profile)
        outputs.append((path, render(args.template, args.midi.name, section, instructions, section_duration, profile, startup_mode)))
        report[label] = {"file": path.name, "duration_s": section_duration, "frames": section, "instructions": instructions, "planning": stats,
                         "startup_mode": startup_mode, "profile": asdict(profile)}
        print(json.dumps({"section": label, "duration_s": section_duration, **stats}))
    for path, text in outputs:
        path.write_text(text, encoding="ascii")
    output.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
