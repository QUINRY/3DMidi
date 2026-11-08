"""Profile-specific startup and independent XY music checks for Klipper.

The offline reference planner assesses the emitted trajectory mathematically.
It does not establish equivalence with a manufacturer's modified firmware.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import TYPE_CHECKING

from convert_midi_u1 import frequency
from convert_poly_midi_u1 import simulate
from ke_startup import (KE_AUTO_STARTUP, KE_ID, is_ke_auto, restore_limits_command,
                        startup_commands as ke_startup_commands, startup_report as ke_startup_report)
from k2_startup import (K2_AUTO_STARTUP, is_k2_auto, startup_commands as k2_startup_commands,
                        startup_report as k2_startup_report)

if TYPE_CHECKING:
    from convert_poly_midi_u1 import PolyProfile

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_ALLOWED = {
    "TURN_OFF_HEATERS", "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE",
    "G90", "M220", "M204", "BED_MESH_CLEAR", "G1", "M400", "G4",
}
_STATE_NAME = "MIDI_STUDIO"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite(value, name: str) -> float:
    result = float(value)
    _require(math.isfinite(result), f"{name} must be finite")
    return result


def _settings(profile, printer: dict) -> dict:
    kinematics = getattr(profile, "kinematics", printer.get("kinematics", "corexy"))
    _require(kinematics in {"corexy", "cartesian"}, "Unsupported music kinematics")
    music_axes = profile.music_axes
    _require(music_axes in {"xy", "x"}, "Unsupported music axes")
    _require(printer.get("music_axes", music_axes) == music_axes, "Music axes differ from the printer profile")
    axis_priority = profile.axis_priority
    _require(axis_priority == printer.get("axis_priority", "balanced"), "Axis priority differs from printer profile")
    factory_speed = _finite(printer["max_velocity_mm_s"], "Factory speed")
    factory_accel = _finite(printer["max_accel_mm_s2"], "Factory acceleration")
    speed = min(_finite(profile.max_speed, "Profile speed"),
                _finite(printer.get("music_max_velocity_mm_s", factory_speed), "Music speed"),
                factory_speed)
    accel = _finite(profile.acceleration, "Music acceleration")
    accel_cap = min(factory_accel,
                    _finite(printer.get("music_max_accel_mm_s2", factory_accel), "Acceleration cap"))
    motor_cap = _finite(profile.max_motor_speed, "Motor speed")
    _require(factory_speed > 0 and factory_accel > 0 and speed > 0 and motor_cap > 0,
             "Nonpositive motion cap")
    _require(0 < accel <= accel_cap + 1e-9, "Music acceleration exceeds printer limits")
    start = tuple(_finite(v, "Start coordinate") for v in getattr(profile, "start_xy", (135.0, 135.0)))
    physical = getattr(profile, "physical_bounds", (
        printer["x"]["min"], printer["x"]["max"], printer["y"]["min"], printer["y"]["max"]))
    route = getattr(profile, "route_bounds", physical)
    physical = tuple(_finite(v, "Physical bound") for v in physical)
    route = tuple(_finite(v, "Route bound") for v in route)
    _require(len(start) == 2 and len(route) == len(physical) == 4, "Invalid XY bounds")
    _require(physical[0] < physical[1] and physical[2] < physical[3], "Invalid physical bounds")
    _require(physical[0] <= route[0] < route[1] <= physical[1]
             and physical[2] <= route[2] < route[3] <= physical[3], "Route exceeds physical bounds")
    _require(route[0] <= start[0] <= route[1] and route[2] <= start[1] <= route[3],
             "Start outside music route")
    cadence_x = _finite(profile.cadence_per_mm, "X motor cadence")
    cadence_y = _finite(getattr(profile, "cadence_y_per_mm", None) or cadence_x, "Y motor cadence")
    _require(cadence_x > 0 and cadence_y > 0, "Nonpositive motor cadence")
    _require(music_axes != "x" or axis_priority == "balanced", "X-only music cannot prioritize Y")
    _require(music_axes != "x" or kinematics != "corexy" or math.isclose(cadence_x, cadence_y),
             "X-only CoreXY melody requires equal motor cadences")
    _require(axis_priority in {"balanced", "y"} and (axis_priority != "y" or (
        kinematics == "corexy" and math.isclose(cadence_x, cadence_y))), "Unsupported axis priority")
    if profile.foc_bands:
        _require(printer.get("motor_control", {}).get("type") == "foc_step_servo"
                 and axis_priority == "balanced" and len(profile.foc_bands) == 2, "Unsupported FOC band profile")
        active_bands = profile.foc_bands[:1] if music_axes == "x" else profile.foc_bands
        _require(all(len(band) == 2 and 0 < band[0] < band[1] <= speed + 1e-6
                     for band in active_bands), "Invalid FOC speed bands")
    return {
        "kinematics": kinematics, "music_axes": music_axes, "axis_priority": axis_priority, "foc_bands": profile.foc_bands, "speed": speed, "accel": accel,
        "safe_accel": min(300.0, accel, factory_accel), "motor_cap": motor_cap,
        "setup_speed": min(30.0, factory_speed) if is_k2_auto(printer) else min(30.0, speed), "start": start,
        "physical": physical, "route": route, "cadence": (cadence_x, cadence_y),
        "mesh": bool(printer.get("has_bed_mesh", True)),
    }


def _comment(value) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").encode("ascii", "replace").decode("ascii")


def _automatic_startup(printer: dict, startup_mode: str) -> bool:
    _require(isinstance(startup_mode, str) and startup_mode in {"prepared_no_z", KE_AUTO_STARTUP, K2_AUTO_STARTUP},
             "Unsupported generic startup mode")
    _require(startup_mode != KE_AUTO_STARTUP or is_ke_auto(printer),
             "Automatic slow-Z startup is only supported by the KE source profile")
    _require(startup_mode != K2_AUTO_STARTUP or is_k2_auto(printer),
             "Automatic K2 XY startup requires a K2 source profile")
    return startup_mode != "prepared_no_z"


def _startup_commands(printer: dict) -> list[str]:
    return k2_startup_commands(printer) if is_k2_auto(printer) else ke_startup_commands(printer)


def _music_setup_commands(profile: PolyProfile, printer: dict) -> list[str]:
    """Use the KE's supported smoothing command only for its XY music block."""
    if printer.get("id") != KE_ID or profile.smoothing_accel < 0:
        return []
    smoothing = min(profile.smoothing_accel, profile.acceleration)
    normal = min(printer["max_accel_to_decel_mm_s2"], profile.acceleration)
    if math.isclose(smoothing, normal):
        return []
    _require(0 < smoothing <= profile.acceleration <= printer["max_accel_mm_s2"],
             "Music smoothing exceeds the KE acceleration limit")
    return [f"SET_VELOCITY_LIMIT ACCEL_TO_DECEL={smoothing:g}"]


def render_generic(source: str, frames: list[dict], instructions: list[dict],
                   duration: float, profile: PolyProfile, printer: dict, transpose: int,
                   startup_mode: str = "prepared_no_z") -> str:
    """Render XY music with prepared startup or a model-specific native home."""
    cfg = _settings(profile, printer)
    automatic = _automatic_startup(printer, startup_mode)
    ke_automatic = automatic and startup_mode == KE_AUTO_STARTUP
    k2_automatic = automatic and startup_mode == K2_AUTO_STARTUP
    music_setup = _music_setup_commands(profile, printer)
    duration = _finite(duration, "Music duration")
    _require(duration > 0, "Music duration must be positive")
    x, y = cfg["start"]
    setup_feed = cfg["setup_speed"] * 60.0
    xs = [x] + [item["x"] for item in instructions if item["kind"] == "move"]
    ys = [y] + [item["y"] for item in instructions if item["kind"] == "move"]
    lines = [
        "; MIDI Studio - Klipper XY music",
        f";TIME:{math.ceil(duration)}",
        "; Time is the music duration; positioning and the initial pause are additional.",
        ";LAYER_COUNT:1", "; One virtual motion layer; no material is printed.",
        f";MINX:{min(xs):.7f}", f";MAXX:{max(xs):.7f}",
        f";MINY:{min(ys):.7f}", f";MAXY:{max(ys):.7f}",
        ";Filament used:0.0m", ";Filament Weight:0.0",
        ";Print Temperature:0", ";Bed Temperature:0",
        f"; Printer: {_comment(printer.get('name', printer.get('id', 'Klipper')))}",
        f"; MIDI source: {_comment(source)}",
        ("; Directional FOC acoustic bands; no claim of measured pitch or preserved source intervals."
         if cfg['foc_bands'] else f"; Cartesian axis priority: {cfg['axis_priority']}; motor cadences are preserved."),
        f"; Duration_s: {duration:.6f}; onset_groups: {len(frames)}; transpose: {int(transpose)}",
        ("; FOC acoustic-band melody: X only; Y and Z fixed during music; source intervals compressed; audible pitch not measured."
         if cfg["foc_bands"] and cfg["music_axes"] == "x" else
         "; FOC acoustic-band melody: X/Y play in separate blocks; source pitch intervals are compressed; audible pitch is not measured."
         if cfg["foc_bands"] else "; Music: X-only melody; Y bed and Z remain fixed during the melody."
         if cfg["music_axes"] == "x" else "; Music: two XY motor voices."),
        ("; Automatic KE homing at normal machine limits; only the separate Z20 move uses F180."
         if ke_automatic else "; Automatic K2 XY homing: G28 X Y at normal machine limits before positioning."
         if k2_automatic else "; Prepared only: home and set safe Z clearance using the printer controls first."),
        ("; Stock homing has a separate FORCE_MOVE Z hop; full slow-hop control requires the supplied firmware helper."
         if ke_automatic else "; Empty bed required; native firmware retains its Z safety behavior during homing."
         if k2_automatic else "; No automatic clearance or homing is performed by this file."),
        ("; Stock probe/homing internals may temporarily heat; explicit file commands never heat or extrude."
         if ke_automatic else "; No explicit Z positioning is performed by this file."),
        "; Reference-planner assessment is not physical printer or vendor firmware validation.",
        "; EXECUTABLE_BLOCK_START",
        "TURN_OFF_HEATERS",
        f"SAVE_GCODE_STATE NAME={_STATE_NAME}",
        "G90", "M220 S100", f"M204 S{cfg['safe_accel']:.6f}",
    ]
    if cfg["mesh"]:
        lines.append("BED_MESH_CLEAR")
    if automatic:
        lines += _startup_commands(printer)
        # Use a separate positioning acceleration after native homing finishes.
        lines.append(f"M204 S{cfg['safe_accel']:.6f}")
    elif music_setup:
        lines += [restore_limits_command(printer), f"M204 S{cfg['safe_accel']:.6f}"]
    lines += [
        f"G1 X{x:.7f} Y{y:.7f} F{setup_feed:.6f}", "M400",
        f"M204 S{cfg['accel']:.6f}",
    ] + music_setup + [
        "G4 P1000", "; MELODY_BEGIN",
    ]
    previous_frame = None
    for item in instructions:
        if item["kind"] == "rest":
            lines.append(f"G4 P{_finite(item['duration'], 'Rest duration') * 1000.0:.6f}")
        else:
            _require(item["kind"] == "move", "Unknown musical instruction")
            if item["frame"] != previous_frame:
                lines.append(f"; EVENT {int(item['frame']):03d}")
                previous_frame = item["frame"]
            y_word = "" if cfg["music_axes"] == "x" else f"Y{_finite(item['y'], 'Y endpoint'):.7f} "
            lines.append(f"G1 X{_finite(item['x'], 'X endpoint'):.7f} " + y_word
                         + f"F{_finite(item['speed'], 'Move speed') * 60.0:.6f}")
    lines += [
        "; MELODY_END", "M400", f"M204 S{cfg['safe_accel']:.6f}",
        f"G1 X{x:.7f} Y{y:.7f} F{setup_feed:.6f}", "M400",
    ] + ([restore_limits_command(printer)] if automatic or music_setup else []) + [
        f"RESTORE_GCODE_STATE NAME={_STATE_NAME} MOVE=0",
        "TURN_OFF_HEATERS", "; EXECUTABLE_BLOCK_END",
    ]
    text = "\n".join(lines) + "\n"
    text.encode("ascii")
    return text


def _parameters(args: list[str], keys: set[str], line: int) -> dict[str, float]:
    values = {}
    for arg in args:
        _require(bool(re.fullmatch("[A-Z]" + _NUMBER, arg)), f"Malformed argument at line {line}")
        key = arg[0]
        _require(key in keys and key not in values, f"Unexpected/duplicate argument at line {line}")
        values[key] = _finite(arg[1:], f"Argument at line {line}")
    _require(set(values) == keys, f"Missing argument at line {line}")
    return values


def _expect(records: list[tuple], expected: list[tuple]) -> None:
    _require(len(records) == len(expected), "Incomplete or extra setup/cleanup commands")
    for (command, args, line), (wanted, values) in zip(records, expected):
        _require(command == wanted, f"Unexpected setup/cleanup command at line {line}")
        if isinstance(values, dict):
            actual = _parameters(args, set(values), line)
            _require(all(abs(actual[k] - v) <= 1e-6 for k, v in values.items()),
                     f"Changed setup/cleanup parameter at line {line}")
        else:
            _require(args == values, f"Unexpected setup/cleanup arguments at line {line}")


def validate_generic(text: str, instructions: list[dict], frames: list[dict],
                     duration: float, profile: PolyProfile, printer: dict, planner: dict,
                     startup_mode: str = "prepared_no_z") -> dict:
    """Parse the exported text independently and simulate its emitted music moves."""
    cfg = _settings(profile, printer)
    automatic = _automatic_startup(printer, startup_mode)
    ke_automatic = automatic and startup_mode == KE_AUTO_STARTUP
    k2_automatic = automatic and startup_mode == K2_AUTO_STARTUP
    music_setup = _music_setup_commands(profile, printer)
    duration = _finite(duration, "Music duration")
    _require(duration > 0, "Music duration must be positive")
    try:
        data = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("G-code must be ASCII") from exc
    before, after, music, events = [], [], [], []
    phase = "before"
    for line, raw in enumerate(text.splitlines(), 1):
        if raw == "; MELODY_BEGIN":
            _require(phase == "before", "Duplicate or misplaced melody start")
            phase = "music"
            continue
        if raw == "; MELODY_END":
            _require(phase == "music", "Duplicate or misplaced melody end")
            phase = "after"
            continue
        if raw.startswith("; EVENT "):
            match = re.fullmatch(r"; EVENT (\d+)", raw)
            _require(phase == "music" and match is not None, "Malformed or misplaced event marker")
            events.append(int(match[1]))
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        command, *args = code.split()
        allowed = (_ALLOWED | ({"G28"} if automatic else set())
                   | ({"SET_VELOCITY_LIMIT"} if automatic or music_setup else set()))
        _require(command in allowed, f"Disallowed command at line {line}: {command}")
        record = (command, args, line)
        if phase == "music":
            _require(command in {"G1", "G4"}, "Setup/flush command inside music")
            music.append(record)
        elif phase == "before":
            before.append(record)
        else:
            after.append(record)
    _require(phase == "after", "Missing melody markers")
    x, y = cfg["start"]
    setup = {"X": x, "Y": y, "F": cfg["setup_speed"] * 60.0}
    expected_before = [
        ("TURN_OFF_HEATERS", []), ("SAVE_GCODE_STATE", [f"NAME={_STATE_NAME}"]),
        ("G90", []), ("M220", {"S": 100.0}), ("M204", {"S": cfg["safe_accel"]}),
    ]
    if cfg["mesh"]:
        expected_before.append(("BED_MESH_CLEAR", []))
    if automatic:
        expected_before.extend((words[0], words[1:]) for words in
                               (command.split() for command in _startup_commands(printer)))
        expected_before.append(("M204", {"S": cfg["safe_accel"]}))
    elif music_setup:
        command, *args = restore_limits_command(printer).split()
        expected_before += [(command, args), ("M204", {"S": cfg["safe_accel"]})]
    expected_before += [
        ("G1", setup), ("M400", []), ("M204", {"S": cfg["accel"]}),
    ]
    expected_before.extend((words[0], words[1:]) for words in
                           (command.split() for command in music_setup))
    expected_before.append(("G4", {"P": 1000.0}))
    expected_after = [
        ("M400", []), ("M204", {"S": cfg["safe_accel"]}), ("G1", setup), ("M400", []),
    ]
    if automatic or music_setup:
        command, *args = restore_limits_command(printer).split()
        expected_after.append((command, args))
    expected_after += [
        ("RESTORE_GCODE_STATE", [f"NAME={_STATE_NAME}", "MOVE=0"]), ("TURN_OFF_HEATERS", []),
    ]
    _expect(before, expected_before)
    _expect(after, expected_after)
    _require(len(music) == len(instructions), "Extra or omitted musical movement/rest")
    frame_lookup = {frame["index"]: frame for frame in frames}
    _require(len(frame_lookup) == len(frames) and frames, "Missing or duplicate musical frames")
    expected_events = []
    for wanted in instructions:
        if wanted["kind"] == "move" and (not expected_events or expected_events[-1] != wanted["frame"]):
            expected_events.append(wanted["frame"])
    _require(events == expected_events == [frame["index"] for frame in frames],
             "Missing, duplicated, or reordered musical events")
    parsed, movements = [], []
    max_coordinate_error = max_feed_relative_error = 0.0
    max_rest_error = rest_total = 0.0
    position = cfg["start"]
    for (command, args, line), wanted in zip(music, instructions):
        if command == "G4":
            values = _parameters(args, {"P"}, line)
            wait = values["P"] / 1000.0
            _require(wanted["kind"] == "rest" and wait >= 0, "Unexpected or negative musical rest")
            expected = _finite(wanted["duration"], "Planned rest duration")
            error = abs(wait - expected)
            _require(error <= 1e-6, "Musical rest changed")
            max_rest_error = max(max_rest_error, error)
            rest_total += wait
            parsed.append({"kind": "rest", "duration": wait})
            continue
        _require(wanted["kind"] == "move", "Musical rest replaced by motion")
        values = _parameters(args, {"X", "F"} if cfg["music_axes"] == "x" else {"X", "Y", "F"}, line)
        speed = values["F"] / 60.0
        _require(0 < speed <= cfg["speed"] + 1e-6, "XY velocity exceeds printer/profile cap")
        end = (values["X"], values.get("Y", position[1]))
        # route_bounds is an inset used to seed the timing solver. The final
        # solved trajectory may expand into the enclosing safe physical bounds.
        bounds = cfg["physical"]
        _require(bounds[0] - 1e-7 <= end[0] <= bounds[1] + 1e-7
                 and bounds[2] - 1e-7 <= end[1] <= bounds[3] + 1e-7,
                 "XY movement exceeds printer/music bounds")
        errors = [abs(end[i] - _finite(wanted[a], "Planned endpoint")) for i, a in enumerate(("x", "y"))]
        max_coordinate_error = max(max_coordinate_error, *errors)
        _require(max(errors) <= 1e-6, "Emitted trajectory differs from plan")
        expected_speed = _finite(wanted["speed"], "Planned speed")
        _require(expected_speed > 0 and abs(speed - expected_speed) <= 1e-6, "Emitted feed differs from plan")
        max_feed_relative_error = max(max_feed_relative_error, abs(speed - expected_speed) / expected_speed)
        _require(math.hypot(end[0] - position[0], end[1] - position[1]) > 1e-8,
                 "Zero-length musical move")
        _require(wanted["frame"] in frame_lookup, "Move references an unknown frame")
        target = list(wanted["targets"])
        _require(len(target) == (1 if cfg["music_axes"] == "x" else 2)
                 and all(isinstance(n, int) and 0 <= n <= 127 for n in target),
                 "Invalid target notes")
        _require(sorted(target) == sorted(frame_lookup[wanted["frame"]]["target_pitches"]),
                 "Move targets differ from musical frame")
        item = {"kind": "move", "x": end[0], "y": end[1], "speed": speed}
        parsed.append(item)
        movements.append((item, wanted))
        position = end
    _require(movements, "No music moves")
    # Only independently parsed, rounded coordinates/feedrates enter the planner.
    actual = simulate(parsed, planner, profile)
    _require(len(actual) == len(movements), "Reference planner dropped a musical move")
    max_cents = max_frequency_relative = max_timing = max_timing_relative = 0.0
    continuous = 0
    x_speeds, y_speeds = [], []
    elapsed = rest_total
    for move, (emitted, wanted) in zip(actual, movements):
        _require(abs(move.cruise_v - emitted["speed"]) <= 1e-6,
                 "Short move cannot reach the intended musical cruise speed")
        _require(move.move_d > 0, "Reference planner produced an empty move")
        vx, vy = (move.axes_d[i] / move.move_d * move.cruise_v for i in (0, 1))
        x_speeds.append(abs(vx))
        y_speeds.append(abs(vy))
        if cfg["axis_priority"] == "y":
            _require(abs(vy) > abs(vx) * (1.0 + 1e-6), "Y-priority music must move Y faster than X")
        if cfg["music_axes"] == "x":
            _require(abs(vy) <= 1e-8, "Y moved during X-only music")
            # A pure X move drives both CoreXY motors at the same cadence.
            motor_speeds = (abs(vx), abs(vx)) if cfg["kinematics"] == "corexy" else (abs(vx),)
        elif cfg["kinematics"] == "corexy":
            motor_speeds = (abs(vx + vy), abs(vx - vy))
        else:
            motor_speeds = (abs(vx), abs(vy))
        _require(min(motor_speeds) > 0 and max(motor_speeds) <= cfg["motor_cap"] + 1e-5,
                 "Motor cadence speed exceeds profile limits or loses a voice")
        actual_hz = sorted(v * cadence for v, cadence in zip(motor_speeds, cfg["cadence"]))
        frame = frame_lookup[wanted["frame"]]
        if cfg["foc_bands"]:
            axis = frame.get("music_axis")
            _require(axis in {"x", "y"}, "FOC frame is missing its axis")
            active_v, idle_v = (abs(vx), abs(vy)) if axis == "x" else (abs(vy), abs(vx))
            low, high = cfg["foc_bands"][0 if axis == "x" else 1]
            _require(idle_v < 1e-7, "FOC acoustic axes must play separately")
            _require(low - 1e-6 <= active_v <= high + 1e-6, "FOC move left its acoustic speed band")
            _require(abs(active_v - frame["band_speed"]) < 1e-6, "FOC move differs from its mapped melodic speed")
        target_notes = wanted["targets"] * (2 if cfg["music_axes"] == "x" and cfg["kinematics"] == "corexy" else 1)
        target_hz = [] if cfg["foc_bands"] else sorted(frequency(note) for note in target_notes)
        for hz, target in zip(actual_hz, target_hz):
            relative = abs(hz - target) / target
            cents = abs(1200.0 * math.log2(hz / target))
            max_frequency_relative = max(max_frequency_relative, relative)
            max_cents = max(max_cents, cents)
            _require(cents <= 0.01, "Emitted motor frequencies differ from target notes")
        simulated_duration = move.accel_t + move.cruise_t + move.decel_t
        target_duration = _finite(wanted["duration"], "Planned move duration")
        _require(target_duration > 0, "Nonpositive planned move duration")
        error = abs(simulated_duration - target_duration)
        max_timing = max(max_timing, error)
        max_timing_relative = max(max_timing_relative, error / target_duration)
        _require(error <= 0.001, "Musical interval differs by more than 1 ms")
        elapsed += simulated_duration
        continuous += move.start_v > 0.001
    total_error = elapsed - duration
    _require(abs(total_error) <= 0.001, "Overall music duration differs by more than 1 ms")
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "printer_id": printer.get("id"), "startup_mode": startup_mode if automatic else "prepared_only",
        "music_axes": cfg["music_axes"], "music_voice_count": 1 if cfg["music_axes"] == "x" or cfg["foc_bands"] else 2,
        "startup": (k2_startup_report(printer) if k2_automatic else ke_startup_report(printer)
                    if ke_automatic else {"mode": "prepared_no_z"}),
        "source_onset_groups": len(frames), "simulated_moves": len(actual),
        "continuous_move_boundaries": continuous,
        "musical_rests": sum(item["kind"] == "rest" for item in parsed),
        "simulated_music_duration_s": elapsed, "total_timing_error_ms": total_error * 1000.0,
        "total_timing_relative_error": abs(total_error) / duration,
        "max_piece_timing_error_us": max_timing * 1e6,
        "max_piece_timing_relative_error": max_timing_relative,
        "max_rest_timing_error_us": max_rest_error * 1e6,
        "max_cadence_model_error_cents": None if cfg["foc_bands"] else max_cents,
        "max_frequency_relative_error": None if cfg["foc_bands"] else max_frequency_relative,
        "foc_acoustic_bands_mm_s": list(cfg["foc_bands"]),
        "audible_pitch_calibrated": False,
        "max_coordinate_error_mm": max_coordinate_error,
        "max_feed_relative_error": max_feed_relative_error,
        "xy_speed_range_mm_s": [min(m.cruise_v for m in actual), max(m.cruise_v for m in actual)],
        "axis_priority": cfg["axis_priority"],
        "x_speed_range_mm_s": [min(x_speeds), max(x_speeds)],
        "y_speed_range_mm_s": [min(y_speeds), max(y_speeds)],
        "minimum_y_to_x_speed_ratio": min(y / x for x, y in zip(x_speeds, y_speeds)) if cfg["axis_priority"] == "y" else None,
        "x_range_mm": [min(min(m.start_pos[0], m.end_pos[0]) for m in actual),
                       max(max(m.start_pos[0], m.end_pos[0]) for m in actual)],
        "y_range_mm": [min(min(m.start_pos[1], m.end_pos[1]) for m in actual),
                       max(max(m.start_pos[1], m.end_pos[1]) for m in actual)],
        "active_mesh_cleared_before_music": cfg["mesh"],
        "route_seed_bounds_mm": list(cfg["route"]),
        "validated_physical_bounds_mm": list(cfg["physical"]),
        "xy_acceleration_mm_s2": cfg["accel"], "motion_profile": profile.name,
        "music_setup_commands": music_setup,
        "normal_limits_restored_after_music": bool(automatic or music_setup),
        "z_isolation": {
            "startup_mode": startup_mode if automatic else "already_homed_and_clear",
            "explicit_z_moves": int(ke_automatic), "music_z_moves": 0,
            "xy_homing_commands": int(automatic), "full_xyz_homing_commands": int(ke_automatic),
            "startup_z_target_mm": 20 if ke_automatic else None,
            "explicit_startup_z_speed_mm_s": 3 if ke_automatic else None,
            "tool_change_commands": 0,
            "extrusion_commands": 0, "clearance_checked_by_file": False,
            "required_clearance_mm": None if k2_automatic else 20,
            "clearance_managed_by_firmware": k2_automatic,
            "firmware_macro_side_effects_verified": False,
        },
        "reference_planner_assessment": {
            "status": "passed", "scope": ("Emitted directional trajectory, acoustic speed bands, and timing in the pinned offline reference planner"
                                          if cfg["foc_bands"] else "Emitted XY trajectory, cadence, and timing in the pinned offline reference planner"),
            "vendor_firmware_equivalence": "not verified", "physical_printer_test": "not performed",
        },
        "no_heat_or_extrusion": ("explicit commands passed; stock homing internals not verified"
                                 if automatic else "passed"),
        "physical_printer_test": "not performed",
    }

