"""Start a temporary HTTPS test URL and allow only that exact hostname."""
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "deploy/.env"


def main():
    if not ENV.exists():
        ENV.write_text("MIDI_ALLOWED_HOSTS=localhost,127.0.0.1\n", encoding="utf-8")
    compose = ["docker", "compose", "--env-file", str(ENV), "-f", str(ROOT / "deploy/compose.yaml")]
    subprocess.run([*compose, "--profile", "preview", "up", "-d", "web", "preview"], check=True)
    deadline = time.monotonic() + 90
    hostname = None
    while time.monotonic() < deadline:
        result = subprocess.run([*compose, "logs", "--no-color", "--tail", "80", "preview"],
                                capture_output=True, text=True, check=True)
        found = re.findall(r"https://([a-z0-9-]+\.trycloudflare\.com)", result.stdout)
        if found:
            hostname = found[-1]
            break
        time.sleep(1)
    if hostname is None:
        raise SystemExit("Tünel adresi henüz oluşmadı; docker compose logs preview ile bağlantıyı kontrol et.")
    lines = [line for line in ENV.read_text(encoding="utf-8").splitlines() if not line.startswith("MIDI_ALLOWED_HOSTS=")]
    lines.append("MIDI_ALLOWED_HOSTS=localhost,127.0.0.1," + hostname)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run([*compose, "up", "-d", "--no-deps", "web"], check=True)
    (ROOT / "deploy/preview-url.txt").write_text("https://" + hostname + "\n", encoding="ascii")
    print("https://" + hostname, flush=True)


if __name__ == "__main__":
    main()
