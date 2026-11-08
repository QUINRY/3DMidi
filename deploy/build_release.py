"""Build the web release with the complete selected MIDI catalog and its files."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from web import public_library


def main():
    folder = ROOT / "output/raspberry-pi"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / ("3dmidi-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".zip")
    library = public_library()
    included = set()
    for base in (ROOT / "app", ROOT / "tools", ROOT / "deploy"):
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(ROOT)
            if (any(part in {"__pycache__", ".logs", "popular", "secrets", "backups"} for part in relative.parts)
                    or path.suffix == ".pyc" or path.name == ".env"
                    or path.name in {"midi_library.json", "popular_midi_sources.json", "mario.mid", "operations-state.json", "operations.lock", "preview-url.txt", "public-url.txt", "maintenance.flag", "STATUS.txt"}):
                continue
            included.add(relative)
    included.add(Path("requirements.txt"))
    included.add(Path(".dockerignore"))
    assets = (ROOT / "app/assets").resolve()
    for item in library:
        path = (assets / item["filename"]).resolve()
        if not path.is_relative_to(assets) or not path.is_file() or path.is_symlink():
            raise ValueError("Kitaplık dosyası eksik veya geçersiz: " + item["filename"])
        included.add(path.relative_to(ROOT))
    # Keep the original source/rights records alongside the selected files.
    for name in ("app/popular_midi_sources.json", "app/assets/library/popular/SOURCES_AND_LICENSES.json"):
        if (ROOT / name).is_file():
            included.add(Path(name))
    for name in ("midi_ke_slow_z.cfg", "KE_YAVAS_Z_KURULUM.txt"):
        included.add(Path("reference/ke-startup") / name)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "public_midi_ids": [item["id"] for item in library], "sha256": {}}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(included):
            data = (ROOT / relative).read_bytes()
            archive.writestr(relative.as_posix(), data)
            manifest["sha256"][relative.as_posix()] = hashlib.sha256(data).hexdigest()
        data = (json.dumps({"version": 1, "items": library}, ensure_ascii=False, indent=2) + "\n").encode()
        archive.writestr("app/midi_library.json", data)
        manifest["sha256"]["app/midi_library.json"] = hashlib.sha256(data).hexdigest()
        archive.writestr("release-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".sha256").write_text(digest + "  " + destination.name + "\n", encoding="ascii")
    print(json.dumps({"archive": str(destination), "sha256": digest, "files": len(manifest["sha256"]),
                      "public_midis": len(library), "bytes": destination.stat().st_size}))


if __name__ == "__main__":
    main()
