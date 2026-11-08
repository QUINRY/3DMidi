"""Own-project recovery, private configuration backups and status for 3DMidi."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
LOGS = DEPLOY / ".logs"
STATE = DEPLOY / "operations-state.json"
BEGIN, END = "# BEGIN 3DMIDI MANAGED", "# END 3DMIDI MANAGED"


def run(args, *, check=True, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=check, timeout=45, **kwargs)


def compose(*args):
    return run(["docker", "compose", "--env-file", str(DEPLOY / ".env"),
                "-f", str(DEPLOY / "compose.yaml"), *args])


def save_state(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATE)


def build_crontab(original, root):
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError("Yönetilen cron bloğu belirsiz; mevcut işler değiştirilmedi.")
    if BEGIN in original:
        start, rest = original.split(BEGIN, 1)
        _, finish = rest.split(END, 1)
        original = start.rstrip() + "\n" + finish.lstrip("\n")
    script = shlex.quote(str(root / "deploy/manage.py"))
    output = shlex.quote(str(root / "deploy/.logs/operations.log"))
    command = f"/usr/bin/python3 {script} reconcile >> {output} 2>&1"
    return original.rstrip() + f"\n{BEGIN}\n@reboot {command}\n*/2 * * * * {command}\n{END}\n"


def backup_project(root=ROOT):
    folder = root / "backups"
    folder.mkdir(mode=0o700, exist_ok=True)
    filename = folder / ("3dmidi-config-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".zip")
    ignored = {"backups", ".logs", "__pycache__", "secrets", ".git", ".venv"}
    with zipfile.ZipFile(filename, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (not path.is_file() or path.is_symlink() or set(relative.parts) & ignored
                    or path.suffix in {".pyc", ".lock", ".tmp"}):
                continue
            archive.write(path, relative.as_posix())
    filename.chmod(0o600)
    for old in sorted(folder.glob("3dmidi-config-*.zip"))[:-7]:
        old.unlink()
    return filename


def ensure_funnel():
    status = json.loads(run(["tailscale", "status", "--json"]).stdout)
    if status.get("BackendState") != "Running":
        raise RuntimeError("Tailscale bağlantısı çevrimiçi değil.")
    hostname = status["Self"]["DNSName"].rstrip(".")
    address = hostname + ":443"
    current = json.loads(run(["tailscale", "funnel", "status", "--json"]).stdout)
    handler = current.get("Web", {}).get(address, {}).get("Handlers", {}).get("/", {})
    if handler and handler.get("Proxy") != "http://127.0.0.1:8765":
        raise RuntimeError("443 portunda başka bir Tailscale servisi var; değiştirilmedi.")
    if not current.get("AllowFunnel", {}).get(address) or not handler:
        run(["tailscale", "funnel", "--bg", "--yes", "http://127.0.0.1:8765"])
    return "https://" + hostname


def health():
    with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=4) as response:
        result = json.load(response)
    if result.get("app") != "MIDI Studio" or result.get("mode") != "public":
        raise RuntimeError("8765 portundaki servis beklenen 3DMidi uygulaması değil.")
    return result


def reconcile():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    if (DEPLOY / "maintenance.flag").exists():
        state.update(maintenance=True, checked_at=now.isoformat())
        save_state(state)
        return state
    inspected = run(["docker", "inspect", "3dmidi-web-1"], check=False)
    container = json.loads(inspected.stdout)[0] if inspected.returncode == 0 else None
    if container is None or not container["State"]["Running"]:
        compose("up", "-d", "--no-build", "--no-deps", "web")
    try:
        health()
        state["failed_health_checks"] = 0
        state["healthy"] = True
    except (OSError, ValueError, RuntimeError):
        state["healthy"] = False
        state["failed_health_checks"] = state.get("failed_health_checks", 0) + 1
        if state["failed_health_checks"] >= 3:
            run(["docker", "restart", "3dmidi-web-1"])
            state.update(last_restart=now.isoformat(), failed_health_checks=0)
            for _ in range(10):
                time.sleep(1)
                try:
                    health()
                    state["healthy"] = True
                    break
                except (OSError, ValueError, RuntimeError):
                    pass
    state["public_url"] = ensure_funnel()
    (DEPLOY / "public-url.txt").write_text(state["public_url"] + "\n", encoding="ascii")
    info = json.loads(run(["docker", "info", "--format", "{{json .}}"]).stdout)
    state["memory_limit_supported"] = bool(info.get("MemoryLimit"))
    if now.hour >= 3 and state.get("backup_date") != now.date().isoformat():
        state.update(last_backup=str(backup_project()), backup_date=now.date().isoformat())
    state.update(maintenance=False, checked_at=now.isoformat())
    save_state(state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "reconcile", "status", "backup", "maintenance"])
    parser.add_argument("value", nargs="?", choices=["on", "off"])
    args = parser.parse_args()
    LOGS.mkdir(mode=0o700, exist_ok=True)
    # Unix advisory lock also prevents cron overlapping a manual repair.
    import fcntl
    with (DEPLOY / "operations.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        log = LOGS / "operations.log"
        if log.exists() and log.stat().st_size > 1024 * 1024:
            log.replace(LOGS / "operations.previous.log")
        if args.command == "backup":
            print(backup_project())
            return
        if args.command == "maintenance":
            if args.value is None:
                raise SystemExit("maintenance on veya maintenance off kullan.")
            flag = DEPLOY / "maintenance.flag"
            if args.value == "on":
                flag.touch()
                print("Bakım modu açık; otomatik onarım durduruldu.")
                return
            flag.unlink(missing_ok=True)
        if args.command == "install":
            previous = run(["crontab", "-l"], check=False)
            if previous.returncode and "no crontab" not in previous.stderr.lower():
                raise RuntimeError("Kullanıcının cron kayıtları okunamadı.")
            original = previous.stdout if previous.returncode == 0 else ""
            (LOGS / "crontab-before.txt").write_text(original, encoding="utf-8")
            run(["crontab", "-"], input=build_crontab(original, ROOT))
        if args.command == "status":
            print(STATE.read_text() if STATE.exists() else "Henüz kontrol kaydı yok.")
            return
        print(json.dumps(reconcile(), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("3DMidi bakım hatası:", str(error), file=sys.stderr)
        raise SystemExit(1)
