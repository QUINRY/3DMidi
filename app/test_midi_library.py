"""Validate the actual expanded library, source traceability and MIDI preparation."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools")]
import engine
import mido
from expand_midi_library import quantize_arrangement


class ExpandedMidiLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = json.loads((ROOT / "app" / "midi_library.json").read_text(encoding="utf-8"))["items"]
        cls.additions = [item for item in cls.items if item["id"].startswith("popular_")]

    def test_at_least_100_distinct_new_pieces_with_multiple_popular_genres(self):
        self.assertGreaterEqual(len(self.additions), 100)
        self.assertEqual(len({item["id"] for item in self.items}), len(self.items))
        self.assertEqual(len({item["sha256"] for item in self.additions}), len(self.additions))
        self.assertEqual(len({item["musical_fingerprint"] for item in self.additions}), len(self.additions))
        genres = Counter(item["category"] for item in self.additions)
        self.assertGreaterEqual(genres["Pop"] + genres["Rock"], 50)
        for name in ("Elektronik", "Film / Dizi", "Oyun"):
            self.assertGreaterEqual(genres[name], 5)
        self.assertIn("popular_rick_astley_never_gonna_give_you_up", {i["id"] for i in self.additions})

    def test_every_new_file_opens_and_matches_its_preserved_source_and_licensing(self):
        for item in self.additions:
            with self.subTest(item=item["id"]):
                path = engine.ASSETS / item["filename"]
                self.assertTrue(path.resolve().is_relative_to(engine.ASSETS.resolve()))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
                source = engine.ASSETS / "library" / "sources" / "popular" / (item["id"] + ".mid")
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), item["source_sha256"])
                song = engine.read_midi(path.read_bytes(), path.name)
                self.assertEqual(len(song["notes"]), item["note_count"])
                self.assertLessEqual(abs(song["duration"] - item["duration_seconds"]), .001)
                self.assertTrue(item["source_url"].startswith("https://bitmidi.com/"))
                self.assertTrue(item["download_url"].startswith("https://bitmidi.com/uploads/"))
                self.assertEqual(item["license"], "Lisans belirtilmemiş")
                self.assertTrue(item["transformation"])

    def test_rhythm_preparation_keeps_tempo_and_pitch_and_removes_silent_intro(self):
        midi = mido.MidiFile(type=0, ticks_per_beat=480)
        midi.tracks.append(mido.MidiTrack([
            mido.MetaMessage("set_tempo", tempo=500000),
            mido.Message("note_on", note=60, velocity=90, time=4801),
            mido.Message("note_off", note=60, time=119),
            mido.MetaMessage("set_tempo", tempo=400000, time=120),
            mido.Message("note_on", note=64, velocity=80, time=1),
            mido.Message("note_off", note=64, time=119),
            mido.MetaMessage("end_of_track")]))
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.mid", Path(directory) / "prepared.mid"
            midi.save(source)
            original = source.read_bytes()
            quantize_arrangement(source, target)
            output = engine.read_midi(target.read_bytes(), target.name)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual([n.pitch for n in output["notes"]], [60, 64])
            self.assertEqual(output["notes"][0].start, 0)
            self.assertAlmostEqual(output["notes"][1].start, .25)
            self.assertEqual([t["bpm"] for t in output["tempos"]], [120, 150])
            self.assertLess(output["duration"], .5)


if __name__ == "__main__":
    unittest.main()
