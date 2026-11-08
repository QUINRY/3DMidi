"""Bambu's native M1006 music protocol, with the Z music channel muted.

This exports queued motor tones, not a Cartesian motion plan. The parameter
mapping comes from Bambu's own MIDI editor; no steps/mm are assumed.
"""
from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy


TEMPOS = {"slow": .75, "medium": 1.0, "fast": 1.25}
REGISTERS = {"slow": -12, "medium": 0, "fast": 12}
NOTE_MIN, NOTE_MAX = 24, 95
TICKS_PER_SECOND, MAX_SEGMENT_TICKS = 100, 200
VOLUME = 70
GUIDE_URL = "https://wiki.bambulab.com/en/A1-mini/Midi"
EDITOR_URL = "https://midi-to-gcode.bambulab.com/browserMain-8002fc808330ff1b5d91.js"
PROTOCOL = {
    "guide_url": GUIDE_URL, "editor_url": EDITOR_URL,
    "editor_sha256": "3e6dc13aa9ad7816b891d4a0bd19acc8b31140cb91f066be9a860dff871caecf",
    "mapping": {"X": "A=pitch, B=duration, L=volume", "Y": "C=pitch, D=duration, M=volume",
                "Z": "E=0, F=0, N=0 (muted)"},
    "midi_to_note_offset": -23, "tick_seconds": .01,
    "note_range": [1, 72], "maximum_segment_ticks": MAX_SEGMENT_TICKS,
    "hardware_motion_tested": False,
}


def _number(value, label):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} sayısal olmalı.") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label} sonlu olmalı.")
    return value


def _fold(pitch):
    while pitch < NOTE_MIN:
        pitch += 12
    while pitch > NOTE_MAX:
        pitch -= 12
    return pitch


def prepare_native(song: dict, settings: dict, printer: dict) -> dict:
    speed, tempo, voice = (settings.get("speed", "medium"), settings.get("tempo", "medium"), settings.get("voice", "duet"))
    if (not all(isinstance(value, str) for value in (speed, tempo, voice))
            or speed not in REGISTERS or tempo not in TEMPOS or voice not in {"duet", "melody"}):
        raise ValueError("Geçersiz Bambu ses ayarı. Sayfayı yenileyip yeniden dene.")
    duration = _number(song["duration"], "MIDI süresi") / TEMPOS[tempo]
    if not 0 < duration <= 800:
        raise ValueError("MIDI süresi Bambu ses modu için uygun değil.")
    # The application MIDI reader has already resolved pedal holds and overlap.
    # Sweep note-on AND note-off boundaries, retaining the active outer voices.
    changes = {}
    for index, note in enumerate(song["notes"]):
        start = _number(note.start, "Nota başlangıcı") / TEMPOS[tempo]
        end = min(duration, _number(note.end, "Nota bitişi") / TEMPOS[tempo])
        if not 0 <= start < end <= duration or not isinstance(note.pitch, int) or not 0 <= note.pitch <= 127:
            raise ValueError("MIDI nota aralığı okunamadı.")
        changes.setdefault(start, {"add": [], "remove": []})["add"].append((index, note.pitch))
        changes.setdefault(end, {"add": [], "remove": []})["remove"].append(index)
    if not changes:
        raise ValueError("Bu MIDI'de çalınabilir nota bulunamadı.")
    boundaries = sorted({0.0, duration, *changes})
    active, frames = {}, []
    simplified = False
    for index, start in enumerate(boundaries[:-1]):
        for key in changes.get(start, {}).get("remove", []):
            active.pop(key, None)
        incoming = changes.get(start, {}).get("add", [])
        active.update(incoming)
        pitches = sorted(set(active.values()))
        simplified |= len(pitches) > 2
        selected = []
        selected_source = []
        if pitches:
            lead = pitches[-1]
            selected = [lead, lead - 12] if voice == "melody" or len(pitches) == 1 else [lead, pitches[0]]
            selected_source = [lead] if voice == "melody" or len(pitches) == 1 else selected
        attack = any(pitch in selected_source for _, pitch in incoming)
        if frames and frames[-1]["pitches"] == selected and not attack:
            frames[-1]["end"] = boundaries[index + 1]
        else:
            frames.append({"start": start, "end": boundaries[index + 1], "pitches": selected, "attack": attack})
    values = [pitch for frame in frames for pitch in frame["pitches"]]
    if not values:
        raise ValueError("Bu MIDI'de çalınabilir nota bulunamadı.")
    requested = REGISTERS[speed]
    candidates = [shift for shift in range(-132, 133, 12)
                  if NOTE_MIN <= min(values) + shift and max(values) + shift <= NOTE_MAX]
    shift = min(candidates, key=lambda item: (abs(item - requested), item)) if candidates else requested
    folded = 0
    for frame in frames:
        changed = []
        for pitch in frame["pitches"]:
            actual = _fold(pitch + shift)
            folded += actual != pitch + shift
            changed.append(actual)
        frame["pitches"] = sorted(changed, reverse=True)
    # Round absolute boundaries so independent per-event rounding cannot drift.
    duration_ticks = round(duration * TICKS_PER_SECOND)
    if duration_ticks < 1:
        raise ValueError("Bu MIDI 10 ms ses çözünürlüğünden kısa.")
    quantized, dropped = [], 0
    max_quantization_error = abs(duration_ticks / TICKS_PER_SECOND - duration)
    for frame in frames:
        begin = round(frame["start"] * TICKS_PER_SECOND)
        end = round(frame["end"] * TICKS_PER_SECOND)
        max_quantization_error = max(max_quantization_error,
                                     abs(begin / TICKS_PER_SECOND - frame["start"]),
                                     abs(end / TICKS_PER_SECOND - frame["end"]))
        if end <= begin:
            dropped += 1
            continue
        pitches = frame["pitches"]
        if quantized and quantized[-1]["end_tick"] == begin and quantized[-1]["pitches"] == pitches and not frame["attack"]:
            quantized[-1]["end_tick"] = end
            quantized[-1]["end"] = end / TICKS_PER_SECOND
        else:
            quantized.append({"start_tick": begin, "end_tick": end,
                              "start": begin / TICKS_PER_SECOND, "end": end / TICKS_PER_SECOND,
                              "pitches": pitches})
    if not any(frame["pitches"] for frame in quantized):
        raise ValueError("Bu MIDI'de 10 ms ses çözünürlüğüne sığan nota kalmadı. Daha yavaş tempo veya daha uzun notalar seç.")
    warnings = [
        "Bambu yerel motor sesi modu: XY yolu veya mm/sn hareket hızı üretilmez; hız seçimi sesin oktavını değiştirir.",
        "Z ses kanalı kapalıdır (E0 F0 N0); home, Z konumlandırma, ısıtma ve filament sürme komutu yoktur.",
        "Yazıcıdaki Ses / Allow Prompt Sound seçeneği açık olmalı. Komut desteği model ve firmware sürümüne bağlıdır; fiziksel test yapılmadı.",
    ]
    if shift != requested:
        warnings.append(f"Yerel ses aralığı için toplam perde değişimi {shift:+d} yarım sese ayarlandı.")
    if folded:
        warnings.append(f"Geniş nota aralığındaki {folded} motor sesi, perde sınıfı korunarak 24–95 MIDI aralığına oktavlandı.")
    if dropped:
        warnings.append(f"10 ms çözünürlüğe sığmayan {dropped} çok kısa nota/sessizlik bölümü atlandı.")
    if simplified:
        warnings.append("İkiden fazla aktif ses, X/Y için en tiz ve en pes sese düzenlendi.")
    if song.get("percussion"):
        warnings.append(f"{song['percussion']} vurmalı nota melodiden ayrıldı.")
    if song.get("bends"):
        warnings.append("Perde bükmeleri sabit notalara indirgenir.")
    return {"printer": deepcopy(printer), "settings": {"printer": printer["id"], "speed": speed, "tempo": tempo,
            "voice": voice, "startup": "native_sound"}, "frames": quantized, "duration": duration_ticks / TICKS_PER_SECOND,
            "duration_ticks": duration_ticks, "unquantized_duration": duration,
            "tempo_ratio": TEMPOS[tempo], "transpose": shift, "warnings": warnings,
            "folded_voice_events": folded, "dropped_short_frames": dropped,
            "max_quantization_error_s": max_quantization_error, "output_mode": "bambu_native"}


def summary_native(song: dict, prepared: dict) -> dict:
    return {"valid": True, "filename": song["filename"], "bytes": song["bytes"], "notes": len(song["notes"]),
            "tracks": song["tracks"], "source_duration": song["duration"], "duration": prepared["duration"],
            "bpm": song["bpm"], "output_bpm": round(song["bpm"] * prepared["tempo_ratio"], 1),
            "tempo_changes": len(song["tempos"]),
            "frames": [{key: frame[key] for key in ("start", "end", "pitches")} for frame in prepared["frames"]],
            "speed_range": [], "speed_cap": None, "speed_caps": {}, "acceleration": None,
            "transpose": prepared["transpose"], "settings": prepared["settings"], "warnings": prepared["warnings"],
            "printer": prepared["printer"], "output_mode": "bambu_native"}


def _segments(frames, limit):
    result = []
    for frame in frames:
        begin, end = frame["start_tick"], min(limit, frame["end_tick"])
        if begin >= end:
            continue
        while begin < end:
            ticks = min(MAX_SEGMENT_TICKS, end - begin)
            result.append({"ticks": ticks, "pitches": frame["pitches"]})
            begin += ticks
    return result


def _render(song, prepared, segments, ticks):
    provenance = {"printer_source": prepared["printer"].get("source"), "library_source": song.get("library_source"),
                  "protocol": PROTOCOL}
    lines = ["; MIDI Studio 0.3 - Bambu native X/Y motor sound",
             "; Printer: " + json.dumps(prepared["printer"]["name"], ensure_ascii=True),
             "; MIDI source: " + json.dumps(song["filename"], ensure_ascii=True),
             "; Sources and licenses: " + json.dumps(provenance, ensure_ascii=True),
             f"; Music duration: {ticks / TICKS_PER_SECOND:.2f} seconds; initial pause is additional",
             "; Z music channel muted; no Cartesian motion, homing, heating or extrusion commands",
             "; Enable printer Sound / Allow Prompt Sound; firmware support is required",
             "; No M18: motors remain enabled after the tune",
             "M17", "M400 S1", "M1006 S1", "M1006 L70 M70 N0", "; MELODY_BEGIN"]
    for segment in segments:
        pitches = segment["pitches"]
        a, c = (pitch - 23 for pitch in pitches) if pitches else (0, 0)
        volume = VOLUME if pitches else 0
        duration = segment["ticks"]
        lines.append(f"M1006 A{a} B{duration} L{volume} C{c} D{duration} M{volume} E0 F0 N0")
    lines += ["; MELODY_END", "M1006 W", "M400"]
    return "\n".join(lines) + "\n"


def validate_native(text: str, expected_segments: list[dict], expected_ticks: int) -> dict:
    """Independently parse the exact exported protocol bytes and reject extra commands."""
    data = text.encode("ascii")
    records = [line.split(";", 1)[0].strip() for line in text.splitlines()]
    records = [line for line in records if line]
    if records[:4] != ["M17", "M400 S1", "M1006 S1", "M1006 L70 M70 N0"] or records[-2:] != ["M1006 W", "M400"]:
        raise ValueError("Bambu ses başlangıcı/bitişi geçersiz.")
    music = records[4:-2]
    if len(music) != len(expected_segments):
        raise ValueError("Bambu ses bölümü eksik veya ek komut içeriyor.")
    parsed_ticks = 0
    for record, expected in zip(music, expected_segments):
        words = record.split()
        if words[0] != "M1006":
            raise ValueError("Bambu ses çıktısında beklenmeyen hareket veya komut bulundu.")
        parameters = {}
        for word in words[1:]:
            if len(word) < 2 or word[0] not in "ABLCDMEFN" or not word[1:].isdigit() or word[0] in parameters:
                raise ValueError("Bambu ses parametresi geçersiz.")
            parameters[word[0]] = int(word[1:])
        if set(parameters) != set("ABLCDMEFN"):
            raise ValueError("Bambu ses kanal parametresi eksik.")
        if (any(parameters[key] != 0 for key in "EFN") or not 1 <= parameters["B"] <= MAX_SEGMENT_TICKS
                or parameters["B"] != parameters["D"] or any(not 0 <= parameters[key] <= 72 for key in "AC")
                or any(not 0 <= parameters[key] <= VOLUME for key in "LM")):
            raise ValueError("Bambu ses kanalı, süre veya ses düzeyi sınırı aşıldı; Z sessiz kalmalı.")
        pitches = expected["pitches"]
        wanted_a, wanted_c = [pitch - 23 for pitch in pitches] if pitches else (0, 0)
        wanted_volume = VOLUME if pitches else 0
        if (parameters["B"] != expected["ticks"] or parameters["A"] != wanted_a or parameters["C"] != wanted_c
                or parameters["L"] != wanted_volume or parameters["M"] != wanted_volume):
            raise ValueError("Bambu çıktısındaki nota veya zamanlama düzenlemeden farklı.")
        parsed_ticks += parameters["B"]
    if parsed_ticks != expected_ticks:
        raise ValueError("Bambu ses süresi 10 ms zaman çizelgesiyle eşleşmiyor.")
    return {"sha256": hashlib.sha256(data).hexdigest(), "native_protocol_validation": "passed",
            "music_segments": len(music), "music_duration_s": parsed_ticks / TICKS_PER_SECOND,
            "tick_seconds": .01, "Z_channel_muted": True, "heating_commands": 0, "extrusion_commands": 0,
            "cartesian_moves": 0, "physical_printer_tested": False,
            "vendor_firmware_execution_verified": False,
            "z_isolation": {"explicit_z_moves": 0, "z_music_notes": 0, "z_music_volume": 0,
                            "motor_disable_commands": 0, "physical_printer_tested": False}}


def convert_native(song: dict, prepared: dict, filename_stem: str) -> dict:
    result = summary_native(song, prepared)
    result["downloads"], result["path"] = {}, []
    report = {"app": "MIDI Studio 0.3 - Bambu native", "output_mode": "bambu_native",
              "source": {key: song[key] for key in ("filename", "sha256", "duration", "tracks")},
              "printer": prepared["printer"], "settings": prepared["settings"], "protocol": PROTOCOL,
              "library_source": song.get("library_source"), "transpose": prepared["transpose"],
              "octave_folded_voice_events": prepared["folded_voice_events"],
              "dropped_sub_tick_frames": prepared["dropped_short_frames"],
              "maximum_boundary_quantization_error_s": prepared["max_quantization_error_s"],
              "duration_quantization_error_s": prepared["duration"] - prepared["unquantized_duration"],
              "warnings": prepared["warnings"], "physical_printer_tested": False,
              "validation": {}}
    for kind, ticks in (("full", prepared["duration_ticks"]), ("test", min(800, prepared["duration_ticks"]))):
        segments = _segments(prepared["frames"], ticks)
        text = _render(song, prepared, segments, ticks)
        check = validate_native(text, segments, ticks)
        name = filename_stem + ("_test" if kind == "test" else "") + ".gcode"
        check["file"] = check["z_isolation"]["file"] = name
        report["validation"][kind] = check
        result["downloads"][kind] = {"name": name, "text": text, "seconds": ticks / TICKS_PER_SECOND,
                                     "bytes": len(text.encode("ascii"))}
    result["downloads"]["report"] = {"name": filename_stem + "_kontrol.json", "text": json.dumps(report, indent=2, ensure_ascii=False)}
    result["checks"] = {"xy_only": False, "native_sound": True, "z_channel_muted": True, "heating": False,
                        "extrusion": False, "planner": False, "planner_kind": "bambu_native_protocol",
                        "physical_printer_tested": False}
    return result
