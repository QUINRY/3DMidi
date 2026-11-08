"""Rebuild the bundled MIDI excerpts from licensed primary Mutopia sources.

Normal builds use the locally compiled .source.mid files. --refresh downloads
the pinned primary .ly sources and needs --lilypond to compile them again.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

import mido

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "app" / "assets" / "library"
SOURCES = LIBRARY / "sources"
UPSTREAM_REVISION = "2144afd6f52d56c5b6995b8b589ef1268b3139f0"
UPSTREAM = f"https://raw.githubusercontent.com/MutopiaProject/MutopiaProject/{UPSTREAM_REVISION}/ftp/"
GENERATOR = "GNU LilyPond 2.24.4"
PUBLIC_DOMAIN = "https://creativecommons.org/licenses/publicdomain/"
PIECES = [
    ("fur_elise", "Für Elise", "Ludwig van Beethoven", 931, "Stelios Samelis", "Public Domain", PUBLIC_DOMAIN,
     "beethoven-woo59-fur-elise.mid", "BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59.ly", 40),
    ("moonlight", "Ay Işığı Sonatı · I", "Ludwig van Beethoven", 276, "Stewart Holmes", "CC BY-SA 2.5", "https://creativecommons.org/licenses/by-sa/2.5/",
     "beethoven-op27-2-moonlight-1.mid", "BeethovenLv/O27/moonlight/moonlight-lys/moonlight1-a4.ly", 48),
    ("bach_prelude_c", "Prelude in C · BWV 846", "Johann Sebastian Bach", 5, "Tobias Erbsland", "Public Domain", PUBLIC_DOMAIN,
     "bach-bwv846-wtk1-prelude1.mid", "BachJS/BWV846/wtk1-prelude1/wtk1-prelude1.ly", 32),
    ("bach_invention_1", "İki Sesli İnvensiyon No. 1", "Johann Sebastian Bach", 40, "jeff covey", "CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/",
     "bach-bwv772-invention-01.mid", "BachJS/BWV772/bach-invention-01/bach-invention-01.ly", 32),
    ("pathetique", "Pathétique · Adagio cantabile", "Ludwig van Beethoven", 295, "Chris Sawer", "Public Domain", PUBLIC_DOMAIN,
     "beethoven-op13-pathetique-2.mid", "BeethovenLv/O13/pathetique-2/pathetique-2.ly", 40),
    ("chopin_prelude_e", "Prelude in E minor · Op. 28 No. 4", "Frédéric Chopin", 468, "Magnus Lewis-Smith", "Public Domain", PUBLIC_DOMAIN,
     "chopin-op28-4-prelude.mid", "ChopinFF/O28/Chop-28-4/Chop-28-4.ly", 40),
    ("clair_de_lune", "Clair de lune", "Claude Debussy", 1778, "Keith OHara", "Public Domain", PUBLIC_DOMAIN,
     "debussy-l75-clair-de-lune.mid", "DebussyC/L75/debussy_Ste_Bergamesq_Clair/debussy_Ste_Bergamesq_Clair.ly", 48),
    ("arabesque_1", "Arabesque No. 1", "Claude Debussy", 1777, "Keith OHara", "Public Domain", PUBLIC_DOMAIN,
     "debussy-l66-arabesque-1.mid", "DebussyC/L66/debussy_Arabesque_1/debussy_Arabesque_1.ly", 40),
]


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def compile_source(source_path: Path, midi_path: Path, lilypond: str):
    binary = Path(lilypond).resolve()
    converter = binary.with_name("convert-ly.py")
    python = binary.with_name("python.exe")
    if converter.exists() and python.exists():
        convert_command = [str(python), str(converter)]
    else:
        converter_name = shutil.which("convert-ly")
        if not converter_name:
            raise ValueError("convert-ly is required next to LilyPond or on PATH")
        convert_command = [converter_name]
    version = subprocess.run([str(binary), "--version"], capture_output=True, check=True).stdout.decode()
    number = re.search(r"GNU LilyPond ([0-9.]+)", version).group(1)
    with tempfile.TemporaryDirectory(prefix="klippermidi-library-") as directory:
        temp = Path(directory)
        converted = subprocess.run([*convert_command, "--to=" + number, str(source_path.resolve())], capture_output=True, check=True).stdout.decode("utf-8")
        # This removed Scheme function only controls engraved beam grouping.
        # Modern LilyPond's default beaming does not change performed notes.
        if source_path.stem == "moonlight":
            converted = re.sub(r"^.*#\(override-auto-beam-setting[^\n]*\n", "", converted, flags=re.M)
        converted_path = temp / source_path.name
        converted_path.write_text(converted, encoding="utf-8")
        result = subprocess.run([str(binary), "-dno-print-pages", "-dno-point-and-click", "-o", str(temp / source_path.stem), str(converted_path)], capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr.decode(errors="replace")[-3000:])
        data = (temp / (source_path.stem + ".mid")).read_bytes()
        mido.MidiFile(file=io.BytesIO(data))
        midi_path.write_bytes(data)


def preserve_source(piece, refresh=False, lilypond=None):
    ident, _, _, _, _, _, _, midi_name, lily_path, _ = piece
    midi_path = SOURCES / f"{ident}.source.mid"
    source_path = SOURCES / f"{ident}.ly"
    if refresh or not source_path.exists():
        source_path.write_bytes(download(UPSTREAM + lily_path))
    # Check the encoding licence against the primary source, rather than just
    # assuming that the public-domain composition makes the encoding reusable.
    source = source_path.read_text(encoding="utf-8")
    expected = {"Public Domain": "Public Domain", "CC BY-SA 2.5": "Attribution-ShareAlike 2.5", "CC BY-SA 3.0": "Attribution-ShareAlike 3.0"}[piece[5]]
    if expected not in source:
        raise ValueError(f"Upstream licence differs for {ident}")
    if refresh or not midi_path.exists():
        if not lilypond:
            raise ValueError("--lilypond <path-to-lilypond> is required to compile primary sources")
        compile_source(source_path, midi_path, lilypond)
    return midi_path


def excerpt(source: Path, target: Path, seconds: float, transpose: int = 0):
    """Retain MIDI timing/tempo changes and release every note at the cut.

    All tracks are merged into a standard type-0 MIDI. Only the opening excerpt
    is retained, with optional documented octave transposition. Tempo,
    velocity and instrumentation are retained.
    The app itself makes the selected printer's two-motor arrangement.
    """
    original = mido.MidiFile(source)
    output = mido.MidiFile(type=0, ticks_per_beat=original.ticks_per_beat)
    track = mido.MidiTrack()
    output.tracks.append(track)
    active = Counter()
    tempo = 500000
    elapsed = 0.0
    channels = set()
    for message in mido.merge_tracks(original.tracks):
        delta_seconds = mido.tick2second(message.time, original.ticks_per_beat, tempo)
        if elapsed + delta_seconds > seconds:
            remaining = max(0, round(mido.second2tick(seconds - elapsed, original.ticks_per_beat, tempo)))
            track.append(mido.MetaMessage("marker", text="End of opening excerpt", time=remaining))
            elapsed = seconds
            break
        elapsed += delta_seconds
        if message.type == "end_of_track":
            continue
        if message.type in {"note_on", "note_off", "polytouch"}:
            if not 0 <= message.note + transpose <= 127:
                raise ValueError("Excerpt transposition leaves the MIDI range")
            track.append(message.copy(note=message.note + transpose))
        else:
            track.append(message.copy())
        if message.type == "set_tempo":
            tempo = message.tempo
        if hasattr(message, "channel"):
            channels.add(message.channel)
        if message.type == "note_on" and message.velocity:
            active[(message.channel, message.note + transpose)] += 1
        elif message.type in {"note_on", "note_off"}:
            key = (message.channel, message.note + transpose)
            if active[key]:
                active[key] -= 1
    for (channel, pitch), count in active.items():
        for _ in range(count):
            track.append(mido.Message("note_off", channel=channel, note=pitch, velocity=0, time=0))
    for channel in channels:
        track.append(mido.Message("control_change", channel=channel, control=64, value=0, time=0))
        track.append(mido.Message("control_change", channel=channel, control=123, value=0, time=0))
    track.append(mido.MetaMessage("end_of_track", time=0))
    output.save(target)
    check = mido.MidiFile(target)
    notes = [message.note for message in check if message.type == "note_on" and message.velocity and message.channel != 9]
    if not notes or check.length > seconds + .02:
        raise ValueError(f"Invalid excerpt: {target}")
    return {"duration_seconds": round(check.length, 3), "note_count": len(notes), "pitch_range": [min(notes), max(notes)],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


def build(refresh=False, lilypond=None):
    if refresh and not lilypond:
        raise ValueError("--refresh needs --lilypond <path-to-lilypond>; normal offline builds need only mido")
    SOURCES.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda piece: preserve_source(piece, refresh, lilypond), PIECES))
    items = []
    credits = ["# Mutopia MIDI examples", "", "Primary sources retrieved 2026-11-08. The eight Mutopia examples below were compiled locally from the Mutopia Project's own licensed LilyPond notation using GNU LilyPond 2.24.4. The additional user-local popular MIDI collection is documented separately in `popular/SOURCES_AND_LICENSES.json`; it is not included in this open-licence claim.",
               "The compositions and the notation/encoding licences are recorded separately below. Primary `.ly` files and the locally compiled `.source.mid` files are preserved in `sources/`; source headers contain the original licence and typesetter credits. The generated excerpts retain those licences.", "",
               f"Primary repository revision: `{UPSTREAM_REVISION}`. Each source URL below is pinned to that revision. The encodings' reuse permission was checked in the primary notation headers, independently of the composition's public-domain status.", "",
               "Each displayed demo is the opening 32–48 seconds, merged to MIDI type 0. Tempos, velocities and instrument events are unchanged. Für Elise is transposed down one octave to fit the motor pitch range; other excerpts keep their source pitch. All sounding notes/pedals are released at the cut. The app separately arranges the imported notes for the chosen printer. The excerpts therefore retain the encoding's original licence; the two ShareAlike excerpts remain available under their respective CC BY-SA licences.", "",
               "Rebuild the excerpts offline with `python tools/build_midi_library.py` (Python + mido). To download the same pinned notation and recompile, supply `--refresh --lilypond <path-to-lilypond>`; LilyPond and convert-ly are required only for recompilation. No compiler is required to run the application.", "",
               "Compilation evidence: all eight primary scores compiled successfully with LilyPond 2.24.4; generated MIDI metadata identifies that compiler and the source staff names. convert-ly updates obsolete LilyPond syntax before compilation. For Moonlight only, three obsolete `override-auto-beam-setting` calls are removed from the temporary converted file; these affect printed beam grouping, not performed notes. Original primary source files remain unchanged.", ""]
    for piece, source in zip(PIECES, paths):
        ident, title, composer, mutopia_id, typesetter, license_name, license_url, midi_name, lily_path, seconds = piece
        filename = f"library/{ident}.mid"
        transpose = -12 if ident == "fur_elise" else 0
        stats = excerpt(source, LIBRARY / f"{ident}.mid", seconds, transpose)
        compiled = mido.MidiFile(source)
        generator = next((message.text.strip() for message in compiled if message.type == "text" and message.text.strip().startswith("GNU LilyPond")), GENERATOR)
        staff_names = sorted({message.name.split(":")[0] for track in compiled.tracks[1:] for message in track if message.type == "track_name"})
        primary = (SOURCES / f"{ident}.ly").read_text(encoding="utf-8")
        source_staff_names = sorted(set(re.findall(r'\\(?:new|context)\s+Staff\s*=\s*"([^"]+)"', primary)))
        if staff_names != source_staff_names:
            raise ValueError(f"Compiled MIDI staff names differ from primary notation: {ident}")
        source_url = f"https://www.mutopiaproject.org/cgibin/piece-info.cgi?id={mutopia_id}"
        attribution = f"{composer}; LilyPond/MIDI: {typesetter}, Mutopia Project #{mutopia_id}."
        item = {"id": ident, "title": title, "composer": composer, "filename": filename,
                "license": license_name, "license_url": license_url, "source_url": source_url,
                "attribution": attribution, "origin": "generated", "generator": generator,
                "provenance": {"method": "Compiled locally from pinned primary LilyPond notation", "staff_names": staff_names},
                "encoding_source_url": UPSTREAM + lily_path,
                "source_revision": UPSTREAM_REVISION,
                "notation_sha256": hashlib.sha256((SOURCES / f"{ident}.ly").read_bytes()).hexdigest(),
                "notes": f"İlk {seconds} saniyelik deneme kesiti. " + ("Motor aralığı için bir oktav aşağı alındı; orijinal tempo korundu. " if transpose else "Orijinal tempo ve perdeler korundu. ") + "Çok sesli notalar seçilen yazıcı için uygulamada düzenlenir.",
                "transpose_semitones": transpose,
                "transformation": f"Opening {seconds}s excerpt; merged type 0; explicit note/pedal releases at cut; transpose {transpose:+d} semitones; no tempo change.", **stats}
        items.append(item)
        credits += [f"## {title}", "", attribution, "", f"Encoding licence: [{license_name}]({license_url}).", "Composition: public domain.",
                    f"Source and licence: {source_url}", f"Primary LilyPond source: {UPSTREAM + lily_path}",
                    f"Notation SHA-256: `{item['notation_sha256']}`", f"Locally compiled full MIDI SHA-256: `{stats['original_sha256']}`", f"Excerpt: `{filename}` — {stats['duration_seconds']} seconds; {stats['note_count']} notes. {item['transformation']}", ""]
        credits += [f"Compiled MIDI metadata: `{generator}`; staff names `{', '.join(staff_names)}` match the primary score's Staff definitions. The generated encoding is directly traceable to the licensed notation above.", ""]
    mario = ROOT / "app" / "assets" / "mario.mid"
    if mario.exists():
        midi = mido.MidiFile(mario)
        count = sum(message.type == "note_on" and message.velocity > 0 for message in midi)
        items.insert(0, {"id": "mario", "title": "Super Mario Theme · senin MIDI dosyan", "composer": "Koji Kondo", "filename": "mario.mid",
                         "license": "Kullanıcı dosyası; yeniden dağıtım izni belirtilmedi", "license_url": "", "source_url": "",
                         "attribution": "Kullanıcı tarafından bu çalışma için sağlanan MIDI.", "origin": "user supplied",
                         "notes": "Daha önce verdiğin çok sesli test dosyası. İnternetten edinilen açık lisanslı kitaplığa ait değildir.",
                         "duration_seconds": round(midi.length, 3), "note_count": count, "sha256": hashlib.sha256(mario.read_bytes()).hexdigest()})
        credits += ["## User-supplied Super Mario Theme", "", "`app/assets/mario.mid` was supplied by the user for this local project. No redistribution permission was asserted. This existing file is kept separate from the openly licensed downloaded examples. A publicly distributed application package should omit this user asset unless suitable permission is obtained.", ""]
    manifest = ROOT / "app" / "midi_library.json"
    known_ids = {item["id"] for item in items}
    extras = [item for item in json.loads(manifest.read_text(encoding="utf-8"))["items"]
              if item["id"] not in known_ids] if manifest.exists() else []
    items = [item for item in items if item["id"] == "mario"] + extras + [item for item in items if item["id"] != "mario"]
    manifest.write_text(json.dumps({"version": 1, "items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LIBRARY / "SOURCES_AND_LICENSES.md").write_text("\n".join(credits), encoding="utf-8")
    print(json.dumps([{key: item[key] for key in ("id", "duration_seconds", "note_count", "license")} for item in items], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Download pinned primary notation and recompile it")
    parser.add_argument("--lilypond", help="LilyPond executable path (required for --refresh)")
    args = parser.parse_args()
    build(args.refresh, args.lilypond)
