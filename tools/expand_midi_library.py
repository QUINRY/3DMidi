"""Import a curated, source-traceable collection into this user's local library.

Public archive downloads are not labelled as CC/public domain. The original
MIDI, its source page, download URL, checksums and embedded credits are kept.
Offline reruns use those exact cached sources; --fetch permits new downloads.
Only pieces that pass real U1 and K2 Pro conversion are added to the catalogue.
"""
from __future__ import annotations

import argparse
import bisect
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import io
import json
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import engine
import mido
from build_midi_library import excerpt

ASSETS = ROOT / "app" / "assets"
ORIGINALS = ASSETS / "library" / "sources" / "popular"
DESTINATION = ASSETS / "library" / "popular"
MANIFEST = ROOT / "app" / "midi_library.json"
POPULAR_MANIFEST = ROOT / "app" / "popular_midi_sources.json"
EVIDENCE = ROOT / "output" / "library-import"
BASE = "https://bitmidi.com"
RETRIEVED = "2026-11-08"


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", value.casefold())
                  .encode("ascii", "ignore").decode()).strip()


def words(value):
    return set(normalized(value).split()) - {"a", "an", "the", "s", "o", "of", "and", "in", "mid"}


def picks():
    groups = defaultdict(deque)
    for line in Path(__file__).with_name("popular_midi_picks.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        title, artist, category = (part.strip() for part in line.split("|"))
        ident = "popular_" + normalized(artist + " " + title).replace(" ", "_")
        groups[category].append({"id": ident, "title": title, "artist": artist, "category": category})
    # Interleave genres so the target is not filled by the first category.
    output = []
    while any(groups.values()):
        for group in groups.values():
            if group:
                output.append(group.popleft())
    return output


def get(url, fetch, *, binary=False):
    cache = EVIDENCE / "cache" / (hashlib.sha256(url.encode()).hexdigest() + (".mid" if binary else ".html"))
    if cache.exists():
        return cache.read_bytes()
    if not fetch:
        raise ValueError("Source is not cached; use --fetch")
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "KlipperMIDI/0.5 (user-requested local MIDI library)"})
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError("Source exceeds 4 MB")
            if binary and not data.startswith(b"MThd"):
                raise ValueError("Download is not a standard MIDI file")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            time.sleep(.12)
            return data
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt:
                raise
            time.sleep(min(15, max(1, int(exc.headers.get("Retry-After", "2")))))
        except (TimeoutError, urllib.error.URLError):
            if attempt:
                raise
            time.sleep(1)


def source_candidates(pick, fetch):
    ranked = {}
    title_words, artist_words = words(pick["title"]), words(pick["artist"])
    for query in (pick["title"] + " " + pick["artist"], pick["title"]):
        page = get(BASE + "/search?" + urllib.parse.urlencode({"q": query}), fetch).decode("utf-8")
        for path, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
            if not re.fullmatch(r"/[a-zA-Z0-9_-]+-mid(?:-[0-9]+)?", path):
                continue
            name = html.unescape(re.sub("<[^>]+>", "", label)).strip()
            available = words(name)
            if not title_words.issubset(available):
                continue
            artist_match = len(artist_words & available)
            if len(title_words) == 1 and len(next(iter(title_words))) <= 5 and not artist_match:
                continue  # Don't silently substitute a different 'Time', 'Bad', etc.
            score = 10 * artist_match - len(available - title_words - artist_words)
            score -= 15 * bool(available & {"medley", "remix", "live"})
            ranked[path] = (score, name)
        if ranked:
            break
    return [(BASE + path, value[1]) for path, value in sorted(ranked.items(), key=lambda pair: pair[1][0], reverse=True)[:4]]


def resolve(pick, fetch):
    metadata_path = ORIGINALS / (pick["id"] + ".json")
    source_path = ORIGINALS / (pick["id"] + ".mid")
    if metadata_path.exists() and source_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != metadata["source_sha256"]:
            raise ValueError("Cached original MIDI checksum mismatch")
        return metadata
    errors = []
    for source_url, original_name in source_candidates(pick, fetch):
        try:
            page = get(source_url, fetch).decode("utf-8")
            path = re.search(r'href="(/uploads/[0-9]+\.mid)"', page)
            if path is None:
                continue
            download_url = BASE + path.group(1)
            data = get(download_url, fetch, binary=True)
            midi = mido.MidiFile(file=io.BytesIO(data))
            count = sum(m.type == "note_on" and m.velocity > 0 and m.channel != 9 for t in midi.tracks for m in t)
            if count < 25 or not 15 <= midi.length <= 1800:
                raise ValueError("Not a usable musical arrangement")
            credits = list(dict.fromkeys(m.text for t in midi.tracks for m in t
                                        if m.type == "copyright" and m.text.strip()))
            metadata = {**pick, "source_url": source_url, "download_url": download_url,
                        "original_filename": original_name, "source_sha256": hashlib.sha256(data).hexdigest(),
                        "source_duration_seconds": round(midi.length, 6), "source_note_count": count,
                        "embedded_copyright": credits, "retrieved_on": RETRIEVED,
                        "license": "Lisans belirtilmemiş", "license_url": "",
                        "rights_status": "The archive does not establish a reusable licence for this arrangement or composition.",
                        "usage_scope": "User-requested local library; no redistribution permission asserted."}
            source_path.write_bytes(data)
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return metadata
        except (ValueError, OSError, EOFError, KeyError) as exc:
            errors.append(str(exc))
    raise ValueError("No matching valid MIDI found" + (": " + "; ".join(errors) if errors else ""))


def quantize_arrangement(source, target, division=4, pitch_range=None):
    """Snap note gates to a musical grid, retaining the original tempo map.

    Sustain is resolved before snapping. Coincident same-pitch notes merge;
    repeated notes on the same channel are released at their next attack.
    Pitches and tempo events are never transposed or scaled here.
    """
    midi = mido.MidiFile(source)
    song = engine.read_midi(source.read_bytes(), source.name)
    segments = [(0.0, 0, 500000)]
    events, tick, seconds, tempo = [], 0, 0.0, 500000
    for message in mido.merge_tracks(midi.tracks):
        tick += message.time
        seconds += mido.tick2second(message.time, midi.ticks_per_beat, tempo)
        if message.type == "set_tempo":
            tempo = message.tempo
            segments.append((seconds, tick, tempo))
            events.append((tick, 0, message.copy(time=0)))
        elif message.type == "program_change" or message.type == "copyright":
            events.append((tick, 0, message.copy(time=0)))
    times = [s[0] for s in segments]
    grid = midi.ticks_per_beat / division
    def snapped(value):
        start_seconds, start_tick, rate = segments[bisect.bisect_right(times, value) - 1]
        absolute = start_tick + mido.second2tick(value - start_seconds, midi.ticks_per_beat, rate)
        return round(round(absolute / grid) * grid)
    notes = {}
    for note in song["notes"]:
        if pitch_range and not pitch_range[0] <= note.pitch <= pitch_range[1]:
            continue
        start = snapped(note.start)
        end = max(start + max(1, round(grid / 2)), snapped(note.end))
        key = note.channel, note.pitch, start
        old = notes.get(key)
        notes[key] = (max(end, old[0]) if old else end, max(note.velocity, old[1]) if old else note.velocity)
    by_pitch = defaultdict(list)
    for (channel, pitch, start), (end, velocity) in notes.items():
        by_pitch[channel, pitch].append((start, end, velocity))
    for (channel, pitch), group in by_pitch.items():
        group.sort()
        for index, (start, end, velocity) in enumerate(group):
            if index + 1 < len(group):
                end = min(end, group[index + 1][0])
            events.append((start, 2, mido.Message("note_on", channel=channel, note=pitch, velocity=velocity)))
            events.append((end, 1, mido.Message("note_off", channel=channel, note=pitch, velocity=0)))
    last_note = max(t for t, _, m in events if m.type == "note_off")
    first_note = min(t for t, _, m in events if m.type == "note_on")
    initial_tempo = next((m.tempo for t, _, m in sorted(events, key=lambda e: e[0], reverse=True)
                          if m.type == "set_tempo" and t <= first_note), 500000)
    output = mido.MidiFile(type=0, ticks_per_beat=midi.ticks_per_beat)
    track = mido.MidiTrack()
    output.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=initial_tempo))
    previous = 0
    for absolute, _, message in sorted(events, key=lambda event: (event[0], event[1])):
        if absolute > last_note:
            continue
        if message.type == "set_tempo" and absolute <= first_note:
            continue
        absolute = max(0, absolute - first_note)
        track.append(message.copy(time=absolute - previous))
        previous = absolute
    track.append(mido.MetaMessage("end_of_track"))
    output.save(target)


def build_item(source):
    ident = source["id"]
    original, target = ORIGINALS / (ident + ".mid"), DESTINATION / (ident + ".mid")
    data = original.read_bytes()
    # Prefer the complete arrangement; keep the full source even if a bounded
    # excerpt is needed by the converter's documented input/trajectory limits.
    attempts = [(None, None), (None, "grid"), (None, "melodic"),
                (90, None), (90, "grid"), (90, "melodic"), (60, "melodic")]
    errors = []
    for seconds, arrangement in attempts:
        try:
            if seconds is None:
                target.write_bytes(data)
            else:
                excerpt(original, target, seconds)
            if arrangement:
                quantize_arrangement(target, target, pitch_range=(48, 96) if arrangement == "melodic" else None)
            song = engine.read_midi(target.read_bytes(), ident + ".mid")
            verified = {}
            for printer in ("snapmaker_u1", "creality_k2_pro"):
                result = engine.convert(song, {"printer": printer})
                report = json.loads(result["downloads"]["report"]["text"])
                verified[printer] = {"settings": result["settings"], "validation": report["validation"]}
            fingerprint = hashlib.sha256(json.dumps([(round(n.start, 5), round(n.end, 5), n.pitch, n.channel)
                                                    for n in song["notes"]]).encode()).hexdigest()
            transformation = "Full-length source timeline." if seconds is None else f"Opening {seconds}s excerpt; explicit note/pedal releases at cut."
            notes = ("Tam parçadan yazıcı düzenlemesi. " if arrangement else "Tam MIDI düzenlemesi. ") if seconds is None else f"İlk {seconds} saniyelik deneme kesiti. "
            if arrangement:
                transformation += " Note onsets/gates snapped to a 1/16 musical grid; sustain resolved; coincident notes merged; leading silence removed."
                notes += "Nota zamanları yazıcı için 16'lık ritim ızgarasına düzenlendi; baştaki sessizlik çıkarıldı. "
            if arrangement == "melodic":
                transformation += " Only source pitches 48–96 retained; outer bass/treble parts omitted."
                notes += "Orta/tiz melodi aralığı korundu; uç bas/tiz eşlikler ayrıldı. "
            transformation += " No pitch transposition or tempo scaling. Original source MIDI preserved separately."
            item = {**source, "filename": target.relative_to(ASSETS).as_posix(), "origin": "local archive import",
                    "attribution": f"{source['artist']} — {source['title']}; MIDI arşivi: BitMidi; kaynak dosya: {source['original_filename']}.",
                    "duration_seconds": round(song["duration"], 3), "note_count": len(song["notes"]),
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "musical_fingerprint": fingerprint,
                    "transformation": transformation, "arrangement": arrangement,
                    "notes": notes + "Özgün MIDI yerel sources/popular klasöründe korunur. "}
            item["notes"] += "Kaynak arşiv düzenleme lisansı belirtmiyor; kaynak ve dosya künyesi korunmuştur."
            return item, verified
        except (ValueError, OSError, EOFError, KeyError) as exc:
            errors.append(str(exc))
    raise ValueError("Conversion rejected: " + "; ".join(errors))


def build(fetch=False, target_count=120):
    for path in (ORIGINALS, DESTINATION, EVIDENCE):
        path.mkdir(parents=True, exist_ok=True)
    existing = json.loads(MANIFEST.read_text(encoding="utf-8"))
    base = [item for item in existing["items"] if not item["id"].startswith("popular_")]
    items, validation, failures, hashes, fingerprints = [], [], [], set(), set()
    def worker(pick):
        try:
            return resolve(pick, fetch), None
        except Exception as exc:
            return pick, str(exc)
    with ThreadPoolExecutor(max_workers=5) as pool:
        for source, error in pool.map(worker, picks()):
            if len(items) >= target_count:
                continue
            try:
                if error:
                    raise ValueError(error)
                if source["source_sha256"] in hashes:
                    raise ValueError("Duplicate original MIDI")
                item, checks = build_item(source)
                if item["musical_fingerprint"] in fingerprints:
                    raise ValueError("Duplicate musical arrangement")
                hashes.add(source["source_sha256"])
                fingerprints.add(item["musical_fingerprint"])
                items.append(item)
                validation.append({"id": item["id"], "conversions": checks})
                if len(items) % 10 == 0:
                    print(json.dumps({"added": len(items), "last": item["title"], "category": item["category"]}, ensure_ascii=False), flush=True)
            except (ValueError, OSError, EOFError, KeyError) as exc:
                failures.append({"id": source["id"], "title": source["title"], "error": str(exc)})
                print(json.dumps({"skipped": source["title"], "reason": str(exc)[:160]}, ensure_ascii=False), flush=True)
    evidence = {"retrieved_on": RETRIEVED, "added": len(items), "target": target_count,
                "failed_candidates": failures, "validation": validation, "physical_printer_tested": False}
    (EVIDENCE / "verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(items) < target_count:
        raise ValueError(f"Only {len(items)} validated pieces; target {target_count}. The existing catalogue has not been replaced.")
    additions = {"version": 1, "usage_scope": "User-requested local archive imports; not an openly licensed redistribution bundle.", "items": items}
    POPULAR_MANIFEST.write_text(json.dumps(additions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    existing["items"] = base + items
    MANIFEST.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DESTINATION / "SOURCES_AND_LICENSES.json").write_text(json.dumps(additions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"added": len(items), "total": len(existing["items"]),
                      "categories": {c: sum(i["category"] == c for i in items) for c in sorted({i["category"] for i in items})}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Allow public source searches/downloads not already cached")
    parser.add_argument("--count", type=int, default=120)
    args = parser.parse_args()
    if not 100 <= args.count <= 160:
        parser.error("--count must be between 100 and 160")
    build(args.fetch, args.count)
