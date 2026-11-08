"""Desktop contracts: authenticated local API and bounded native file saving."""
from http.cookiejar import CookieJar
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "app", ROOT / "tools"):
    sys.path.insert(0, str(folder))

from desktop.host import DesktopServer, NativeAPI, exported_file
import server as backend


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.host = DesktopServer()
        self.host.start()
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def tearDown(self):
        self.host.close()

    def login(self):
        self.client.open(self.host.start_url, timeout=5).close()

    def test_api_requires_a_bootstrapped_desktop_cookie(self):
        with self.assertRaises(HTTPError) as error:
            self.client.open(self.host.origin + "/api/catalog", timeout=5)
        self.assertEqual(error.exception.code, 403)
        self.login()
        with self.client.open(self.host.origin + "/api/catalog", timeout=5) as response:
            data = json.load(response)
        self.assertEqual(data["runtime"]["mode"], "desktop")
        self.assertEqual(data["default_id"], "snapmaker_u1")
        self.assertEqual(len(data["library"]), 129)
        with self.client.open(self.host.origin + "/locales.json", timeout=5) as response:
            self.assertEqual(len(json.load(response)["languages"]), 10)

    def test_cross_origin_post_is_rejected_even_with_cookie(self):
        self.login()
        request = Request(self.host.origin + "/api/demo", data=b'{}',
                          headers={"Origin": "https://other.example"})
        with self.assertRaises(HTTPError) as error:
            self.client.open(request, timeout=5)
        self.assertEqual(error.exception.code, 403)

    def test_host_spoof_is_rejected_even_with_cookie(self):
        self.login()
        request = Request(self.host.origin + "/api/catalog", headers={"Host": "other.example"})
        with self.assertRaises(HTTPError) as error:
            self.client.open(request, timeout=5)
        self.assertEqual(error.exception.code, 403)

    def test_save_bridge_only_resolves_registered_exports(self):
        with self.assertRaises(ValueError):
            exported_file("file:///C:/private.txt")
        result = {"downloads": {"test": {"name": "Test_Orta_Orta_test.gcode", "text": "G90\n"}}}
        backend.register_exports(result)
        url = result["downloads"]["test"]["url"]
        self.assertEqual(exported_file(url)["body"], b"G90\n")
        with self.assertRaises(ValueError):
            exported_file(url.replace("Test_Orta_Orta_test.gcode", "other.gcode"))

    def test_native_save_retains_extension_and_handles_cancel(self):
        result = {"downloads": {"test": {"name": "Test_Orta_Orta_test.gcode", "text": "G90\n"}}}
        backend.register_exports(result)
        bridge = NativeAPI(self.host.origin)
        window = Mock()
        bridge._window = window
        window.get_current_url.return_value = self.host.origin + "/"
        window.create_file_dialog.return_value = None
        self.assertTrue(bridge.save_export(result["downloads"]["test"]["url"])["cancelled"])
        from webview.util import parse_file_type
        for file_filter in window.create_file_dialog.call_args.kwargs["file_types"]:
            parse_file_type(file_filter)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "melodi"
            window.create_file_dialog.return_value = (str(path),)
            saved = bridge.save_export(result["downloads"]["test"]["url"])
            self.assertEqual(saved["name"], "melodi.gcode")
            self.assertEqual(path.with_suffix(".gcode").read_bytes(), b"G90\n")
        window.get_current_url.return_value = "https://other.example/"
        self.assertIn("error", bridge.save_export(result["downloads"]["test"]["url"]))


if __name__ == "__main__":
    unittest.main()
