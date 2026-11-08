"""MIDI Studio. Run: python app/server.py --open"""
from __future__ import annotations

import argparse
import json
import re
import mimetypes
import secrets
import threading
import urllib.parse
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from engine import ASSETS, InputError, convert, prepare, read_midi, summary, source_summary
from printers import public_profiles, import_profile

STATIC = ASSETS.parent / "static"
SONGS = OrderedDict()
EXPORTS = OrderedDict()
LOCK = threading.Lock()
CONVERSION_LOCK = threading.Semaphore(1)
MAX_UPLOAD = 4 * 1024 * 1024


def library_items():
    return json.loads((ASSETS.parent / "midi_library.json").read_text(encoding="utf-8"))["items"]


def remember(song):
    key = secrets.token_urlsafe(18)
    with LOCK:
        SONGS[key] = song
        while len(SONGS) > 16:
            SONGS.popitem(last=False)
    return key


def register_exports(result):
    key = secrets.token_urlsafe(18)
    files = {}
    for kind, file in result["downloads"].items():
        files[kind] = {"name": file["name"], "body": file["text"].encode("utf-8"),
                       "content_type": "application/json; charset=utf-8" if kind == "report" else "application/octet-stream"}
        file["url"] = f"/api/download/{key}/{kind}/{urllib.parse.quote(file['name'], safe='')}"
    with LOCK:
        EXPORTS[key] = files
        while len(EXPORTS) > 16:
            EXPORTS.popitem(last=False)


class Handler(BaseHTTPRequestHandler):
    def reply(self, data, status=200, content_type="application/json; charset=utf-8", download_name=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if not isinstance(data, bytes) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download_name is not None:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"; filename*=UTF-8\'\'{urllib.parse.quote(download_name, safe="")}')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urllib.parse.urlparse("//" + self.headers.get("Host", "")).hostname not in {"127.0.0.1", "localhost"}:
            return self.reply({"error": "Bu uygulama yalnızca yerel bilgisayarda açılır."}, 403)
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/download/"):
            parts = path.split("/")
            file = None
            if len(parts) == 6:
                with LOCK:
                    file = EXPORTS.get(parts[3], {}).get(parts[4])
                if file and urllib.parse.unquote(parts[5]) != file["name"]:
                    file = None
            if file is None:
                return self.reply({"error": "İndirme bulunamadı. G-code'u yeniden oluştur."}, 404)
            return self.reply(file["body"], content_type=file["content_type"], download_name=file["name"])
        if path == "/api/health":
            return self.reply({"app": "MIDI Studio", "version": "0.5"})
        if path.startswith("/api/foc-y-scan/"):
            from foc_acoustic import make_y_scan
            from engine import PLANNER
            from printers import get_profile
            try:
                scan = make_y_scan(get_profile(path.rsplit("/", 1)[-1]), PLANNER)
            except ValueError as exc:
                return self.reply({"error": str(exc)}, 400)
            return self.reply(scan["text"].encode("ascii"), content_type="application/octet-stream", download_name=scan["name"])
        if path in {"/api/ke-slow-z-config", "/api/ke-slow-z-guide"}:
            name = "midi_ke_slow_z.cfg" if path.endswith("config") else "KE_YAVAS_Z_KURULUM.txt"
            target = ASSETS.parents[1] / "reference" / "ke-startup" / name
            if not target.is_file():
                return self.reply({"error": "Kurulum dosyası bulunamadı."}, 404)
            return self.reply(target.read_bytes(), content_type="application/octet-stream", download_name=name)
        if path == "/api/catalog":
            from foc_acoustic import DEFAULT_BANDS
            return self.reply({"default_id": "snapmaker_u1", "profiles": public_profiles(), "library": library_items(), "foc_reference_bands": DEFAULT_BANDS})
        files = {"/": "index.html", "/styles.css": "styles.css", "/app.js": "app.js", "/favicon.svg": "favicon.svg", "/i18n.js": "i18n.js", "/locales.json": "locales.json"}
        if path in files:
            target = STATIC / files[path]
            content_type = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".json": "application/json"}[target.suffix]
            return self.reply(target.read_bytes(), content_type=content_type + "; charset=utf-8")
        self.reply({"error": "Bu sayfa bulunamadı."}, 404)

    def do_POST(self):
        if urllib.parse.urlparse("//" + self.headers.get("Host", "")).hostname not in {"127.0.0.1", "localhost"}:
            return self.reply({"error": "Bu uygulama yalnızca yerel bilgisayarda açılır."}, 403)
        parsed = urllib.parse.urlparse(self.path)
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
            return self.reply({"error": "İstek bu yerel uygulamadan gelmeli."}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_UPLOAD:
                raise InputError("Dosya çok büyük. En fazla 4 MB MIDI seçebilirsin.")
            body = self.rfile.read(length)
            if parsed.path == "/api/upload":
                filename = urllib.parse.parse_qs(parsed.query).get("name", ["melodi.mid"])[0]
                if Path(filename).suffix.lower() not in {".mid", ".midi"}:
                    raise InputError("Lütfen .mid veya .midi dosyası seç.")
                song = read_midi(body, Path(filename).name)
                key = remember(song)
                return self.reply({"id": key, **source_summary(song)})
            if parsed.path == "/api/demo":
                payload = json.loads(body) if body else {}
                if not isinstance(payload, dict):
                    raise InputError("MIDI seçimi okunamadı.")
                item = next((i for i in library_items() if i["id"] == payload.get("id", "mario")), None)
                if item is None:
                    raise InputError("Bu MIDI kitaplıkta bulunamadı.")
                path = (ASSETS / item["filename"]).resolve()
                if not path.is_relative_to(ASSETS.resolve()):
                    raise InputError("Geçersiz kitaplık dosyası.")
                name = ("Super Mario Theme.mid" if item["id"] == "mario" else
                        re.sub(r'[\\/:*?"<>|]', " ", item["title"]) + ".mid" if item.get("artist") else
                        Path(item["filename"]).name)
                song = read_midi(path.read_bytes(), name)
                song["library_source"] = item
                key = remember(song)
                return self.reply({"id": key, **source_summary(song)})
            if parsed.path == "/api/profile":
                payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
                    raise InputError("Yazıcı yapılandırması okunamadı.")
                try:
                    profile = import_profile(payload.get("filename", "printer.cfg"), payload["text"])
                except ValueError as exc:
                    raise InputError(str(exc)) from exc
                return self.reply({"profile": profile})
            if parsed.path not in {"/api/preview", "/api/generate"}:
                return self.reply({"error": "Bu işlem bulunamadı."}, 404)
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict):
                raise InputError("Ayarlar okunamadı. Sayfayı yenileyip yeniden dene.")
            if not isinstance(payload.get("id"), str):
                raise InputError("MIDI oturumu bulunamadı. Dosyanı yeniden seç.")
            with LOCK:
                song = SONGS.get(payload.get("id"))
            if song is None:
                raise InputError("MIDI oturumu bulunamadı. Dosyanı yeniden seç.")
            if parsed.path == "/api/preview":
                return self.reply(summary(song, prepare(song, payload["settings"])))
            if not CONVERSION_LOCK.acquire(blocking=False):
                return self.reply({"error": "Bir dosya hâlâ hazırlanıyor. Birkaç saniye sonra yeniden dene."}, 409)
            try:
                result = convert(song, payload["settings"])
                register_exports(result)
            finally:
                CONVERSION_LOCK.release()
            self.reply(result)
        except (InputError, json.JSONDecodeError) as exc:
            self.reply({"error": str(exc)}, 400)
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            self.reply({"error": "İşlem tamamlanamadı. MIDI dosyasını yeniden seçip tekrar dene."}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=2) as response:
            if json.load(response).get("app") in {"U1 MIDI Studio", "Klipper MIDI Studio", "MIDI Studio"}:
                webbrowser.open(f"http://127.0.0.1:{args.port}")
                return
        raise
    url = f"http://127.0.0.1:{args.port}"
    print("MIDI Studio: " + url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
