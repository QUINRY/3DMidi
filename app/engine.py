"""Local, profile-aware Klipper MIDI conversion."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import mido

from resources import ROOT, ASSETS
sys.path.insert(0, str(ROOT / "tools"))
from convert_midi_u1 import Note
from convert_poly_midi_u1 import PolyProfile, arrange, plan, render, frame_vector, piece_distance
from validate_u1_gcode import load_planner
from validate_poly_u1 import validate
from printers import get_profile
from motion_export import render_generic, validate_generic
from k2_startup import K2_AUTO_STARTUP, K2_IDS, STARTUP_NOTE as K2_STARTUP_NOTE
from bambu_native import prepare_native, summary_native, convert_native
from foc_acoustic import prepare as prepare_foc, summary as summary_foc, convert as convert_foc

PLANNER = load_planner(ASSETS / "u1_toolhead.py")
SPEEDS = {
    "slow": {"label": "Yavaş", "transpose": -12, "accel": 3000, "max_speed": 100, "max_motor": 120},
    "medium": {"label": "Orta", "transpose": 0, "accel": 7000, "max_speed": 180, "max_motor": 240},
    "fast": {"label": "Hızlı", "transpose": 12, "accel": 12000, "max_speed": 360, "max_motor": 480},
}
TEMPOS = {"slow": {"label": "Yavaş", "ratio": .75}, "medium": {"label": "Orta", "ratio": 1.0},
          "fast": {"label": "Hızlı", "ratio": 1.25}}
FILENAME_LABELS = {"slow": "Yavas", "medium": "Orta", "fast": "Hizli"}


def export_stem(filename: str, settings: dict, printer: dict | None = None) -> str:
    midi_name = Path(filename).stem.translate(str.maketrans({"ı": "i", "İ": "I"}))
    midi_name = unicodedata.normalize("NFKD", midi_name).encode("ascii", "ignore").decode("ascii")
    midi_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", midi_name).strip("_-")[:70] or "melodi"
    printer = printer if printer is not None else get_profile(settings.get("printer", "snapmaker_u1"))
    prefix = re.sub(r"[^a-zA-Z0-9]+", "", unicodedata.normalize("NFKD", printer["name"]).encode("ascii", "ignore").decode())[:60] or "Klipper"
    speed_labels = ({"slow": "Kalin", "medium": "Orijinal", "fast": "Ince"}
                    if printer.get("music_mode") == "bambu_native" else FILENAME_LABELS)
    return f"{prefix}_{midi_name}_{FILENAME_LABELS[settings['tempo']]}_{speed_labels[settings['speed']]}"


class InputError(ValueError):
    pass


def read_midi(data: bytes, filename: str) -> dict:
    if not data.startswith(b"MThd"):
        raise InputError("Bu dosya bir MIDI dosyası değil. .mid veya .midi dosyası seç.")
    try:
        midi = mido.MidiFile(file=io.BytesIO(data))
        if midi.type == 2 or midi.ticks_per_beat <= 0:
            raise InputError("Bağımsız zaman çizelgeli MIDI Type 2 bu taslakta desteklenmiyor.")
        now, opened, held, pedal, notes, tempos = 0.0, defaultdict(deque), defaultdict(list), {}, [], []
        percussion, bends, events = 0, False, 0
        def finish(started, end):
            start, pitch, velocity, channel = started
            if end > start + 1e-6:
                notes.append(Note(round(start, 9), round(end, 9), pitch, velocity, channel))
        for message in midi:
            events += 1
            now += message.time
            if events > 100000 or now > 600:
                raise InputError("Taslak en fazla 10 dakikalık MIDI dosyalarını işler. Daha kısa bir bölüm seç.")
            if message.type == "set_tempo":
                tempos.append({"time": now, "bpm": round(mido.tempo2bpm(message.tempo), 2)})
            channel = getattr(message, "channel", None)
            if channel == 9:
                percussion += message.type == "note_on" and message.velocity > 0
                continue
            if message.type == "note_on" and message.velocity:
                opened[channel, message.note].append((now, message.note, message.velocity, channel))
            elif message.type in {"note_off", "note_on"}:
                queue = opened[channel, message.note]
                if queue:
                    started = queue.popleft()
                    if pedal.get(channel, False):
                        held[channel].append(started)
                    else:
                        finish(started, now)
            elif message.type == "control_change" and message.control == 64:
                pedal[channel] = message.value >= 64
                if not pedal[channel]:
                    for started in held.pop(channel, []):
                        finish(started, now)
            elif message.type == "pitchwheel" and message.pitch:
                bends = True
        for queue in opened.values():
            for started in queue:
                finish(started, now)
        for group in held.values():
            for started in group:
                finish(started, now)
    except InputError:
        raise
    except Exception as exc:
        raise InputError("MIDI okunamadı. Dosyayı bir MIDI düzenleyicisinden yeniden dışa aktarmayı dene.") from exc
    notes.sort(key=lambda n: (n.start, n.pitch))
    if not notes:
        raise InputError("Bu MIDI'de çalınabilir nota bulunamadı. Yalnızca vurmalı ses içeren dosyalar desteklenmiyor.")
    if len(notes) > 12000:
        raise InputError("Bu MIDI taslak için çok yoğun. Daha kısa bir bölüm seç.")
    duration = max(now, max(n.end for n in notes))
    return {"filename": filename, "notes": notes, "duration": duration, "bpm": tempos[0]["bpm"] if tempos else 120,
            "tempos": tempos, "tracks": len(midi.tracks), "percussion": percussion, "bends": bends,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def prepare(song: dict, settings: dict, *, printer: dict | None = None) -> dict:
    voice = settings.get("voice", "duet")
    try:
        printer = (deepcopy(printer) if printer is not None
                   else get_profile(settings.get("printer", "snapmaker_u1")))
        if printer["id"] != settings.get("printer", "snapmaker_u1"):
            raise ValueError("Yazıcı profili seçimle eşleşmiyor.")
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    speed_key = settings.get("speed", printer.get("default_speed", "medium"))
    tempo_key = settings.get("tempo", printer.get("default_tempo", "medium"))
    if printer.get("music_mode") == "bambu_native":
        try:
            return prepare_native(song, settings, printer)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
    sound_mode = settings.get("sound_mode", "step_cadence")
    if not isinstance(sound_mode, str) or sound_mode not in {"step_cadence", "foc_band"}:
        raise InputError("Geçersiz ses üretim modu.")
    if sound_mode == "foc_band":
        try:
            return prepare_foc(song, settings, printer, TEMPOS)
        except ValueError as exc:
            raise InputError(str(exc)) from exc
    allowed_voices = {"duet", "melody"}
    if printer.get("music_axes") == "x":
        if not isinstance(voice, str) or voice not in {"duet", "melody", "x_melody"}:
            raise InputError("Geçersiz melodi ayarı.")
        voice, allowed_voices = "x_melody", {"x_melody"}
        speed_key = settings.get("speed", printer.get("default_speed", "fast"))
    if printer["id"] == "snapmaker_u1":
        if printer.get("tempo_follows_speed"):
            tempo_key = settings.get("tempo", speed_key)
        startup = settings.get("startup", "xy_home")
        allowed_startups = {"xy_home", "prepared_no_z"}
    elif printer["id"] == "creality_ender3_v3_ke":
        startup = settings.get("startup", "ke_auto_home_slow_z")
        allowed_startups = {"ke_auto_home_slow_z", "prepared_no_z"}
        if startup in ("xy_home", "xy_home_zero_hop"):
            startup = "ke_auto_home_slow_z"
    elif printer["id"] in K2_IDS:
        # Also upgrade settings sent by browser tabs opened before automatic K2 homing.
        startup, allowed_startups = K2_AUTO_STARTUP, {K2_AUTO_STARTUP}
    else:
        startup, allowed_startups = "prepared_no_z", {"prepared_no_z"}
    if startup == "xy_home_zero_hop":
        startup = "xy_home"  # Compatibility for an already-open older browser tab.
    if (not all(isinstance(value, str) for value in (speed_key, tempo_key, voice, startup))
            or speed_key not in SPEEDS or tempo_key not in TEMPOS or voice not in allowed_voices
            or startup not in allowed_startups):
        raise InputError("Geçersiz ayar. Sayfayı yenileyip yeniden dene.")
    locked_settings = printer.get("music_settings_lock", {})
    if locked_settings:
        speed_key, tempo_key = locked_settings["speed"], locked_settings["tempo"]
    printer["startup"] = startup
    speed, tempo = SPEEDS[speed_key], TEMPOS[tempo_key]
    caps = {key: min(value["max_speed"], printer["music_max_velocity_mm_s"]) for key, value in SPEEDS.items()}
    bounds, route = printer["music_bounds"], printer["route_bounds"]
    accel_cap = printer["music_max_accel_mm_s2"]
    profile = PolyProfile(
        speed_key, min(speed["accel"], accel_cap), caps[speed_key], speed["max_motor"], tempo["ratio"], True,
        cadence_per_mm=printer["x"]["fullsteps_per_mm"], cadence_y_per_mm=printer["y"]["fullsteps_per_mm"],
        kinematics=printer["kinematics"], start_xy=tuple(printer["start_xy"]),
        route_bounds=tuple(route["x"]+route["y"]), physical_bounds=tuple(bounds["x"]+bounds["y"]),
        firmware_max_velocity=printer["max_velocity_mm_s"],
        square_corner_velocity=printer.get("square_corner_velocity_mm_s", 5),
        cruise_ratio=printer.get("minimum_cruise_ratio", .5),
        smoothing_accel=printer.get("max_accel_to_decel_mm_s2", -1) if printer["id"] != "snapmaker_u1" else -1,
        event_ramp_factor=2.0 if printer["id"] == "creality_ender3_v3_ke" else 3.0,
        music_axes=printer.get("music_axes", "xy"), axis_priority=printer.get("axis_priority", "balanced"))
    groups = defaultdict(list)
    for note in song["notes"]:
        groups[note.start].append(note)
    onsets, active, original_score = sorted(groups), [], []
    for index, start in enumerate(onsets):
        active = [n for n in active if n.end > start + 1e-7] + groups[start]
        by_pitch = {n.pitch: n for n in sorted(active, key=lambda n: n.end)}
        chosen = [by_pitch[max(by_pitch)]] if voice in {"melody", "x_melody"} else list(by_pitch.values())
        next_start = onsets[index + 1] if index + 1 < len(onsets) else song["duration"]
        end = min(next_start, max(n.end for n in chosen))
        original_score.extend(replace(n, start=start, end=end) for n in chosen)
        if len(original_score) > 60000 or len(onsets) > 6000:
            raise InputError("Bu MIDI çok fazla eşzamanlı nota içeriyor. Daha kısa bir bölüm seç.")
    # Keep intervals intact: fit the X-only melody by semitones, and the
    # existing two-motor arrangements by octaves. Never clip individual notes.
    fitted = False
    for extra_down in range(0, 73, 1 if profile.music_axes == "x" else 12):
        transpose = speed["transpose"] - extra_down
        score = [replace(n, pitch=n.pitch + transpose) for n in original_score]
        if min(n.pitch for n in score) < 0:
            break
        if max(n.pitch for n in score) > 127:
            continue
        try:
            frames, arrangement = arrange(score, song["duration"], profile)
            speeds = [math.hypot(*frame_vector(f["target_pitches"], profile)[:2]) for f in frames]
            required = profile.acceleration
            for frame, velocity in zip(frames, speeds):
                interval = frame["end"] - frame["start"]
                count = max(1, math.ceil(velocity * interval / piece_distance(profile)))
                required = max(required, profile.event_ramp_factor * velocity * count / interval)
            if required > accel_cap + 1e-6:
                continue
            required = min(accel_cap, math.ceil(required / 100) * 100)
            profile = replace(profile, acceleration=required,
                              smoothing_accel=required if printer["id"] == "creality_ender3_v3_ke" else profile.smoothing_accel)
            fitted = True
            break
        except ValueError:
            continue
    if not fitted:
        raise InputError("Bu MIDI bu yazıcının hız/ivme sınırlarına sığmıyor. Daha yavaş tempo veya daha dar nota aralığı seç.")
    warnings = []
    if locked_settings:
        warnings.append("FOC step-servo profili: hareket hızı Yavaş, tempo Yavaş (%75) olarak sabit.")
    if extra_down:
        shift_label = f"{extra_down // 12} ek oktav" if extra_down % 12 == 0 else f"{extra_down} yarım ses"
        warnings.append(f"Yazıcı sınırlarına uyması için eserin tamamı {shift_label} aşağı alındı; toplam perde değişimi {transpose:+d} yarım ses.")
    if profile.music_axes == "x":
        warnings.append("Müzikte yalnızca X ekseni ana melodiyi çalar; Y ve Z sabit kalır. Hız, nota aralıkları korunarak hesaplanır.")
    if profile.axis_priority == "y":
        warnings.append("Her müzik hareketinde Y, X'ten hızlı ilerler; CoreXY motor notaları ve nota süreleri korunur. Hız ve tempo ayrı ayarlanabilir.")
    if caps[speed_key] < speed["max_speed"]:
        warnings.append(f"Hız üst sınırı bu yazıcı için {caps[speed_key]:g} mm/sn ile sınırlandı.")
    if startup == "ke_auto_home_slow_z":
        warnings.append("Home normal yazıcı limitlerinde yapılır; yalnızca sonraki Z20 mm yükseltmesi 3 mm/sn'dir. Dosya sonunda normal limitler geri yüklenir; müzik sırasında Z sabit kalır.")
        warnings.append("Stok homing içindeki sabit hızlı Z kaldırmasını da yavaşlatmak için yavaş Z ayar dosyası bir kez kurulmalıdır; firmware'in iç homing hareketleri fiziksel olarak test edilmedi.")
    elif startup == K2_AUTO_STARTUP:
        warnings.append(K2_STARTUP_NOTE)
    elif printer["id"] != "snapmaker_u1":
        warnings.append("Önceden home edilmiş, motorları etkin ve en az 20 mm nozul–tabla boşluğu olan yazıcı gerekir; çıktı home veya Z hareketi içermez.")
    if song["percussion"]:
        warnings.append(f"{song['percussion']} vurmalı nota melodiden ayrıldı.")
    if song["bends"]:
        warnings.append("Perde bükmeleri sabit notalara indirgenir.")
    if voice == "melody":
        warnings.append("Ana melodi ikinci motorda bir alt oktavla desteklenir.")
    if arrangement["omitted_inner_notes"] and profile.music_axes != "x":
        warnings.append("Çok sesli bölümler iki motor sesine düzenlendi.")
    axis_speeds = None
    if profile.axis_priority == "y" or profile.music_axes == "x":
        vectors = [frame_vector(f["target_pitches"], profile) for f in frames]
        axis_speeds = {axis: [min(abs(v[index]) for v in vectors), max(abs(v[index]) for v in vectors)]
                       for index, axis in enumerate(("x", "y"))}
    return {"profile": profile, "printer": printer, "score": score, "frames": frames, "arrangement": arrangement,
            "duration": song["duration"] / tempo["ratio"], "startup": startup, "speed_caps": caps,
            "settings": {"printer": printer["id"], "speed": speed_key, "tempo": tempo_key, "voice": voice, "startup": startup},
            "transpose": transpose, "speed_range": [min(speeds), max(speeds)],
            "axis_speed_ranges": axis_speeds, "warnings": warnings}


def summary(song: dict, prepared: dict) -> dict:
    if prepared["settings"].get("sound_mode") == "foc_band":
        return summary_foc(song, prepared)
    if prepared["printer"].get("music_mode") == "bambu_native":
        return summary_native(song, prepared)
    return {"valid": True, "filename": song["filename"], "bytes": song["bytes"], "notes": len(song["notes"]), "tracks": song["tracks"],
            "source_duration": song["duration"], "duration": prepared["duration"], "bpm": song["bpm"],
            "output_bpm": round(song["bpm"] * prepared["profile"].tempo_ratio, 1), "tempo_changes": len(song["tempos"]),
            "frames": [{"start": f["start"], "end": f["end"], "pitches": f["target_pitches"]} for f in prepared["frames"]],
            "speed_range": prepared["speed_range"], "speed_cap": prepared["profile"].max_speed,
            "acceleration": prepared["profile"].acceleration, "transpose": prepared["transpose"],
            "settings": prepared["settings"], "warnings": prepared["warnings"],
            "music_axes": prepared["profile"].music_axes,
            "axis_priority": prepared["profile"].axis_priority, "axis_speed_ranges": prepared["axis_speed_ranges"],
            "printer": prepared["printer"], "speed_caps": prepared["speed_caps"]}


def source_summary(song: dict) -> dict:
    return {"valid": False, "filename": song["filename"], "bytes": song["bytes"], "notes": len(song["notes"]),
            "tracks": song["tracks"], "source_duration": song["duration"], "duration": song["duration"],
            "bpm": song["bpm"], "output_bpm": song["bpm"], "tempo_changes": len(song["tempos"]),
            "frames": [], "speed_range": [], "warnings": []}


def convert(song: dict, settings: dict, *, printer: dict | None = None) -> dict:
    prepared = prepare(song, settings, printer=printer)
    if prepared["settings"].get("sound_mode") == "foc_band":
        try:
            return convert_foc(song, prepared, PLANNER, export_stem(song["filename"], prepared["settings"], prepared["printer"]))
        except ValueError as exc:
            raise InputError("FOC ses aralığı için hareket planı oluşturulamadı. Tempo veya ses aralığını daraltıp yeniden dene.") from exc
    if prepared["printer"].get("music_mode") == "bambu_native":
        try:
            return convert_native(song, prepared, export_stem(song["filename"], prepared["settings"], prepared["printer"]))
        except ValueError as exc:
            raise InputError(str(exc)) from exc
    profile, frames, duration = prepared["profile"], prepared["frames"], prepared["duration"]
    cut = next((f["start"] for f in frames if f["start"] >= 8), duration)
    sections = [("full", frames, duration), ("test", [f for f in frames if f["start"] < cut], cut)]
    result = summary(song, prepared)
    result["downloads"] = {}
    filename_stem = export_stem(song["filename"], prepared["settings"], prepared["printer"])
    report = {"app": "MIDI Studio 0.5", "backend": "klipper_xy", "source": {k: song[k] for k in ("filename", "sha256", "duration", "tracks", "bpm")},
              "settings": prepared["settings"], "profile": asdict(profile), "global_transpose_semitones": prepared["transpose"],
              "printer": prepared["printer"], "library_source": song.get("library_source"),
              "required_clearance_mm": None if prepared["startup"] == K2_AUTO_STARTUP else 20,
              "clearance_managed_by_firmware": prepared["startup"] == K2_AUTO_STARTUP,
              "clearance_measured_by_file": False, "physical_printer_tested": False,
              "clearance_positioned_after_home": prepared["startup"] == "ke_auto_home_slow_z",
              "tempo_map_scaled_by": profile.tempo_ratio, "output_bpm": result["output_bpm"],
              "warnings": prepared["warnings"], "validation": {}}
    try:
        with tempfile.TemporaryDirectory(prefix="klipper-midi-studio-") as directory:
            for label, selected, selected_duration in sections:
                instructions, _ = plan(selected, selected_duration, PLANNER, profile)
                is_u1 = prepared["printer"]["id"] == "snapmaker_u1"
                if is_u1:
                    text = render(ASSETS / "u1_metadata.gcode", song["filename"], selected, instructions, selected_duration,
                                  profile, prepared["startup"], clear_mesh_before_home=True)
                    text = text.replace("; Compatibility marker above; actual generator: KlipperMIDI v7 two-voice XY",
                                        "; Compatibility marker above; actual generator: MIDI Studio 0.5")
                    text = text.replace("; Motion profile:", f"; Global MIDI transpose: {prepared['transpose']:+d} semitones\n; Motion profile:", 1)
                else:
                    text = render_generic(song["filename"], selected, instructions, selected_duration,
                                          profile, prepared["printer"], prepared["transpose"], startup_mode=prepared["startup"])
                provenance = {"printer_source": prepared["printer"].get("source"), "library_source": song.get("library_source")}
                text = "; Sources and licenses: " + json.dumps(provenance, ensure_ascii=True) + "\n" + text
                section = {"frames": selected, "duration_s": selected_duration, "instructions": instructions,
                           "startup_mode": prepared["startup"], "profile": asdict(profile)}
                path = Path(directory) / (label + ".gcode")
                # Validate the same LF bytes that the HTTP download serves;
                # write_text would translate them to CRLF on Windows.
                path.write_bytes(text.encode("ascii"))
                checked = (validate(path, section, [asdict(n) for n in prepared["score"]], PLANNER) if is_u1 else
                           validate_generic(text, instructions, selected, selected_duration, profile, prepared["printer"], PLANNER,
                                            startup_mode=prepared["startup"]))
                name = filename_stem + ("_test" if label == "test" else "") + ".gcode"
                checked["file"] = name
                checked["z_isolation"]["file"] = name
                result["downloads"][label] = {"name": name, "text": text, "seconds": selected_duration, "bytes": len(text)}
                report["validation"][label] = checked
                if label == "full":
                    result["path"] = [[i["x"], i["y"]] for i in instructions if i["kind"] == "move"]
    except ValueError as exc:
        if "short" in str(exc).lower() or "converge" in str(exc).lower() or "timing" in str(exc).lower():
            raise InputError("Bu notalar seçilen ayarlarda çok kısa kalıyor. Tempoyu veya hareket hızını düşürüp yeniden dene.") from exc
        raise InputError("Bu MIDI için hareket planı oluşturulamadı. Daha yavaş hız ve tempo seçmeyi dene.") from exc
    result["downloads"]["report"] = {"name": filename_stem + "_kontrol.json", "text": json.dumps(report, indent=2, ensure_ascii=False)}
    result["checks"] = {"xy_only": prepared["startup"] != "ke_auto_home_slow_z", "music_xy_only": True,
                        "music_axes": profile.music_axes, "music_voice_count": 1 if profile.music_axes == "x" else 2,
                        "startup_slow_z": prepared["startup"] == "ke_auto_home_slow_z",
                        "heating": False, "extrusion": False, "planner": True,
                        "planner_kind": "official_u1" if prepared["printer"]["id"] == "snapmaker_u1" else "klipper_reference",
                        "physical_printer_tested": False}
    return result
