"""Exercise printer/library selection through the HTTP contract used by the UI."""
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request

from server import Handler, ThreadingHTTPServer


class QuietHandler(Handler):
    def log_message(self, *_):
        pass


class CatalogApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def api(self, path, payload=None):
        request = urllib.request.Request(self.base + path, None if payload is None else json.dumps(payload).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def test_catalog_default_sources_and_disabled_models(self):
        catalog = self.api("/api/catalog")
        self.assertEqual(catalog["default_id"], "snapmaker_u1")
        self.assertEqual(sum(p["selectable"] and p.get("firmware_family") == "klipper" and not p["id"].startswith("custom_") for p in catalog["profiles"]), 19)
        self.assertEqual(sum(p["selectable"] and p.get("firmware_family") == "bambu" for p in catalog["profiles"]), 12)
        self.assertEqual(sum(p.get("firmware_family") == "bambu" for p in catalog["profiles"]), 15)
        self.assertGreaterEqual(len(catalog["library"]), 109)
        for profile in catalog["profiles"]:
            if profile["selectable"] and not profile["id"].startswith("custom_"):
                self.assertTrue(profile["source"]["url"].startswith("https://github.com/"))
                if profile.get("firmware_family") == "klipper":
                    self.assertTrue(profile["music_bounds"]["x"][0] < profile["start_xy"][0] < profile["music_bounds"]["x"][1])
                else:
                    self.assertEqual(profile["native_music"]["muted_channels"], ["Z"])
                    self.assertNotIn("x", profile)
        song = self.api("/api/demo", {"id": "bach_prelude_c"})
        blocked = next(p for p in catalog["profiles"] if not p["selectable"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.api("/api/preview", {"id": song["id"], "settings": {"printer": blocked["id"]}})
        self.assertEqual(error.exception.code, 400)

    def test_model_specific_export_keeps_attribution_and_real_attachment(self):
        song = self.api("/api/demo", {"id": "moonlight"})
        result = self.api("/api/generate", {"id": song["id"], "settings": {
            "printer": "creality_k1_72", "speed": "medium", "tempo": "medium",
            "startup": "xy_home_zero_hop"}})
        self.assertEqual(result["settings"]["startup"], "prepared_no_z")
        self.assertEqual(result["printer"]["x"]["rotation_distance"], 72)
        self.assertNotEqual(result["printer"]["start_xy"], [135, 135])
        self.assertTrue(result["downloads"]["full"]["name"].startswith("CrealityK172mmkasnakprofili_moonlight_Orta_Orta"))
        with urllib.request.urlopen(self.base + result["downloads"]["full"]["url"]) as response:
            self.assertEqual(response.headers.get_content_disposition(), "attachment")
            self.assertEqual(response.headers.get_filename(), result["downloads"]["full"]["name"])
            data = response.read()
        report = json.loads(result["downloads"]["report"]["text"])
        self.assertEqual(hashlib.sha256(data).hexdigest(), report["validation"]["full"]["sha256"])
        self.assertIn("CC BY-SA", report["library_source"]["license"])
        self.assertIn(b"Sources and licenses", data)
        commands = [line.split(";", 1)[0].strip() for line in data.decode("ascii").splitlines()]
        self.assertFalse(any(line.startswith("G28") for line in commands))
        self.assertFalse(any(any(word.startswith("Z") for word in line.split()[1:]) for line in commands))

    def test_custom_config_and_invalid_library_id(self):
        text = """[printer]
kinematics: cartesian
max_velocity: 200
max_accel: 3500
[stepper_x]
position_max: 240
rotation_distance: 40
microsteps: 16
gear_ratio: 80:16
[stepper_y]
position_max: 200
rotation_distance: 32
microsteps: 32
[gcode_macro DO_NOT_EXECUTE]
gcode:
    G1 Z100
"""
        profile = self.api("/api/profile", {"filename": "real-printer.cfg", "text": text})["profile"]
        self.assertTrue(profile["id"].startswith("custom_"))
        self.assertEqual(profile["x"]["fullsteps_per_mm"], 25)
        self.assertEqual(profile["y"]["fullsteps_per_mm"], 6.25)
        self.assertEqual(profile["source"]["sha256"], hashlib.sha256(text.encode()).hexdigest())
        song = self.api("/api/demo", {"id": "bach_prelude_c"})
        preview = self.api("/api/preview", {"id": song["id"], "settings": {"printer": profile["id"]}})
        self.assertEqual(preview["settings"]["startup"], "prepared_no_z")
        self.assertLessEqual(preview["acceleration"], 3500)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.api("/api/demo", {"id": "not-a-library-item"})
        self.assertEqual(error.exception.code, 400)

    def test_foc_lock_is_enforced_in_http_preview_export_and_attachment_name(self):
        song = self.api("/api/demo", {"id": "mario"})
        settings = {"printer": "creality_hi", "speed": "fast", "tempo": "fast"}
        preview = self.api("/api/preview", {"id": song["id"], "settings": settings})
        result = self.api("/api/generate", {"id": song["id"], "settings": settings})
        for response in (preview, result):
            self.assertEqual((response["settings"]["speed"], response["settings"]["tempo"]), ("slow", "slow"))
            self.assertEqual(response["output_bpm"], round(response["bpm"] * .75, 1))
            self.assertLessEqual(response["speed_range"][1], 100)
        file = result["downloads"]["full"]
        self.assertEqual(file["name"], "CrealityHi_Super_Mario_Theme_Yavas_Yavas.gcode")
        with urllib.request.urlopen(self.base + file["url"]) as response:
            self.assertEqual(response.headers.get_filename(), file["name"])
            self.assertEqual(response.headers.get_content_disposition(), "attachment")
            self.assertEqual(response.read(), file["text"].encode("ascii"))

    def test_k2_honors_user_settings_and_reports_separate_axis_speeds(self):
        song = self.api("/api/demo", {"id": "mario"})
        settings = {"printer": "creality_k2_pro", "speed": "fast", "tempo": "medium"}
        preview = self.api("/api/preview", {"id": song["id"], "settings": settings})
        result = self.api("/api/generate", {"id": song["id"], "settings": settings})
        for response in (preview, result):
            self.assertEqual((response["settings"]["speed"], response["settings"]["tempo"]), ("fast", "medium"))
            self.assertEqual(response["music_axes"], "x")
            self.assertEqual(response["axis_speed_ranges"]["y"], [0, 0])
            self.assertGreater(response["axis_speed_ranges"]["x"][1], 0)
            self.assertEqual(response["output_bpm"], response["bpm"])
        self.assertEqual(result["downloads"]["full"]["name"], "CrealityK2Pro_Super_Mario_Theme_Orta_Hizli.gcode")

    def test_foc_directional_mode_and_scan_use_real_named_http_downloads(self):
        catalog = self.api("/api/catalog")
        self.assertEqual(catalog["foc_reference_bands"]["y"], [.125, .25])
        song = self.api("/api/demo", {"id": "popular_faithless_insomnia"})
        result = self.api("/api/generate", {"id": song["id"], "settings": {
            "printer": "creality_k2_pro", "sound_mode": "foc_band", "foc_axis": "y", "tempo": "medium", "speed": "medium"}})
        self.assertEqual(result["axis_speed_ranges"]["x"], [12, 16])
        self.assertEqual(result["axis_speed_ranges"]["y"], [0, 0])
        self.assertEqual(result["settings"]["foc_axis"], "x")
        file = result["downloads"]["test"]
        self.assertEqual(file["name"], "CrealityK2Pro_Insomnia_FOCX_Orta_Orta_test.gcode")
        with urllib.request.urlopen(self.base + file["url"]) as response:
            self.assertEqual(response.headers.get_filename(), file["name"])
            self.assertEqual(response.read(), file["text"].encode("ascii"))
        with urllib.request.urlopen(self.base + "/api/foc-y-scan/creality_k2_pro") as response:
            self.assertEqual(response.headers.get_filename(), "CrealityK2Pro_Y_Ses_Tarama.gcode")
            data = response.read().decode("ascii")
            self.assertIn("M117 Y01 Y 0.125mm/s", data)
            self.assertEqual(data.splitlines().count("G28 X Y"), 1)

    def test_popular_song_loads_with_readable_name_and_keeps_source_in_export(self):
        song = self.api("/api/demo", {"id": "popular_rick_astley_never_gonna_give_you_up"})
        self.assertEqual(song["filename"], "Never Gonna Give You Up.mid")
        result = self.api("/api/generate", {"id": song["id"], "settings": {"printer": "creality_k2_pro"}})
        report = json.loads(result["downloads"]["report"]["text"])
        self.assertEqual(report["library_source"]["artist"], "Rick Astley")
        self.assertEqual(report["library_source"]["license"], "Lisans belirtilmemiş")
        self.assertTrue(report["library_source"]["download_url"].startswith("https://bitmidi.com/uploads/"))
        self.assertEqual(result["downloads"]["full"]["name"], "CrealityK2Pro_Never_Gonna_Give_You_Up_Yavas_Yavas.gcode")

    def test_malformed_setting_types_return_explained_bad_request(self):
        song = self.api("/api/demo", {})
        for field, value in (("speed", []), ("tempo", {}), ("voice", []), ("startup", [])):
            with self.subTest(field=field), self.assertRaises(urllib.error.HTTPError) as error:
                self.api("/api/preview", {"id": song["id"], "settings": {field: value}})
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.api("/api/preview", {"id": [], "settings": {}})
        self.assertEqual(error.exception.code, 400)

    def test_bambu_download_uses_native_xy_sound_and_mutes_z(self):
        song = self.api("/api/demo", {"id": "fur_elise"})
        result = self.api("/api/generate", {"id": song["id"], "settings": {
            "printer": "bambu_a1_mini", "speed": "fast", "tempo": "slow", "voice": "duet"}})
        self.assertEqual(result["printer"]["firmware_family"], "bambu")
        self.assertEqual(result["output_mode"], "bambu_native")
        self.assertFalse(result["checks"]["planner"])
        self.assertTrue(result["checks"]["z_channel_muted"])
        file = result["downloads"]["full"]
        self.assertEqual(file["name"], "BambuLabA1mini_fur_elise_Yavas_Ince.gcode")
        with urllib.request.urlopen(self.base + file["url"]) as response:
            self.assertEqual(response.headers.get_filename(), file["name"])
            self.assertEqual(response.headers.get_content_disposition(), "attachment")
            data = response.read()
        self.assertEqual(data, file["text"].encode("ascii"))
        executable = [line.split(";", 1)[0].strip() for line in file["text"].splitlines()]
        executable = [line for line in executable if line]
        self.assertTrue(all(line.split()[0] in {"M17", "M400", "M1006"} for line in executable))
        notes = [line.split() for line in executable if line.startswith("M1006 A")]
        self.assertTrue(notes)
        for row in notes:
            self.assertTrue({"E0", "F0", "N0"}.issubset(row))
        self.assertFalse(any(line.startswith("M18") for line in executable))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.api("/api/generate", {"id": song["id"], "settings": {"printer": "bambu_p1s"}})
        self.assertEqual(error.exception.code, 400)

    def test_ke_defaults_to_auto_home_with_separate_slow_z_setup(self):
        song = self.api("/api/demo", {"id": "mario"})
        result = self.api("/api/generate", {"id": song["id"], "settings": {
            "printer": "creality_ender3_v3_ke", "speed": "medium", "tempo": "medium"}})
        self.assertEqual(result["settings"]["startup"], "ke_auto_home_slow_z")
        self.assertTrue(result["checks"]["startup_slow_z"])
        self.assertTrue(result["checks"]["music_xy_only"])
        self.assertFalse(result["checks"]["xy_only"])
        for kind in ("full", "test"):
            text = result["downloads"][kind]["text"]
            before, music = text.split("; MELODY_BEGIN", 1)
            self.assertIn("\nG28\n", before)
            self.assertNotIn("Z_HOP", text)
            self.assertTrue(any(line.startswith("G1 Z20") and "F180" in line for line in before.splitlines()))
            self.assertFalse(any(any(word.startswith("Z") for word in line.split()[1:])
                                 for line in music.split("; MELODY_END", 1)[0].splitlines() if not line.startswith(";")))
        for path, expected_name in (("/api/ke-slow-z-config", "midi_ke_slow_z.cfg"),
                                    ("/api/ke-slow-z-guide", "KE_YAVAS_Z_KURULUM.txt")):
            with urllib.request.urlopen(self.base + path) as response:
                self.assertEqual(response.headers.get_content_disposition(), "attachment")
                self.assertEqual(response.headers.get_filename(), expected_name)
                self.assertGreater(len(response.read()), 100)


if __name__ == "__main__":
    unittest.main()
