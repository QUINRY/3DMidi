r"""Regression checks for real HTTP attachments and setting-based export names.

Run from the workspace: .venv\Scripts\python.exe -m unittest discover -s app -p test_downloads.py
"""
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

import engine
from server import Handler, ThreadingHTTPServer


class QuietHandler(Handler):
    def log_message(self, *_):
        pass


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        song = cls.post("/api/demo", {})
        cls.result = cls.post("/api/generate", {"id": song["id"], "settings": {
            "speed": "fast", "tempo": "slow", "voice": "duet", "startup": "xy_home_zero_hop"}})

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    @classmethod
    def post(cls, path, payload):
        request = urllib.request.Request(cls.base + path, json.dumps(payload).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def test_names_follow_printer_midi_tempo_speed(self):
        stem = "SnapmakerU1_Super_Mario_Theme_Yavas_Hizli"
        for kind, suffix in [("full", ".gcode"), ("test", "_test.gcode"), ("report", "_kontrol.json")]:
            with self.subTest(kind=kind):
                self.assertEqual(self.result["downloads"][kind]["name"], stem + suffix)

    def test_direct_http_download_has_name_extension_and_exact_bytes(self):
        # Navigate directly: this exercises the case where a browser host
        # ignores the HTML download attribute. No Blob or DOM hint is used.
        for kind, file in self.result["downloads"].items():
            with self.subTest(kind=kind):
                self.assertTrue("url" in file, "missing direct HTTP attachment URL")
                self.assertTrue(file["url"].startswith("/api/download/"))
                self.assertEqual(urllib.parse.unquote(file["url"].rsplit("/", 1)[1]), file["name"])
                with urllib.request.urlopen(self.base + file["url"]) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_disposition(), "attachment")
                    self.assertIn(f'filename="{file["name"]}"', response.headers["Content-Disposition"])
                    self.assertIn("filename*=UTF-8''", response.headers["Content-Disposition"])
                    self.assertEqual(response.headers.get_filename(), file["name"])
                    body = response.read()
                    self.assertEqual(body, file["text"].encode("utf-8"))
                    if kind != "report":
                        report = json.loads(self.result["downloads"]["report"]["text"])
                        self.assertEqual(hashlib.sha256(body).hexdigest(), report["validation"][kind]["sha256"])
                    self.assertEqual(response.headers.get_content_type(),
                                     "application/json" if kind == "report" else "application/octet-stream")

    def test_unknown_or_wrong_named_download_is_not_served(self):
        file = self.result["downloads"]["full"]
        self.assertTrue("url" in file, "missing direct HTTP attachment URL")
        for url in (file["url"].rsplit("/", 1)[0] + "/wrong.gcode",
                    "/api/download/missing/full/missing.gcode",
                    file["url"].replace("/full/", "/unknown/")):
            with self.subTest(url=url), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + url)
            self.assertEqual(error.exception.code, 404)

    def test_turkish_characters_and_unusual_names(self):
        settings = {"tempo": "slow", "speed": "fast"}
        self.assertEqual(engine.export_stem("Çılgın Rüzgâr.test.MIDI", settings),
                         "SnapmakerU1_Cilgin_Ruzgar_test_Yavas_Hizli")
        for name in ('a\r\n"<>:|?*.mid', "🎵.mid", "CON.mid", " very.long.name.mid"):
            with self.subTest(name=name):
                stem = engine.export_stem(name, settings)
                self.assertRegex(stem, r"^SnapmakerU1_[A-Za-z0-9_-]+_Yavas_Hizli$")
                self.assertLess(len(stem), 130)
        for tempo, tlabel in [("slow", "Yavas"), ("medium", "Orta"), ("fast", "Hizli")]:
            for speed, slabel in [("slow", "Yavas"), ("medium", "Orta"), ("fast", "Hizli")]:
                self.assertEqual(engine.export_stem("mario.mid", {"tempo": tempo, "speed": speed}),
                                 f"SnapmakerU1_mario_{tlabel}_{slabel}")


if __name__ == "__main__":
    unittest.main()
