"""Public WSGI service; the desktop-only server remains in server.py."""
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import quote, urlsplit

from flask import Flask, jsonify, request, send_file, session
from werkzeug.exceptions import HTTPException, TooManyRequests

from engine import ASSETS, InputError, PLANNER, convert, prepare, read_midi, source_summary, summary
from printers import get_profile, import_profile, public_profiles
from web_state import BrowserStore, RequestLimiter

MAX_UPLOAD = 4 * 1024 * 1024
STATIC = Path(__file__).resolve().parent / "static"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def public_library():
    """Serve the complete user-selected catalog, preserving source/licence metadata."""
    return json.loads((ASSETS.parent / "midi_library.json").read_text(encoding="utf-8-sig"))["items"]


def create_app(config=None):
    hosts = os.environ.get("MIDI_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    hosts = [host.strip().lower() for host in hosts if host.strip()]
    if not hosts or any(not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host) for host in hosts):
        raise ValueError("MIDI_ALLOWED_HOSTS yalnızca tam sunucu adlarını içermeli.")
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.environ.get("MIDI_SESSION_SECRET") or secrets.token_hex(32),
        TRUSTED_HOSTS=list(dict.fromkeys([*hosts, "localhost", "127.0.0.1"])),
        MAX_CONTENT_LENGTH=MAX_UPLOAD,
        SESSION_COOKIE_NAME="midistudio_session", SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        SITE_NAME=os.environ.get("MIDI_SITE_NAME", "3DMidi"),
        PROXY_MODE=os.environ.get("MIDI_PROXY_MODE", "cloudflare" if os.environ.get("MIDI_TRUST_CLOUDFLARE") == "1" else "none"),
        JOB_WAIT_SECONDS=2,
    )
    if config:
        app.config.update(config)
    if app.config["PROXY_MODE"] not in {"none", "cloudflare", "tailscale"}:
        raise ValueError("Geçersiz MIDI_PROXY_MODE.")
    store, limiter, jobs = BrowserStore(), RequestLimiter(), threading.Semaphore(1)
    app.extensions.update(midi_store=store, midi_limiter=limiter, midi_jobs=jobs)

    def owner():
        if "owner" not in session:
            session["owner"] = secrets.token_urlsafe(24)
        session.permanent = True
        return session["owner"]

    def payload():
        try:
            value = json.loads(request.get_data(cache=False) or b"{}")
        except (ValueError, UnicodeError) as exc:
            raise InputError("İstek okunamadı.") from exc
        if not isinstance(value, dict):
            raise InputError("İstek bir ayar nesnesi olmalı.")
        return value

    @contextmanager
    def job():
        if not jobs.acquire(timeout=app.config["JOB_WAIT_SECONDS"]):
            raise TooManyRequests("Sunucu başka bir MIDI işliyor. Birkaç saniye sonra yeniden dene.")
        try:
            yield
        finally:
            jobs.release()

    def selected(data):
        if not isinstance(data.get("settings"), dict) or not isinstance(data.get("id"), str):
            raise InputError("MIDI dosyanı ve ayarlarını yeniden seç.")
        who = owner()
        song = store.get("song", who, data["id"])
        if song is None:
            raise InputError("MIDI oturumu sona ermiş. Dosyanı yeniden seç.")
        profile_id = data["settings"].get("printer", "snapmaker_u1")
        if not isinstance(profile_id, str):
            raise InputError("Geçersiz yazıcı seçimi.")
        if profile_id.startswith("custom_"):
            profile = store.get("profile", who, profile_id)
            if profile is None:
                raise InputError("Bu yazıcı profili oturumunda bulunamadı; yeniden içe aktar.")
        else:
            profile = get_profile(profile_id)
        return song, data["settings"], profile

    def remember(song):
        # Bound raw input plus the decoded note objects' approximate footprint.
        key = store.put("song", owner(), song, size=song["bytes"] + len(song["notes"]) * 512)
        return jsonify(id=key, **source_summary(song))

    @app.before_request
    def guard():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and (urlsplit(origin).scheme not in {"https", "http"}
                           or urlsplit(origin).netloc.lower() != request.host.lower()):
                return jsonify(error="İstek bu siteden gelmeli."), 403
            client = request.remote_addr or "unknown"
            if app.config["PROXY_MODE"] != "none":
                try:
                    # The loopback-only origin trusts only its selected proxy's overwritten header.
                    if ipaddress.ip_address(client).is_private:
                        header = "X-Forwarded-For" if app.config["PROXY_MODE"] == "tailscale" else "CF-Connecting-IP"
                        client = str(ipaddress.ip_address(request.headers.get(header, client)))
                except ValueError:
                    pass
            if not limiter.allow(client):
                raise TooManyRequests("Çok fazla istek gönderildi. Bir dakika sonra yeniden dene.")

    @app.after_request
    def headers(response):
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": CSP, "Referrer-Policy": "same-origin"})
        if response.status_code == 429:
            response.headers["Retry-After"] = "3"
        return response

    @app.errorhandler(InputError)
    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = "Dosya çok büyük. En fazla 4 MB seçebilirsin." if error.code == 413 else error.description
        return jsonify(error=message), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Web isteği tamamlanamadı")
        return jsonify(error="İşlem tamamlanamadı. Dosyanı yeniden seçip tekrar dene."), 500

    @app.get("/api/health")
    def health():
        return jsonify(app="MIDI Studio", version="0.5", mode="public", name=app.config["SITE_NAME"])

    @app.get("/api/catalog")
    def catalog():
        from foc_acoustic import DEFAULT_BANDS
        profiles = [p for p in public_profiles() if not p["id"].startswith("custom_")]
        profiles.extend(store.values("profile", owner()))
        return jsonify(default_id="snapmaker_u1", profiles=profiles, library=public_library(),
                       foc_reference_bands=DEFAULT_BANDS,
                       runtime={"mode": "public", "name": app.config["SITE_NAME"],
                                "demo_label": "Mario ile hızlı dene",
                                "privacy": "MIDI sunucuda geçici işlenir; kalıcı dosya arşivi tutulmaz."})

    @app.post("/api/upload")
    def upload():
        filename = request.args.get("name", "melodi.mid").replace("\\", "/").rsplit("/", 1)[-1]
        if len(filename) > 240 or Path(filename).suffix.lower() not in {".mid", ".midi"}:
            raise InputError("Lütfen .mid veya .midi dosyası seç.")
        with job():
            return remember(read_midi(request.get_data(cache=False), filename))

    @app.post("/api/demo")
    def demo():
        data = payload()
        item = next((item for item in public_library() if item["id"] == data.get("id", "mario")), None)
        if item is None:
            raise InputError("Bu örnek web kitaplığında bulunamadı.")
        path = (ASSETS / item["filename"]).resolve()
        if not path.is_relative_to(ASSETS.resolve()):
            raise InputError("Geçersiz kitaplık yolu.")
        filename = ("Super Mario Theme.mid" if item["id"] == "mario" else
                    re.sub(r'[\\/:*?"<>|]', " ", item["title"]) + ".mid" if item.get("artist") else path.name)
        with job():
            song = read_midi(path.read_bytes(), filename)
            song["library_source"] = item
            return remember(song)

    @app.post("/api/profile")
    def profile():
        data = payload()
        parsed = import_profile(data.get("filename", "printer.cfg"), data.get("text"), register=False)
        store.put("profile", owner(), parsed, key=parsed["id"], size=8192)
        return jsonify(profile=parsed)

    @app.post("/api/preview")
    def preview():
        song, settings, printer = selected(payload())
        with job():
            return jsonify(summary(song, prepare(song, settings, printer=printer)))

    @app.post("/api/generate")
    def generate():
        song, settings, printer = selected(payload())
        with job():
            result = convert(song, settings, printer=printer)
            files = {kind: {"name": file["name"], "body": file["text"].encode("utf-8"),
                            "content_type": "application/json; charset=utf-8" if kind == "report" else "application/octet-stream"}
                     for kind, file in result["downloads"].items()}
            token = store.put("export", owner(), files, size=sum(len(file["body"]) for file in files.values()))
            for kind, file in result["downloads"].items():
                file["url"] = f"/api/download/{token}/{kind}/{quote(file['name'], safe='')}"
            return jsonify(result)

    @app.get("/api/download/<token>/<kind>/<filename>")
    def download(token, kind, filename):
        files = store.get("export", owner(), token)
        file = files.get(kind) if files else None
        if not file or file["name"] != filename:
            return jsonify(error="İndirme bulunamadı. Dosyayı yeniden oluştur."), 404
        return send_file(BytesIO(file["body"]), mimetype=file["content_type"],
                         as_attachment=True, download_name=file["name"], max_age=0)

    @app.get("/api/ke-slow-z-config")
    @app.get("/api/ke-slow-z-guide")
    def ke_guide():
        name = "midi_ke_slow_z.cfg" if request.path.endswith("config") else "KE_YAVAS_Z_KURULUM.txt"
        target = ASSETS.parents[1] / "reference/ke-startup" / name
        return send_file(target, as_attachment=True, download_name=name, max_age=0)

    @app.get("/")
    @app.get("/app.js")
    @app.get("/styles.css")
    @app.get("/favicon.svg")
    @app.get("/i18n.js")
    @app.get("/locales.json")
    def static_file():
        name = "index.html" if request.path == "/" else request.path[1:]
        mime = {"index.html": "text/html", "app.js": "text/javascript", "styles.css": "text/css", "favicon.svg": "image/svg+xml", "i18n.js": "text/javascript", "locales.json": "application/json"}[name]
        return send_file(STATIC / name, mimetype=mime, max_age=0)

    return app
