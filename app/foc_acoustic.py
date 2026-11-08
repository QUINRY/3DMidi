"""X-only FOC sound band based on the user's earlier K2 Pro scan.

This is an acoustic experiment, not an equal-tempered STEP-frequency model.
The melody uses X exclusively; earlier Y calibration remains historical data.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile

from convert_poly_midi_u1 import PolyProfile, plan, make_toolhead
from motion_export import render_generic, validate_generic
from k2_startup import (K2_AUTO_STARTUP, K2_IDS, STARTUP_NOTE, startup_commands,
                        startup_report, restore_limits_command)


MODE = "foc_band"
DEFAULT_BANDS = {"x": (12.0, 16.0), "y": (.125, .25)}
REFERENCE = {"printer": "Creality K2 Pro", "x_stages": ["A07", "A08"], "y_stages": ["Y01", "Y02", "Y03"],
             "source": "User confirmed Y01/Y02/Y03 (0.125/0.18/0.25 mm/s) audible in the new 48-second scan; X uses the earlier A07/A08 feedback.",
             "confirmed_y_band_mm_s": [.125, .25], "prior_y_reference_mm_s": [.25, .5],
             "current_hardware_retested": True, "audible_frequency_transfer_measured": False}
SPEED_FRACTIONS = {"slow": (0.0, .65), "medium": (0.0, 1.0), "fast": (.35, 1.0)}


def prepare(song, settings, printer, tempos):
    if not printer.get("foc_band_available") or printer["id"] not in K2_IDS:
        raise ValueError("Bu yazıcı için FOC ses aralığı modu mevcut değil.")
    speed, tempo = settings.get("speed", "slow"), settings.get("tempo", "slow")
    axis_mode = settings.get("foc_axis", "x")
    if (not all(isinstance(v, str) for v in (speed, tempo, axis_mode)) or speed not in SPEED_FRACTIONS
            or tempo not in tempos or axis_mode not in {"alternate", "x", "y"}):
        raise ValueError("Geçersiz FOC hız, tempo veya eksen seçimi.")
    # Upgrade valid X/Y settings from older tabs; K2 music now always uses X.
    axis_mode = "x"
    bands = {"y": DEFAULT_BANDS["y"]}
    normalized = {"printer": printer["id"], "speed": speed, "tempo": tempo, "voice": "foc_melody",
                  "startup": K2_AUTO_STARTUP, "sound_mode": MODE, "foc_axis": axis_mode}
    for axis in ("x",):
        try:
            low, high = (float(settings.get(f"foc_{axis}_{name}", DEFAULT_BANDS[axis][i])) for i, name in enumerate(("min", "max")))
        except (TypeError, ValueError) as exc:
            raise ValueError("Ses aralığı için sayısal mm/sn değerleri gerekli.") from exc
        cap = min(100, printer["music_max_velocity_mm_s"], printer["max_velocity_mm_s"])
        if not math.isfinite(low + high) or not .05 <= low < high <= cap:
            raise ValueError(f"{axis.upper()} ses aralığı 0,05–{cap:g} mm/sn içinde, alt değer üstten küçük olmalı.")
        bands[axis] = low, high
        normalized[f"foc_{axis}_min"], normalized[f"foc_{axis}_max"] = low, high
    ratio = tempos[tempo]["ratio"]
    groups = defaultdict(list)
    for note in song["notes"]:
        groups[note.start].append(note)
    # Ignore sub-audible inter-track staggering, retaining the highest active
    # melodic pitch. The amount of grouping is reported, never hidden.
    kept = []
    for start, group in sorted(groups.items()):
        if kept and start - kept[-1][0] < .04 * ratio:
            kept[-1][1].extend(group)
        else:
            kept.append((start, list(group)))
    origin = kept[0][0]
    duration = max(.04, (song["duration"] - origin) / ratio)
    frames, active = [], []
    for index, (start, group) in enumerate(kept):
        active = [n for n in active if n.end > start + 1e-7] + group
        lead = max(n.pitch for n in active)
        next_start = kept[index + 1][0] if index + 1 < len(kept) else origin + duration * ratio
        end = min(next_start, max(n.end for n in active))
        if next_start - end <= .230:
            end = next_start
        end = min(next_start, max(end, start + .04 * ratio))
        if index == len(kept) - 1:
            end = max(end, start + .04 * ratio)
        frames.append({"index": index, "start": (start - origin) / ratio,
                       "end": max((end - origin) / ratio, (start - origin) / ratio + .000001),
                       "source_lead": lead, "target_pitches": [lead], "music_axis": "x"})
    duration = max(duration, frames[-1]["end"])
    low_note, high_note = min(f["source_lead"] for f in frames), max(f["source_lead"] for f in frames)
    bottom, top = SPEED_FRACTIONS[speed]
    for frame in frames:
        fraction = (frame["source_lead"] - low_note) / max(1, high_note - low_note)
        fraction = bottom + (top - bottom) * fraction
        lo, hi = bands[frame["music_axis"]]
        frame["band_speed"] = lo * (hi / lo) ** fraction
    velocity = bands["x"][1]
    acceleration = min(printer["music_max_accel_mm_s2"], max(3000, math.ceil(3 * velocity / .04 / 100) * 100))
    bounds, route = printer["music_bounds"], printer["route_bounds"]
    profile = PolyProfile("foc_" + speed, acceleration, velocity, velocity, ratio, False,
                          cadence_per_mm=printer["x"]["fullsteps_per_mm"], cadence_y_per_mm=printer["y"]["fullsteps_per_mm"],
                          kinematics=printer["kinematics"], start_xy=tuple(printer["start_xy"]),
                          route_bounds=tuple(route["x"] + route["y"]), physical_bounds=tuple(bounds["x"] + bounds["y"]),
                          firmware_max_velocity=printer["max_velocity_mm_s"], square_corner_velocity=printer.get("square_corner_velocity_mm_s", 5),
                          smoothing_accel=printer.get("max_accel_to_decel_mm_s2", -1),
                          music_axes="x", foc_bands=(bands["x"], bands["y"]))
    printer = deepcopy(printer)
    printer.update(axis_priority="balanced", music_axes="x", startup=K2_AUTO_STARTUP, music_mode="foc_acoustic")
    axis_speeds = {axis: [min(values), max(values)] if (values := [f["band_speed"] for f in frames if f["music_axis"] == axis]) else [0, 0]
                   for axis in ("x", "y")}
    warnings = ["FOC ses aralığı: ana melodi yalnızca X ekseniyle çalar; müzikte Y ve Z sabittir. Melodi çizgisi hız aralığına sıkıştırılır; özgün perde aralıkları korunmaz.",
                f"Başlangıç referansı X {DEFAULT_BANDS['x'][0]:g}–{DEFAULT_BANDS['x'][1]:g} mm/sn: K2 Pro A07/A08 dinleme geri bildirimi. Gerçek ses frekansı ölçülmedi.",
                STARTUP_NOTE]
    merged = len(groups) - len(kept)
    if merged:
        warnings.append(f"{merged} çok yakın nota başlangıcı, en az 40 ms'lik motor aralıkları için birleştirildi.")
    return {"printer": printer, "profile": profile, "settings": normalized, "startup": K2_AUTO_STARTUP,
            "frames": frames, "duration": duration,
            "axis_speed_ranges": axis_speeds, "bands": bands, "warnings": warnings,
            "trimmed_leading_silence_s": origin, "merged_onsets": merged}


def summary(song, prepared):
    velocities = [f["band_speed"] for f in prepared["frames"]]
    return {"valid": True, "filename": song["filename"], "bytes": song["bytes"], "notes": len(song["notes"]), "tracks": song["tracks"],
            "bpm": song["bpm"], "output_bpm": round(song["bpm"] * prepared["profile"].tempo_ratio, 1), "tempo_changes": len(song["tempos"]),
            "source_duration": song["duration"], "duration": prepared["duration"], "settings": prepared["settings"], "printer": prepared["printer"],
            "sound_mode": MODE, "music_axes": "x", "axis_priority": "acoustic", "axis_speed_ranges": prepared["axis_speed_ranges"],
            "speed_range": [min(velocities), max(velocities)], "speed_cap": prepared["profile"].max_speed,
            "speed_caps": {key: prepared["profile"].max_speed for key in SPEED_FRACTIONS},
            "acceleration": prepared["profile"].acceleration, "transpose": 0, "warnings": prepared["warnings"],
            "frames": [{"start": f["start"], "end": f["end"], "pitches": [f["source_lead"]], "music_axis": f["music_axis"]} for f in prepared["frames"]]}


def convert(song, prepared, planner, stem):
    result = summary(song, prepared)
    profile, frames, duration = prepared["profile"], prepared["frames"], prepared["duration"]
    cut = next((f["start"] for f in frames if f["start"] >= 8), duration)
    report = {"app": "MIDI Studio - FOC acoustic bands", "backend": MODE, "source": {key: song[key] for key in ("filename", "sha256", "duration", "bpm")},
              "library_source": song.get("library_source"), "printer": prepared["printer"], "settings": prepared["settings"], "profile": asdict(profile),
              "acoustic_reference": REFERENCE, "audible_pitch_calibrated": False, "physical_printer_tested": False,
              "required_clearance_mm": None, "clearance_managed_by_firmware": True,
              "trimmed_leading_silence_s": prepared["trimmed_leading_silence_s"], "merged_onsets": prepared["merged_onsets"],
              "tempo_map_scaled_by": profile.tempo_ratio, "warnings": prepared["warnings"], "validation": {}}
    stem_parts = stem.rsplit("_", 2)
    name_stem = stem_parts[0] + "_FOC" + ("Y" if prepared["settings"]["foc_axis"] == "y" else "X" if prepared["settings"]["foc_axis"] == "x" else "XY") + "_" + "_".join(stem_parts[1:])
    result["downloads"] = {}
    with tempfile.TemporaryDirectory(prefix="midi-foc-band-") as directory:
        for kind, selected, seconds in (("full", frames, duration), ("test", [f for f in frames if f["start"] < cut], cut)):
            instructions, _ = plan(selected, seconds, planner, profile)
            expanded = []
            for instruction in instructions:
                if instruction["kind"] == "rest":
                    remaining = instruction["duration"]
                    while remaining > 10:
                        expanded.append({"kind": "rest", "duration": 10})
                        remaining -= 10
                    if remaining > 1e-9:
                        expanded.append({"kind": "rest", "duration": remaining})
                else:
                    expanded.append(instruction)
            text = render_generic(song["filename"], selected, expanded, seconds, profile, prepared["printer"], 0,
                                  startup_mode=prepared["startup"])
            provenance = {"printer_source": prepared["printer"].get("source"), "library_source": song.get("library_source"), "acoustic_reference": REFERENCE}
            text = "; Sources and calibration: " + json.dumps(provenance, ensure_ascii=True) + "\n" + text
            checked = validate_generic(text, expanded, selected, seconds, profile, prepared["printer"], planner,
                                       startup_mode=prepared["startup"])
            name = name_stem + ("_test" if kind == "test" else "") + ".gcode"
            checked["file"] = name
            checked["z_isolation"]["file"] = name
            result["downloads"][kind] = {"name": name, "text": text, "seconds": seconds, "bytes": len(text.encode("ascii"))}
            report["validation"][kind] = checked
            if kind == "full":
                result["path"] = [[i["x"], i["y"]] for i in expanded if i["kind"] == "move"]
    result["downloads"]["report"] = {"name": name_stem + "_kontrol.json", "text": json.dumps(report, ensure_ascii=False, indent=2)}
    result["checks"] = {"xy_only": True, "music_xy_only": True, "music_axes": "x", "music_voice_count": 1,
                        "heating": False, "extrusion": False, "planner": True, "planner_kind": "foc_band_reference",
                        "physical_printer_tested": False, "audible_pitch_calibrated": False}
    return result


def make_y_scan(printer, planner):
    """A labelled listening experiment after native XY homing, without explicit Z."""
    if not printer.get("foc_band_available") or printer["id"] not in K2_IDS:
        raise ValueError("Bu model için FOC taraması yok.")
    x, y = printer["start_xy"]
    acceleration, seconds = 600.0, 1.5
    stages, body, elapsed = [], ["M117 S00 baseline", "G4 P2000"], 2.0
    requested = [("X01", "x", 12.0), ("X02", "x", 16.0)]
    requested += [(f"Y{i:02}", "y", speed) for i, speed in enumerate((.125, .18, .25, .35, .5, .7, 1.0, 2.0, 4.0), 1)]
    for code, axis, speed in requested:
        distance = speed * (seconds - speed / acceleration)
        ex, ey = (x + distance, y) if axis == "x" else (x, y + distance)
        stages.append({"code": code, "axis": axis, "speed_mm_s": speed, "start_s": elapsed, "end_s": elapsed + 4})
        body += [f"; STAGE {code} axis={axis} speed_mm_s={speed:g}", f"M117 {code} {axis.upper()} {speed:g}mm/s",
                 f"G1 X{ex:.9f} Y{ey:.9f} F{speed * 60:.7f}", "M400",
                 f"G1 X{x:.9f} Y{y:.9f} F{speed * 60:.7f}", "M400", "G4 P1000"]
        elapsed += 4
    body += ["M117 S99 baseline", "G4 P2000", "M400"]
    elapsed += 2
    text = "\n".join(["; MIDI Studio - K2 FOC directional listening scan", f";TIME:{math.ceil(elapsed)}", ";LAYER_COUNT:1",
                      "; Automatic G28 X Y at normal machine limits. Empty bed; native firmware Z safety behavior applies.",
                      "; No explicit Z, heating or extrusion commands; no Z target is set by this file.",
                      "; Stage times begin at S00; homing and initial centre positioning are additional.",
                      "TURN_OFF_HEATERS", "SAVE_GCODE_STATE NAME=FOC_SCAN", "G90", "M220 S100", "M204 S300", "BED_MESH_CLEAR",
                      *startup_commands(printer), "M204 S300",
                      f"G1 X{x:.9f} Y{y:.9f} F1800", "M400", "M204 S600", "G4 P1000", "; SOUND_SCAN_BEGIN",
                      *body, "; SOUND_SCAN_END", "M204 S300", f"G1 X{x:.9f} Y{y:.9f} F1800", "M400",
                      "M117 FOC scan finished", restore_limits_command(printer),
                      "RESTORE_GCODE_STATE NAME=FOC_SCAN MOVE=0", "TURN_OFF_HEATERS", ""])
    checked = validate_y_scan(text, stages, printer, planner)
    prefix = "".join(c for c in printer["name"] if c.isascii() and c.isalnum())
    return {"name": prefix + "_Y_Ses_Tarama.gcode", "text": text, "stages": stages, "validation": checked}


def validate_y_scan(text, stages, printer, planner):
    allowed = {"TURN_OFF_HEATERS", "SAVE_GCODE_STATE", "RESTORE_GCODE_STATE", "G90", "M220", "M204", "BED_MESH_CLEAR", "G1", "M400", "G4", "M117", "G28", "SET_VELOCITY_LIMIT"}
    if "Z_HOP" in text:
        raise ValueError("Unexpected homing override")
    for raw in text.splitlines():
        code = raw.split(";", 1)[0].strip()
        if not code:
            continue
        command, *args = code.split()
        if command not in allowed:
            raise ValueError("Unexpected scan command")
        if command == "G1" and {word[0] for word in args} != {"X", "Y", "F"}:
            raise ValueError("Scan contains Z/extrusion or malformed motion")
        if command == "G1":
            values = {word[0]: float(word[1:]) for word in args}
            if (not 0 < values["F"] <= 1800 or not all(math.isfinite(value) for value in values.values())
                    or any(not printer["music_bounds"][axis][0] <= values[axis.upper()] <= printer["music_bounds"][axis][1] for axis in ("x", "y"))):
                raise ValueError("Scan positioning exceeds limits")
        if command == "RESTORE_GCODE_STATE" and args != ["NAME=FOC_SCAN", "MOVE=0"]:
            raise ValueError("Scan restore must not move")
    before, rest = text.split("; SOUND_SCAN_BEGIN\n", 1)
    body, after = rest.split("; SOUND_SCAN_END", 1)
    def codes(block):
        return [code for raw in block.splitlines() if (code := raw.split(";", 1)[0].strip())]
    x, y = printer["start_xy"]
    expected_before = ["TURN_OFF_HEATERS", "SAVE_GCODE_STATE NAME=FOC_SCAN", "G90", "M220 S100", "M204 S300", "BED_MESH_CLEAR",
                       *startup_commands(printer), "M204 S300", f"G1 X{x:.9f} Y{y:.9f} F1800", "M400", "M204 S600", "G4 P1000"]
    expected_after = ["M204 S300", f"G1 X{x:.9f} Y{y:.9f} F1800", "M400", "M117 FOC scan finished",
                      restore_limits_command(printer), "RESTORE_GCODE_STATE NAME=FOC_SCAN MOVE=0", "TURN_OFF_HEATERS"]
    if codes(before) != expected_before or codes(after) != expected_after:
        raise ValueError("Changed scan homing/setup/cleanup sequence")
    profile = PolyProfile("foc_listening_scan", 600, 16, 16, 1, False,
                          firmware_max_velocity=printer["max_velocity_mm_s"], square_corner_velocity=printer.get("square_corner_velocity_mm_s", 5))
    samples = []
    toolhead = make_toolhead(samples.extend, profile)
    queue = planner["LookAheadQueue"](toolhead)
    position = [*printer["start_xy"], 20.0, 0.0]
    active = None
    counts = {stage["code"]: 0 for stage in stages}
    lookup = {stage["code"]: stage for stage in stages}
    elapsed, bounds = 0.0, [list(printer["start_xy"]), list(printer["start_xy"])]
    for line in body.splitlines():
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        command, *args = code.split()
        if command == "M117":
            active = lookup.get(args[0])
        elif command == "G1":
            if active is None:
                raise ValueError("Unlabelled scan move")
            values = {a[0]: float(a[1:]) for a in args}
            end = [values["X"], values["Y"], 20.0, 0.0]
            dx, dy = end[0] - position[0], end[1] - position[1]
            if (active["axis"] == "x" and (abs(dy) > 1e-8 or abs(dx) < 1e-8)) or (active["axis"] == "y" and (abs(dx) > 1e-8 or abs(dy) < 1e-8)):
                raise ValueError("Scan did not isolate its labelled axis")
            if abs(values["F"] / 60 - active["speed_mm_s"]) > 1e-7:
                raise ValueError("Scan feed differs from its labelled speed")
            if any(not printer["music_bounds"][axis][0] <= end[i] <= printer["music_bounds"][axis][1] for i, axis in enumerate(("x", "y"))):
                raise ValueError("Scan left the printer's inset bounds")
            move = planner["Move"](toolhead, position, end, values["F"] / 60)
            queue.add_move(move)
            queue.flush()
            if abs(move.cruise_v - active["speed_mm_s"]) > 1e-6 or abs(move.accel_t + move.cruise_t + move.decel_t - 1.5) > 1e-6:
                raise ValueError("Scan cannot reach its labelled speed/duration")
            elapsed += move.accel_t + move.cruise_t + move.decel_t
            counts[active["code"]] += 1
            position = end
            for i in (0, 1):
                bounds[0][i] = min(bounds[0][i], end[i])
                bounds[1][i] = max(bounds[1][i], end[i])
        elif command == "G4":
            delay = float(args[0][1:]) / 1000
            if not 0 <= delay <= 2:
                raise ValueError("Unexpected scan dwell")
            elapsed += delay
        elif command != "M400":
            raise ValueError("Setup or homing command inside scan music")
    if any(count != 2 for count in counts.values()) or position[:2] != printer["start_xy"]:
        raise ValueError("Incomplete scan")
    return {"stages": len(stages), "moves": len(samples), "duration_s": elapsed, "xy_bounds_mm": bounds,
            "explicit_z_moves": 0, "heating_or_extrusion": False, "home_commands": 1,
            "startup": startup_report(printer),
            "offline_motion_check": "passed", "physical_sound_observed": False}
