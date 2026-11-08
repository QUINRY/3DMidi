"""Boot flag edits, managed cron preservation and private backup scope."""
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
from enable_memory import memory_cmdline
from manage import backup_project, build_crontab


class DeploymentTests(unittest.TestCase):
    def test_memory_flags_preserve_boot_parameters_and_are_idempotent(self):
        original = "console=serial0,115200 root=PARTUUID=abc rootfstype=ext4 rootwait quiet\n"
        changed = memory_cmdline(original)
        self.assertEqual(changed, original.strip() + " cgroup_enable=memory cgroup_memory=1\n")
        self.assertEqual(memory_cmdline(changed), changed)

    def test_memory_only_is_removed_from_disabled_controllers(self):
        result = memory_cmdline("root=abc cgroup_disable=memory,hugetlb cgroup_memory=0 cgroup_enable=cpu\n")
        self.assertIn("cgroup_disable=hugetlb", result)
        self.assertIn("cgroup_enable=cpu", result)
        self.assertNotIn("cgroup_memory=0", result)
        self.assertEqual(result.count("cgroup_memory=1"), 1)

    def test_multiple_boot_lines_are_rejected(self):
        with self.assertRaises(ValueError):
            memory_cmdline("root=abc\ncgroup_enable=memory\n")

    def test_cron_is_idempotent_and_preserves_unrelated_jobs(self):
        existing = "MAILTO=\n15 4 * * * /home/quinry/other-job\n"
        result = build_crontab(existing, Path("/home/quinry/3dmidi"))
        self.assertIn(existing.strip(), result)
        self.assertEqual(result.count("@reboot"), 1)
        self.assertEqual(result.count("*/2 * * * *"), 1)
        self.assertEqual(build_crontab(result, Path("/home/quinry/3dmidi")), result)

    def test_backups_exclude_secrets_logs_and_their_own_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("app/web.py", "deploy/.env", "deploy/secrets/token", "deploy/.logs/debug", "__pycache__/code.pyc"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            archive = backup_project(root)
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(set(package.namelist()), {"app/web.py", "deploy/.env"})


if __name__ == "__main__":
    unittest.main()
