"""Review/apply the Raspberry Pi memory-controller boot flags, with a backup."""
import argparse
from datetime import datetime, timezone
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def memory_cmdline(original):
    if len(original.strip().splitlines()) != 1:
        raise ValueError("Boot komut satırı tek satır olmalı; dosya değiştirilmedi.")
    result = []
    for token in original.split():
        if token.startswith("cgroup_memory="):
            continue
        if token.startswith("cgroup_disable="):
            remaining = [name for name in token.split("=", 1)[1].split(",") if name != "memory"]
            if remaining:
                result.append("cgroup_disable=" + ",".join(remaining))
            continue
        result.append(token)
    if not any(token.startswith("cgroup_enable=") and "memory" in token.split("=", 1)[1].split(",") for token in result):
        result.append("cgroup_enable=memory")
    result.append("cgroup_memory=1")
    return " ".join(result) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reboot", action="store_true")
    args = parser.parse_args()
    path = Path("/boot/firmware/cmdline.txt")
    before = path.read_text(encoding="utf-8")
    after = memory_cmdline(before)
    print("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                     fromfile="cmdline.txt (önce)", tofile="cmdline.txt (sonra)")))
    if not args.apply:
        print("Yalnızca önizleme. Uygulamak için --apply; yeniden başlatmak için ayrıca --reboot.")
        return
    if os.geteuid() != 0:
        raise SystemExit("Bu boot ayarı sudo ile çalıştırılmalı; dosya değiştirilmedi.")
    if before != after:
        backup = path.with_name("cmdline.3dmidi-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".bak")
        shutil.copy2(path, backup)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="cmdline.3dmidi-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(after.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
        print("Boot yedeği:", backup)
    print("Bellek kontrolcüsü bir sonraki açılışta etkinleşecek.")
    if args.reboot:
        subprocess.run(["systemctl", "reboot"], check=True)


if __name__ == "__main__":
    main()
