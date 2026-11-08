"""Run 3DMidi as a local, offline Windows application."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
for folder in (ROOT, ROOT / "app", ROOT / "tools"):
    sys.path.insert(0, str(folder))

from desktop import VERSION


def data_directory():
    folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "3DMidi"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def configure_logging(folder):
    handler = RotatingFileHandler(folder / "3dmidi.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")


def self_test(destination):
    """Exercise the bundled engine, resources and protected HTTP API without a GUI."""
    from desktop.host import DesktopServer
    import server as backend
    import hashlib
    from http.cookiejar import CookieJar
    from urllib.request import Request, build_opener, HTTPCookieProcessor, ProxyHandler
    from urllib.error import HTTPError

    host = DesktopServer()
    host.start()
    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
    result = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        try:
            client.open(host.origin + "/api/catalog", timeout=10)
            raise AssertionError("Unauthenticated API request was accepted")
        except HTTPError as exc:
            assert exc.code == 403
        client.open(host.start_url, timeout=10).close()
        def request(path, payload=None):
            data = json.dumps(payload).encode() if payload is not None else None
            with client.open(Request(host.origin + path, data=data,
                                     headers={"Content-Type": "application/json"}), timeout=120) as response:
                return json.load(response)
        catalog = request("/api/catalog")
        assert catalog["runtime"]["mode"] == "desktop"
        assert len(catalog["library"]) == 129
        for item in catalog["library"]:
            data = (backend.ASSETS / item["filename"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == item["sha256"], item["id"]
        demo = request("/api/demo", {"id": "mario"})
        generated = request("/api/generate", {"id": demo["id"], "settings": {
            "printer": "snapmaker_u1", "speed": "medium", "tempo": "medium", "voice": "duet", "startup": "xy_home"}})
        files = []
        for kind, file in generated["downloads"].items():
            with client.open(host.origin + file["url"], timeout=10) as response:
                body = response.read()
                assert body and "attachment" in response.headers["Content-Disposition"]
                if kind != "report":
                    assert file["name"].endswith(".gcode") and b"Z_HOP=" not in body
                files.append(file["name"])
        result.update(ok=True, library=len(catalog["library"]), printers=len(catalog["profiles"]), exports=files)
    except Exception as exc:
        result.update(ok=False, error=str(exc))
        raise
    finally:
        host.close()
        Path(destination).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="3DMidi Windows")
    parser.add_argument("--self-test", metavar="JSON", help="Verify the bundled application and write a JSON report")
    args = parser.parse_args()
    folder = data_directory()
    configure_logging(folder)
    if args.self_test:
        try:
            self_test(args.self_test)
        except Exception as exc:
            logging.exception("Bundled self-test failed")
            Path(args.self_test).write_text(json.dumps({"ok": False, "error": repr(exc)}, indent=2), encoding="utf-8")
            raise SystemExit(1)
        return
    host = None
    lock = None
    try:
        # Keep one window and one persistent browser profile per Windows user.
        import msvcrt
        lock = (folder / "instance.lock").open("a+b")
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"1")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            from desktop.preferences import text
            ctypes.windll.user32.MessageBoxW(None, text("3DMidi is already running. Switch to its open window."), "3DMidi", 0x40)
            return
        import webview
        from desktop.host import DesktopServer, NativeAPI
        try:
            host = DesktopServer(port=18765)
        except OSError:
            host = DesktopServer()
        host.start()
        bridge = NativeAPI(host.origin)
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        window = webview.create_window("3DMidi", host.start_url, js_api=bridge,
            width=1360, height=920, min_size=(1040, 720), background_color="#f7f7f2", text_select=True)
        bridge._window = window
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(folder / "WebView2"),
                      icon=str(ROOT / "desktop/assets/3dmidi.ico"))
    except Exception:
        logging.exception("3DMidi could not start")
        from desktop.preferences import text
        message = (text("Could not start 3DMidi. Make sure Microsoft Edge WebView2 Runtime is installed.") + "\n\n"
                   "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
                   f"Log: {folder / '3dmidi.log'}")
        ctypes.windll.user32.MessageBoxW(None, message, "3DMidi", 0x10)
    finally:
        if host:
            host.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    main()
