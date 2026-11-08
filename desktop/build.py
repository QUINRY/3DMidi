"""Build and verify the portable Windows application from the repository root."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop import VERSION


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows executable must be built on Windows.")
    out = ROOT / "output/windows"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(out), "--workpath", str(out / "build"),
                    str(ROOT / "desktop/3dmidi.spec")], cwd=ROOT, check=True)
    executable = out / "3DMidi.exe"
    report = out / "bundle-check.json"
    report.unlink(missing_ok=True)
    subprocess.run([str(executable), "--self-test", str(report)], cwd=out, check=True, timeout=180)
    checked = json.loads(report.read_text(encoding="utf-8"))
    if not checked.get("ok") or not checked.get("frozen") or checked.get("library") != 129:
        raise RuntimeError("Bundled app verification failed: " + str(checked))
    notes = ROOT / "desktop/WINDOWS_KULLANIM.txt"
    archive = out / f"3DMidi-{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in (executable, notes, ROOT / "LICENSE", ROOT / "THIRD_PARTY_NOTICES.md"):
            zipped.write(path, path.name)
    digests = []
    for path in (executable, archive):
        digests.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
    (out / "SHA256SUMS.txt").write_text("\n".join(digests) + "\n", encoding="ascii")
    print(json.dumps({"version": VERSION, "executable": str(executable), "bytes": executable.stat().st_size,
                      "archive": str(archive), "self_test": checked}, ensure_ascii=False))


if __name__ == "__main__":
    main()
