"""Convert a monophonic MIDI into bounded, cold Snapmaker U1 motion.

No printer connection is made. The acoustic mapping is an initial full-step
cadence model; the dominant audible harmonic needs a physical listening test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mido


SOURCE_COMMIT = "7ac453b50fe6779b2ec0b759038a17da5e6d671d"
SOURCE_BASE = f"https://github.com/Snapmaker/u1-klipper/blob/{SOURCE_COMMIT}"
ROTATION_DISTANCE = 40.0
FULL_STEPS_PER_ROTATION = 200
MICROSTEPS = 64
X_MIN, X_MAX, Y_MIN, Y_MAX, Z = 55.0, 215.0, 55.0, 215.0, 20.0
# These eight headings vary both axes while keeping the two CoreXY motor
# speeds in an exact 2:1 ratio. A 45-degree diagonal would stop one motor.
HEADINGS = ((3, 1), (1, 3), (-1, 3), (-3, 1), (-3, -1), (-1, -3), (1, -3), (3, -1))
LEAD_MOTOR_GAIN = 4.0 / math.sqrt(10.0)
CRUISE_RATIO = 0.5
ARTICULATION = 0.012
NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass(frozen=True)
class MotionProfile:
    name: str
    acceleration: float
    max_toolhead_speed: float
    max_motor_speed: float
    default_transpose: int


PROFILES = {
    "normal": MotionProfile("normal", 3000.0, 100.0, 100.0, -12),
    "fast": MotionProfile("fast", 10000.0, 350.0, 450.0, 12),
}


@dataclass(frozen=True)
class Note:
    start: float
    end: float
    pitch: int
    velocity: int
    channel: int


def note_name(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def frequency(pitch: int) -> float:
    return 440.0 * 2.0 ** ((pitch - 69) / 12.0)


def read_notes(path: Path) -> tuple[list[Note], dict]:
    midi = mido.MidiFile(path)
    if midi.type == 2:
        raise ValueError("Asynchronous type-2 MIDI is unsupported")
    if midi.ticks_per_beat <= 0:
        raise ValueError("SMPTE time division is unsupported")
    now = 0.0
    active: dict[tuple[int, int], tuple[float, int]] = {}
    notes: list[Note] = []
    tempo_changes = []
    for msg in midi:
        now += msg.time
        if msg.type == "set_tempo":
            tempo_changes.append({"time_s": now, "bpm": mido.tempo2bpm(msg.tempo)})
        elif msg.type == "control_change" and msg.control == 64 and msg.value >= 64:
            raise ValueError("Resolve sustain pedal events before conversion")
        elif msg.type == "pitchwheel" and msg.pitch != 0:
            raise ValueError("Resolve pitch bends before conversion")
        elif msg.type == "note_on" and msg.velocity:
            if active:
                raise ValueError("This converter requires a monophonic melody")
            if msg.channel == 9:
                raise ValueError("MIDI percussion cannot be mapped to pitched notes")
            active[msg.channel, msg.note] = now, msg.velocity
        elif msg.type in {"note_off", "note_on"}:
            key = msg.channel, msg.note
            if key not in active:
                raise ValueError(f"Unmatched note-off: {key}")
            start, velocity = active.pop(key)
            if now <= start:
                raise ValueError("Zero-duration note")
            notes.append(Note(start, now, msg.note, velocity, msg.channel))
    if active:
        raise ValueError("MIDI ends with held notes")
    if not notes:
        raise ValueError("MIDI contains no pitched notes")
    notes.sort(key=lambda n: n.start)
    return notes, {
        "source_file": path.name,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "midi_type": midi.type,
        "ticks_per_beat": midi.ticks_per_beat,
        "midi_duration_s": now,
        "note_count": len(notes),
        "tempo_changes": tempo_changes,
        "tracks": [track.name for track in midi.tracks],
        "source_pitch_range": [note_name(min(n.pitch for n in notes)), note_name(max(n.pitch for n in notes))],
    }


def plan_note(
    note: Note, position: tuple[float, float], transpose: int,
    cadence_scale: float, heading_index: int,
    profile: MotionProfile = PROFILES["normal"],
) -> tuple[list[dict], tuple[float, float]]:
    pitch = note.pitch + transpose
    if not 0 <= pitch <= 127:
        raise ValueError("Transposition exceeds MIDI pitch range")
    target_hz = frequency(pitch)
    # CoreXY A=X+Y, B=X-Y. For a 3:1 (or 1:3) heading, the faster
    # motor travels 4/sqrt(10) times as far as the toolhead. Compensate
    # the vector feedrate so the melody retains its intended cadence.
    lead_motor_speed = target_hz * ROTATION_DISTANCE / FULL_STEPS_PER_ROTATION * cadence_scale
    speed = lead_motor_speed / LEAD_MOTOR_GAIN
    if not 0 < speed <= profile.max_toolhead_speed:
        raise ValueError(f"{note_name(pitch)} needs {speed:.3f} mm/s; cap is {profile.max_toolhead_speed}")
    if lead_motor_speed > profile.max_motor_speed:
        raise ValueError("Motor-equivalent speed exceeds the profile cap")
    duration = note.end - note.start
    gap = min(ARTICULATION, duration * 0.1)
    motion_time = duration - gap
    # A rest-to-rest trapezoid at cruise speed v lasts d/v + v/a.
    # Subtract its acceleration overhead rather than adding it to MIDI time.
    full_distance = speed * (motion_time - speed / profile.acceleration)
    x, y = position
    candidates = []
    for offset in range(len(HEADINGS)):
        heading = (heading_index + offset) % len(HEADINGS)
        hx, hy = HEADINGS[heading]
        ux, uy = hx / math.sqrt(10.0), hy / math.sqrt(10.0)
        room_x = (X_MAX - x) / ux if ux > 0 else (X_MIN - x) / ux
        room_y = (Y_MAX - y) / uy if uy > 0 else (Y_MIN - y) / uy
        candidates.append((min(room_x, room_y), ux, uy, heading))
    # Prefer a heading that rotates with each note. Near the boundary,
    # choose another heading that fits, or equal alternating strokes.
    selected = next((c for c in candidates if full_distance <= c[0]), None)
    if selected is None:
        selected = max(candidates, key=lambda c: c[0])
    room, ux, uy, heading = selected
    if room <= 0:
        raise ValueError("No room for a bounded melody stroke")
    # One maximal rest-to-rest stroke takes room/v + v/a seconds.
    # Split long high-speed notes into as many bounded strokes as needed.
    maximum_stroke_time = room / speed + speed / profile.acceleration
    strokes = max(1, math.ceil(motion_time / maximum_stroke_time))
    if strokes > 128:
        raise ValueError("Note requires too many direction changes")
    stroke_time = motion_time / strokes
    distance = speed * (stroke_time - speed / profile.acceleration)
    min_distance = speed * speed / (profile.acceleration * (1.0 - CRUISE_RATIO))
    if distance <= 0 or distance < min_distance - 1e-9:
        raise ValueError(f"{note_name(pitch)} is too short to reach its target speed")
    if distance > room + 1e-8:
        raise ValueError("Note cannot fit the central motion area")
    moves = []
    for stroke in range(strokes):
        end_x, end_y = x + ux * distance, y + uy * distance
        if not (X_MIN - 1e-8 <= end_x <= X_MAX + 1e-8 and Y_MIN - 1e-8 <= end_y <= Y_MAX + 1e-8):
            raise ValueError("Planned motion leaves the central area")
        moves.append({
            "start_x": x,
            "start_y": y,
            "end_x": end_x,
            "end_y": end_y,
            "duration_s": stroke_time,
            "cruise_mm_s": speed,
            "target_pitch": pitch,
            "target_hz": target_hz,
            "companion_hz": target_hz / 2.0,
            "heading_index": heading if stroke % 2 == 0 else (heading + 4) % len(HEADINGS),
            "gap_after_s": gap if stroke == strokes - 1 else 0.0,
        })
        x, y = end_x, end_y
        ux, uy = -ux, -uy
    return moves, (x, y)


def render(
    notes: list[Note], name: str, transpose: int, cadence_scale: float,
    profile: MotionProfile = PROFILES["normal"],
) -> tuple[str, dict]:
    if not (0 < profile.acceleration <= 20000 and 0 < profile.max_toolhead_speed <= 500
            and 0 < profile.max_motor_speed <= 500):
        raise ValueError("Profile exceeds the published stock U1 motion limits")
    duration = notes[-1].end
    generated_at = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d at %H:%M:%S")
    lines = [
        "; HEADER_BLOCK_START",
        f"; generated by Snapmaker Orca 2.4.0 on {generated_at}",
        f"; Compatibility marker above; actual generator: KlipperMIDI, MIDI motion format v4 XY {profile.name}",
        "; total layer number: 1",
        "; One virtual motion segment; no material layer is printed",
        "; filament_density: 1.24",
        "; filament_diameter: 1.75",
        f"; max_z_height: {Z:.2f}",
        "; HEADER_BLOCK_END",
        "",
        "; Snapmaker U1 - cold stepper-motor melody",
        f"; Source: {json.dumps(name, ensure_ascii=True)}",
        f"; Melody: {duration:.6f} seconds, {len(notes)} notes, transpose {transpose:+d} semitones",
        "; Stock U1 CoreXY, XY rotation_distance=40 mm, 200 full steps/rev, microsteps=64",
        "; Acoustic assumption: full-step cadence; actual audible harmonic is unverified",
        f"; Motion profile: {profile.name}; maximum toolhead speed {profile.max_toolhead_speed:.0f} mm/s",
        f"; Temporary acceleration: {profile.acceleration:.0f} mm/s^2; stock minimum_cruise_ratio=0.5 assumed",
        f"; Melody area: X{X_MIN:.0f}..{X_MAX:.0f} Y{Y_MIN:.0f}..{Y_MAX:.0f} Z{Z:.0f}",
        "; Every melody stroke changes X and Y; CoreXY motor cadences are melody + lower octave",
        "; Run standalone, on an idle cold printer with an empty build plate",
        "; Uses native G28 homing; no PRINT_START, extrusion, or heating commands",
        "; Input shaping, motor current and microstep settings are not modified",
        "; Physical sound and firmware/job-UI behavior require an on-printer test",
        f"; Profile source: {SOURCE_BASE}/lava/printer.cfg",
        "; EXECUTABLE_BLOCK_START",
        "TURN_OFF_HEATERS",
        "G90",
        "G28",
        "SAVE_GCODE_STATE NAME=U1_MIDI",
        "M220 S100",
        "G90",
        "M204 S300",
        "BED_MESH_CLEAR",
        f"G1 Z{Z:.3f} F300",
        "M400",
        f"G1 X{X_MIN:.7f} Y{Y_MIN:.7f} F3600",
        "M400",
        f"M204 S{profile.acceleration:.0f}",
        "G4 P1000",
        "; MELODY_BEGIN",
    ]
    position, now = (X_MIN, Y_MIN), 0.0
    moves = []
    stroke_counts = []
    for i, note in enumerate(notes, 1):
        if note.start > now + 1e-9:
            lines.append(f"G4 P{(note.start - now) * 1000:.6f}")
        elif note.start < now - 1e-8:
            raise ValueError("Overlapping notes")
        planned, position = plan_note(note, position, transpose, cadence_scale, (i - 1) % len(HEADINGS), profile)
        stroke_counts.append(len(planned))
        lines.append(
            f"; NOTE {i:03d} source={note_name(note.pitch)} target={note_name(note.pitch + transpose)} "
            f"start={note.start:.6f}s duration={note.end - note.start:.6f}s"
        )
        for move in planned:
            lines.append(f"G1 X{move['end_x']:.7f} Y{move['end_y']:.7f} F{move['cruise_mm_s'] * 60:.5f}")
            # G4 also flushes Klipper look-ahead, guaranteeing rest-to-rest
            # motion even when two successive notes share a travel direction.
            lines.append(f"G4 P{move['gap_after_s'] * 1000:.6f}")
            moves.append(move)
        now = note.end
    lines += [
        "; MELODY_END",
        "M400",
        "G1 X135.00000 Y135.00000 F3600",
        "M400",
        "; U1 fork restores acceleration as well as speed/mode with MOVE=0",
        "RESTORE_GCODE_STATE NAME=U1_MIDI MOVE=0",
        "TURN_OFF_HEATERS",
        "; End - motors remain enabled for the normal firmware idle timeout",
        "; EXECUTABLE_BLOCK_END",
        "",
        "; filament used [mm] = 0.00",
        "; filament used [cm3] = 0.00",
        "; filament used [g] = 0.00",
        "; total filament used [g] = 0.00",
        "; total layers count = 1",
        f"; estimated printing time (normal mode) = {math.ceil(duration)}s",
        "; Estimate describes the melody only; native homing time is additional",
        "",
        "; CONFIG_BLOCK_START",
        "; Actual generator: KlipperMIDI; Snapmaker Orca identification is for U1 interoperability",
        "; printer_model = Snapmaker U1",
        "; printer_settings_id = Snapmaker U1 (0.4 nozzle)",
        "; printer_technology = FFF",
        "; gcode_flavor = klipper",
        "; printable_area = 0.5x1,270.5x1,270.5x271,0.5x271",
        "; printable_height = 270.05",
        "; print_sequence = by layer",
        "; layer_height = 0.2",
        "; first_layer_height = 0.2",
        "; filament_colour = #FFFFFF",
        "; filament_colour_mode = 0",
        "; filament_density = 1.24",
        "; filament_diameter = 1.75",
        "; filament_type = PLA",
        "; filament_vendor = Snapmaker",
        '; filament_settings_id = "PLA metadata only - zero material usage"',
        "; filament_volume_type = standard",
        "; filament_flow_ratio = 1",
        "; filament_max_volumetric_speed = 20",
        "; filament_retract_length_toolchange = 0",
        "; nozzle_diameter = 0.4,0.4,0.4,0.4",
        "; nozzle_temperature = 0",
        "; nozzle_temperature_initial_layer = 0",
        "; first_layer_temperature = 0",
        "; first_layer_bed_temperature = 0",
        "; chamber_temperature = 0",
        "; CONFIG_BLOCK_END",
    ]
    return "\n".join(lines) + "\n", {
        "melody_duration_s": duration,
        "note_count": len(notes),
        "transpose_semitones": transpose,
        "cadence_scale": cadence_scale,
        "cadence_model": "full_steps_per_rotation / rotation_distance; not STEP pulse frequency",
        "motion_mode": "xy_octaves",
        "z_isolated": True,
        "motion_profile": profile.name,
        "acceleration_mm_s2": profile.acceleration,
        "max_toolhead_speed_mm_s": profile.max_toolhead_speed,
        "max_motor_speed_mm_s": profile.max_motor_speed,
        "assumed_minimum_cruise_ratio": CRUISE_RATIO,
        "start_position_mm": [X_MIN, Y_MIN, Z],
        "motion_bounds_mm": {"x": [X_MIN, X_MAX], "y": [Y_MIN, Y_MAX]},
        "corexy_motor_cadence_ratio": [2, 1],
        "acoustic_pitch_verified": False,
        "target_pitch_range": [note_name(min(n.pitch for n in notes) + transpose), note_name(max(n.pitch for n in notes) + transpose)],
        "max_melody_speed_mm_s": max(m["cruise_mm_s"] for m in moves),
        "max_melody_motor_speed_mm_s": max(m["cruise_mm_s"] * LEAD_MOTOR_GAIN for m in moves),
        "maximum_strokes_per_note": max(stroke_counts),
        "x_range_mm": [min([X_MIN] + [m["end_x"] for m in moves]), max([X_MIN] + [m["end_x"] for m in moves])],
        "y_range_mm": [min([Y_MIN] + [m["end_y"] for m in moves]), max([Y_MIN] + [m["end_y"] for m in moves])],
        "z_mm": Z,
        "strokes": moves,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("midi", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile", choices=PROFILES, default="normal")
    parser.add_argument("--transpose", type=int, help="Defaults to -12 for normal, +12 for fast")
    parser.add_argument("--cadence-scale", type=float, default=1.0)
    args = parser.parse_args()
    if not math.isfinite(args.cadence_scale) or args.cadence_scale <= 0:
        parser.error("cadence-scale must be finite and positive")
    profile = PROFILES[args.profile]
    transpose = profile.default_transpose if args.transpose is None else args.transpose
    output = args.output or Path("childomine_u1_xy_fast.gcode" if args.profile == "fast" else "childomine_u1_xy.gcode")
    notes, source = read_notes(args.midi)
    gcode, full = render(notes, args.midi.name, transpose, args.cadence_scale, profile)
    # First seven source notes form a short, recognizable initial test.
    test_gcode, test = render(notes[:7], args.midi.name, transpose, args.cadence_scale, profile)
    test_path = output.with_name(output.stem + "_test.gcode")
    report_path = output.with_suffix(".json")
    report = {
        "source": source,
        "format": {
            "revision": 4,
            "identity_marker": "Snapmaker Orca 2.4.0",
            "actual_generator": "KlipperMIDI",
            "reference_file": "Silindir_PLA_2m5s.gcode",
            "filament_metadata": "PLA, density 1.24 g/cm3; zero usage; all temperature targets 0",
            "virtual_motion_segments": 1,
            "motion_mode": "xy_octaves",
            "motion_profile": profile.name,
            "screen_acceptance_hardware_tested": False,
        },
        "profile": {
            "printer": "Snapmaker U1 stock",
            "reference_commit": SOURCE_COMMIT,
            "configuration_source": f"{SOURCE_BASE}/lava/printer.cfg",
            "stepper_defaults_source": f"{SOURCE_BASE}/klippy/stepper.py",
            "corexy_source": f"{SOURCE_BASE}/klippy/kinematics/corexy.py",
            "state_restore_source": f"{SOURCE_BASE}/klippy/extras/gcode_move.py",
            "rotation_distance_mm": ROTATION_DISTANCE,
            "full_steps_per_rotation": FULL_STEPS_PER_ROTATION,
            "microsteps": MICROSTEPS,
            "firmware_step_pulses_per_mm": FULL_STEPS_PER_ROTATION * MICROSTEPS / ROTATION_DISTANCE,
            "acceleration_mm_s2": profile.acceleration,
            "max_toolhead_speed_mm_s": profile.max_toolhead_speed,
            "max_motor_speed_mm_s": profile.max_motor_speed,
            "assumed_minimum_cruise_ratio": CRUISE_RATIO,
        },
        "full": full,
        "test": test,
        "hardware_tested": False,
    }
    # Finish all planning before writing any deliverable.
    output.write_text(gcode, encoding="ascii")
    test_path.write_text(test_gcode, encoding="ascii")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "gcode": str(output.resolve()),
        "test": str(test_path.resolve()),
        "report": str(report_path.resolve()),
        "notes": len(notes),
        "melody_seconds": full["melody_duration_s"],
        "test_seconds": test["melody_duration_s"],
        "max_speed_mm_s": full["max_melody_speed_mm_s"],
    }, indent=2))


if __name__ == "__main__":
    main()
