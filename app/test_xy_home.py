"""Normal XY homing remains isolated from music and uses portable arguments."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / "tools")]
import engine
from check_z_isolation import check_z_isolation


def executable(text):
    return [code for line in text.splitlines() if (code := line.split(";", 1)[0].strip())]


class NormalXyHomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = engine.read_midi((engine.ASSETS / "mario.mid").read_bytes(), "Mario.mid")

    def test_default_new_and_legacy_startup_use_plain_xy_home(self):
        for startup in (None, "xy_home", "xy_home_zero_hop"):
            settings = {} if startup is None else {"startup": startup}
            with self.subTest(startup=startup):
                result = engine.convert(self.song, settings)
                self.assertEqual(result["settings"]["startup"], "xy_home")
                report = json.loads(result["downloads"]["report"]["text"])
                for kind in ("full", "test"):
                    text = result["downloads"][kind]["text"]
                    self.assertEqual([line for line in executable(text) if line.startswith("G28")], ["G28 X Y"])
                    self.assertNotIn("Z_HOP", text)
                    check = report["validation"][kind]["z_isolation"]
                    self.assertEqual(check["explicit_z_moves"], 0)
                    self.assertIsNone(check["z_hop_mm"])
                    self.assertEqual(check["homing_z_behavior"], "firmware_default")

    def test_prepared_u1_and_ke_keep_manual_homing(self):
        for settings in ({"startup": "prepared_no_z"}, {"printer": "creality_ender3_v3_ke", "startup": "prepared_no_z"}):
            with self.subTest(settings=settings):
                result = engine.convert(self.song, settings)
                for kind in ("full", "test"):
                    code = executable(result["downloads"][kind]["text"])
                    self.assertFalse(any(line.startswith("G28") for line in code))
                    self.assertFalse(any(word.startswith("Z") for line in code for word in line.split()[1:]))

    def test_checker_requires_standard_xy_home_before_movement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "startup.gcode"
            for command in ("G28", "G28 X Y Z_HOP=0", "G28 X Y Z", "G28 X"):
                with self.subTest(command=command):
                    path.write_text("M204 S300\n" + command + "\nG1 X110 Y110 F1800\n", encoding="ascii")
                    with self.assertRaises(ValueError):
                        check_z_isolation(path, prepared_start=True, xy_home=True)
            path.write_text("M204 S300\nG28 X Y\nG1 X110 Y110 F1800\n", encoding="ascii")
            self.assertEqual(check_z_isolation(path, True, True)["xy_homing_commands"], 1)
            self.assertEqual(check_z_isolation(path, True, xy_home_zero_hop=True)["startup_mode"], "xy_home")
            for text in ("M204 S7000\nG28 X Y\n", "M204 S300\nG28 X Y\nM18\n",
                         "M204 S300\nG28 X Y\nG1 Z20 F300\n"):
                path.write_text(text, encoding="ascii")
                with self.subTest(text=text), self.assertRaises(ValueError):
                    check_z_isolation(path, True, True)


if __name__ == "__main__":
    unittest.main()
