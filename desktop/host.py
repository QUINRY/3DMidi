"""An authenticated loopback host and the narrow native save-file bridge."""
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import logging
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, unquote, urlsplit

import server as backend
from desktop import VERSION
from desktop import preferences

COOKIE = "3dmidi_desktop"


class DesktopHandler(backend.Handler):
    def log_message(self, format, *args):
        # Do not put the initial window authentication token in logs.
        logging.getLogger("3dmidi.http").debug("%s %s", self.command, urlsplit(self.path).path)

    def _authorized(self):
        if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}",
                                             f"localhost:{self.server.server_port}"}:
            return False
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            value = cookies[COOKIE].value if COOKIE in cookies else ""
            return secrets.compare_digest(value, self.server.session_token)
        except Exception:
            return False

    def do_GET(self):
        parsed = urlsplit(self.path)
        token = parse_qs(parsed.query).get("desktop_token", [""])[0]
        if (parsed.path == "/" and token
                and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
                and secrets.compare_digest(token, self.server.session_token)):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authorized():
            return self.reply({"error": "3DMidi masaüstü oturumu gerekli."}, 403)
        super().do_GET()

    def do_POST(self):
        if not self._authorized():
            return self.reply({"error": "3DMidi masaüstü oturumu gerekli."}, 403)
        super().do_POST()

    def reply(self, data, *args, **kwargs):
        if urlsplit(self.path).path == "/api/catalog" and isinstance(data, dict) and "profiles" in data:
            data = {**data, "runtime": {"mode": "desktop", "name": "3DMidi", "version": VERSION,
                                       "demo_label": "Try Mario"}}
        super().reply(data, *args, **kwargs)


class DesktopServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0):
        self.session_token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), DesktopHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.start_url = f"{self.origin}/?desktop_token={self.session_token}"
        self._thread = threading.Thread(target=self.serve_forever, name="3DMidi-local", daemon=True)

    def start(self):
        self._thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)


def exported_file(url):
    """Resolve only files already generated in this process; never arbitrary paths."""
    if not isinstance(url, str):
        raise ValueError("Geçersiz kayıt bağlantısı.")
    parsed = urlsplit(url)
    parts = parsed.path.split("/")
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or len(parts) != 6 or parts[1:3] != ["api", "download"]:
        raise ValueError("Geçersiz kayıt bağlantısı.")
    with backend.LOCK:
        file = backend.EXPORTS.get(parts[3], {}).get(parts[4])
    if file is None or unquote(parts[5]) != file["name"]:
        raise ValueError("Dosya bulunamadı. G-code'u yeniden oluştur.")
    return file


class NativeAPI:
    def __init__(self, origin):
        self._origin = origin
        self._window = None
        self._saving = threading.Lock()

    def get_preferences(self):
        if not self._window or self._window.get_current_url() != self._origin + "/":
            return {"language": "en"}
        return preferences.get_preferences()

    def set_preferences(self, data):
        if not self._window or self._window.get_current_url() != self._origin + "/":
            raise ValueError("Return to the 3DMidi window and try again.")
        return preferences.set_preferences(data)

    def save_export(self, url, language="en"):
        if not self._window or self._window.get_current_url() != self._origin + "/":
            return {"error": "3DMidi penceresine geri dönüp yeniden dene."}
        if not self._saving.acquire(blocking=False):
            return {"cancelled": True}
        try:
            import webview
            file = exported_file(url)
            suffix = Path(file["name"]).suffix
            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE, save_filename=file["name"],
                file_types=(preferences.text("Gcode files", language) + " (*.gcode)" if suffix == ".gcode" else preferences.text("JSON report", language) + " (*.json)",))
            if not selected:
                return {"cancelled": True}
            target = Path(selected if isinstance(selected, str) else selected[0])
            if target.suffix.lower() != suffix:
                target = target.with_name(target.name + suffix)
                # Adding an extension must not silently overwrite another file.
                mode = "xb"
            else:
                # The Windows save dialog owns the overwrite confirmation.
                mode = "wb"
            with target.open(mode) as stream:
                stream.write(file["body"])
            return {"name": target.name, "cancelled": False}
        except ValueError as exc:
            return {"error": str(exc)}
        except OSError:
            logging.exception("Saving an export failed")
            return {"error": "Dosya kaydedilemedi. Klasör iznini ve dosya adını kontrol et."}
        finally:
            self._saving.release()
