"""Public hosting contract: private sessions, bounded input, real downloads."""
import io
import json
from pathlib import Path
import sys
import unittest

import mido

sys.path.insert(0, str(Path(__file__).resolve().parent))
from printers import public_profiles
from web import create_app, MAX_UPLOAD
from web_state import BrowserStore


def midi_bytes():
    midi = mido.MidiFile()
    track = mido.MidiTrack()
    midi.tracks.append(track)
    for note in (60, 64, 67):
        track.append(mido.Message("note_on", note=note, velocity=80))
        track.append(mido.Message("note_off", note=note, time=480))
    out = io.BytesIO()
    midi.save(file=out)
    return out.getvalue()


class WebTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-only",
                               "TRUSTED_HOSTS": ["localhost"], "JOB_WAIT_SECONDS": 0})
        self.a, self.b = self.app.test_client(), self.app.test_client()

    def post(self, client, path, data):
        return client.post(path, json=data, base_url="https://localhost")

    def upload(self, client):
        response = client.post("/api/upload?name=private.mid", data=midi_bytes(), base_url="https://localhost")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json["id"]

    def test_public_library_and_processing_labels_are_honest(self):
        response = self.a.get("/api/catalog", base_url="https://localhost")
        self.assertEqual(len(response.json["library"]), 129)
        self.assertEqual(response.json["default_id"], "snapmaker_u1")
        self.assertEqual(response.json["runtime"]["mode"], "public")
        insomnia = next(item for item in response.json["library"] if item["id"] == "popular_faithless_insomnia")
        self.assertEqual(insomnia["license"], "Lisans belirtilmemiş")
        self.assertEqual(self.post(self.a, "/api/demo", {"id": insomnia["id"]}).status_code, 200)
        default = self.post(self.a, "/api/demo", {})
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default.json["filename"], "Super Mario Theme.mid")
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(flag, cookie)

    def test_popular_example_preserves_its_title_and_source_in_the_download(self):
        loaded = self.post(self.a, "/api/demo", {"id": "popular_faithless_insomnia"})
        self.assertEqual(loaded.status_code, 200, loaded.json)
        self.assertEqual(loaded.json["filename"], "Insomnia.mid")
        result = self.post(self.a, "/api/generate", {"id": loaded.json["id"], "settings": {
            "printer": "creality_k2_pro", "sound_mode": "foc_band", "speed": "medium", "tempo": "medium"}})
        self.assertEqual(result.status_code, 200, result.json)
        report = json.loads(result.json["downloads"]["report"]["text"])
        self.assertEqual(report["library_source"]["artist"], "Faithless")
        self.assertEqual(report["library_source"]["license"], "Lisans belirtilmemiş")
        file = result.json["downloads"]["test"]
        self.assertEqual(file["name"], "CrealityK2Pro_Insomnia_FOCX_Orta_Orta_test.gcode")
        response = self.a.get(file["url"], base_url="https://localhost")
        self.assertEqual(response.data, file["text"].encode("ascii"))

    def test_other_visitor_cannot_preview_or_download_a_private_song(self):
        token = self.upload(self.a)
        settings = {"printer": "creality_k2_pro", "sound_mode": "foc_band", "foc_axis": "y"}
        data = {"id": token, "settings": settings}
        self.assertEqual(self.post(self.b, "/api/preview", data).status_code, 400)
        result = self.post(self.a, "/api/generate", data)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["music_axes"], "x")
        file = result.json["downloads"]["test"]
        self.assertTrue(file["name"].endswith(".gcode"))
        self.assertIn("FOCX", file["name"])
        own = self.a.get(file["url"], base_url="https://localhost")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.data, file["text"].encode("ascii"))
        self.assertIn(file["name"], own.headers["Content-Disposition"])
        self.assertEqual(self.b.get(file["url"], base_url="https://localhost").status_code, 404)
        self.assertEqual(self.a.get(file["url"] + "wrong", base_url="https://localhost").status_code, 404)
        music = own.data.decode().split("; MELODY_BEGIN")[1].split("; MELODY_END")[0]
        for line in (line for line in music.splitlines() if line.startswith("G1 ")):
            self.assertEqual({word[0] for word in line.split()[1:]}, {"X", "F"})

    def test_custom_profiles_are_browser_owned_and_still_generate(self):
        source = """[printer]
kinematics: cartesian
max_velocity: 220
max_accel: 3500
[stepper_x]
position_max: 241
rotation_distance: 36
microsteps: 16
[stepper_y]
position_max: 235
rotation_distance: 40
microsteps: 16
"""
        before = {p["id"] for p in public_profiles()}
        response = self.post(self.a, "/api/profile", {"filename": "private-printer.cfg", "text": source})
        self.assertEqual(response.status_code, 200, response.json)
        profile_id = response.json["profile"]["id"]
        self.assertEqual(before, {p["id"] for p in public_profiles()})
        for client, present in ((self.a, True), (self.b, False)):
            profiles = client.get("/api/catalog", base_url="https://localhost").json["profiles"]
            self.assertEqual(any(p["id"] == profile_id for p in profiles), present)
        token = self.upload(self.a)
        result = self.post(self.a, "/api/generate", {"id": token, "settings": {"printer": profile_id}})
        self.assertEqual(result.status_code, 200, result.json)
        self.assertIn("privateprintercfg", result.json["downloads"]["full"]["name"])

    def test_host_origin_body_limits_and_traversal(self):
        self.assertEqual(self.a.get("/api/catalog", base_url="https://evil.invalid").status_code, 400)
        response = self.a.post("/api/demo", json={}, base_url="https://localhost",
                               headers={"Origin": "https://evil.invalid"})
        self.assertEqual(response.status_code, 403)
        response = self.a.post("/api/upload?name=test.mid", data=b"x" * (MAX_UPLOAD + 1), base_url="https://localhost")
        self.assertEqual(response.status_code, 413)
        self.assertIn("4 MB", response.json["error"])
        for path in ("/requirements.txt", "/../requirements.txt", "/assets/mario.mid"):
            self.assertEqual(self.a.get(path, base_url="https://localhost").status_code, 404)

    def test_busy_and_rate_limits_return_retryable_json(self):
        token = self.upload(self.a)
        jobs = self.app.extensions["midi_jobs"]
        jobs.acquire()
        try:
            response = self.post(self.a, "/api/generate", {"id": token, "settings": {}})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "3")
        finally:
            jobs.release()
        self.app.extensions["midi_limiter"].count = 1
        response = self.post(self.a, "/api/demo", {})
        self.assertEqual(response.status_code, 429)
        self.assertIn("error", response.json)

    def test_expired_data_is_inaccessible_and_storage_is_bounded(self):
        now = [0]
        store = BrowserStore(ttl=10, max_entries=2, max_bytes=20, per_kind=1, clock=lambda: now[0])
        one = store.put("song", "a", "one", size=8)
        self.assertIsNone(store.get("song", "b", one))
        two = store.put("song", "a", "two", size=8)
        self.assertIsNone(store.get("song", "a", one))
        store.put("song", "b", "three", size=8)
        store.put("song", "c", "four", size=8)
        self.assertIsNone(store.get("song", "a", two))
        self.assertLessEqual(len(store.entries), 2)
        now[0] = 11
        self.assertEqual(store.values("song", "c"), [])
        with self.assertRaises(ValueError):
            store.put("export", "a", "too big", size=21)

    def test_tailscale_client_rate_limit_uses_its_overwritten_header(self):
        self.app.config["PROXY_MODE"] = "tailscale"
        self.app.extensions["midi_limiter"].count = 1
        def submit(ip, cloudflare):
            return self.a.post("/api/demo", json={}, base_url="https://localhost",
                               environ_overrides={"REMOTE_ADDR": "172.18.0.1"},
                               headers={"X-Forwarded-For": ip, "CF-Connecting-IP": cloudflare})
        self.assertEqual(submit("203.0.113.8", "192.0.2.1").status_code, 200)
        self.assertEqual(submit("203.0.113.8", "192.0.2.2").status_code, 429)
        self.assertEqual(submit("203.0.113.9", "192.0.2.1").status_code, 200)

    def test_untrusted_remote_cannot_select_its_rate_limit_identity(self):
        self.app.config["PROXY_MODE"] = "tailscale"
        self.app.extensions["midi_limiter"].count = 1
        for index, expected in ((1, 200), (2, 429)):
            response = self.a.post("/api/demo", json={}, base_url="https://localhost",
                                   environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
                                   headers={"X-Forwarded-For": f"203.0.113.{index}"})
            self.assertEqual(response.status_code, expected)


if __name__ == "__main__":
    unittest.main()
