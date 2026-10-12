"""配布キットの改変・欠落を公開CLIで検出する。"""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class VerifyBundleTests(unittest.TestCase):
    """同じ配布物をBashと利用可能なPowerShellで検証する。"""

    def setUp(self):
        """自己参照しないhash階層を持つ最小配布物を作る。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name)
        (self.bundle / "payload").mkdir()
        payload = self.bundle / "payload/data.txt"
        payload.write_bytes("CSV確認用\n".encode())
        digest = hashlib.sha256(payload.read_bytes()).hexdigest()
        (self.bundle / "checksums.sha256").write_text(f"{digest}  payload/data.txt\n")
        files = []
        for path in [payload, self.bundle / "checksums.sha256"]:
            files.append(
                {
                    "path": path.relative_to(self.bundle).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        (self.bundle / "manifest.json").write_text(
            json.dumps({"schemaVersion": 1, "source": {"commit": "abc"}, "files": files}),
            encoding="utf-8",
        )
        self.refresh_manifest_hash()

    def refresh_manifest_hash(self):
        """manifestとpayload一覧のhashを固定する。"""
        (self.bundle / "manifest.sha256").write_text(
            "".join(
                f"{hashlib.sha256((self.bundle / name).read_bytes()).hexdigest()}  {name}\n"
                for name in ["manifest.json", "checksums.sha256"]
            )
        )

    def verify(self, success):
        """各CLIの終了codeで整合性判定を確認する。"""
        commands = [["bash", str(ROOT / "scripts/aws/verify-bundle.sh"), str(self.bundle)]]
        if shutil.which("pwsh"):
            commands.append(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/aws/verify-bundle.ps1"),
                    "-BundleRoot",
                    str(self.bundle),
                ]
            )
        for command in commands:
            with self.subTest(command=command[0]):
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_complete(self):
        self.verify(True)

    def test_unlisted_file(self):
        (self.bundle / "unexpected.txt").write_bytes(b"extra")
        self.verify(False)

    def test_missing(self):
        (self.bundle / "payload/data.txt").unlink()
        self.verify(False)

    def test_modified(self):
        (self.bundle / "payload/data.txt").write_bytes(b"changed")
        self.verify(False)

    def test_modified_manifest(self):
        (self.bundle / "manifest.json").write_bytes(b"{}")
        self.verify(False)

    def test_traversal(self):
        (self.bundle / "checksums.sha256").write_text("0" * 64 + "  ../outside\n")
        self.refresh_manifest_hash()
        self.verify(False)

    def test_symlink(self):
        (self.bundle / "payload/data.txt").unlink()
        (self.bundle / "payload/data.txt").symlink_to(self.bundle / "manifest.json")
        self.verify(False)

    def test_duplicate_payload(self):
        checksum = self.bundle / "checksums.sha256"
        checksum.write_text(checksum.read_text() * 2)
        self.refresh_manifest_hash()
        self.verify(False)

    def test_linked_directory(self):
        (self.bundle / "payload").rename(self.bundle / "actual")
        (self.bundle / "payload").symlink_to(self.bundle / "actual", target_is_directory=True)
        self.verify(False)

    def test_linked_hash_list(self):
        (self.bundle / "checksums.sha256").rename(self.bundle / "actual.sha256")
        (self.bundle / "checksums.sha256").symlink_to(self.bundle / "actual.sha256")
        self.verify(False)

    def test_absolute_path(self):
        (self.bundle / "checksums.sha256").write_text("0" * 64 + "  /outside\n")
        self.refresh_manifest_hash()
        self.verify(False)

    def test_extra_manifest_hash_entry(self):
        with (self.bundle / "manifest.sha256").open("a") as output:
            output.write("0" * 64 + "  payload/data.txt\n")
        self.verify(False)


if __name__ == "__main__":
    unittest.main()
