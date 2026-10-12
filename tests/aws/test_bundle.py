"""指定commitだけから許可済みの配布内容を収集する境界検査。"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("bundle", ROOT / "scripts/aws/bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class CollectionTests(unittest.TestCase):
    """ローカル設定や作業中のファイルを配布へ混ぜない。"""

    def setUp(self):
        """会社情報を持たない一時Gitリポジトリを用意する。"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Bundle Test")
        self.git("config", "user.email", "bundle@example.invalid")
        path = self.repo / "functions/validator/validation.py"
        path.parent.mkdir(parents=True)
        path.write_text("# 検証済みの公開ソース\n")
        (self.repo / "company.tfvars").write_text('private_setting = "not_for_delivery"')
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments):
        """一時リポジトリだけでGitを操作する。"""
        return subprocess.check_output(["git", "-C", str(self.repo), *arguments], text=True)

    def test_only_allowed_commit_bytes_are_delivered(self):
        """未コミット編集と追跡済みの個人設定をどちらも収集しない。"""
        (self.repo / "functions/validator/validation.py").write_text("# 作業中\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/private-notes.md").write_text("do not bundle")
        files = bundle.collect(self.repo, self.commit)
        self.assertEqual(
            files, {"functions/validator/validation.py": "# 検証済みの公開ソース\n".encode()}
        )


if __name__ == "__main__":
    unittest.main()


class BundleTests(unittest.TestCase):
    """配布物と検査報告を同じcommitの実体へ結び付ける。"""

    def setUp(self):
        """最小の依存なしLambdaを持つ配布用commitを用意する。"""
        CollectionTests.setUp(self)
        import io
        import json
        import zipfile

        for name in bundle.ALLOWED_FILES:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("# 公開fixture\n")
        (self.repo / "functions/aws/handler.py.lock").write_text("version = 1\npackage = []\n")
        self.git("add", ".")
        self.git("commit", "-qm", "complete fixture")
        self.commit = self.git("rev-parse", "HEAD").strip()
        source = bundle.collect(self.repo, self.commit)
        self.runtime = {
            "python": "3.14",
            "architecture": "arm64",
            "platform": "linux-arm64",
            "dependencies": [],
            "validation_sha256": bundle.sha256(source["functions/validator/validation.py"]),
            "lock_sha256": bundle.sha256(source["functions/aws/handler.py.lock"]),
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("handler.py", source["functions/aws/handler.py"])
            archive.writestr("validation.py", source["functions/validator/validation.py"])
            archive.writestr("package-manifest.json", json.dumps(self.runtime))
        self.lambda_zip = self.repo / "lambda.zip"
        self.lambda_zip.write_bytes(stream.getvalue())

    git = CollectionTests.git

    def test_report_cannot_verify_a_different_bundle(self):
        """別内容の成功報告を使って検査済みZIPを生成できない。"""
        import json

        report = self.repo / "report.json"
        report.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sourceCommit": self.commit,
                    "payloadDigest": "0" * 64,
                    "platform": "linux-arm64",
                    "deploymentVerified": False,
                    "checks": [
                        {"name": name, "status": "passed"} for name in bundle.REQUIRED_CHECKS
                    ],
                }
            )
        )
        destination = self.repo / "final.zip"
        with self.assertRaisesRegex(ValueError, "検査報告"):
            bundle.build(self.repo, self.commit, self.lambda_zip, destination, report)
        self.assertFalse(destination.exists())

    def test_manifest_and_verified_bundle_preserve_the_payload(self):
        """検査前後のpayloadが一致し、自己hash以外の検証情報を配布する。"""
        import json
        import zipfile

        draft = self.repo / "draft.zip"
        result = bundle.build(self.repo, self.commit, self.lambda_zip, draft)
        with zipfile.ZipFile(draft) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["verification"]["status"], "not_checked")
            self.assertEqual(
                archive.read("functions/validator/validation.py"),
                "# 検証済みの公開ソース\n".encode(),
            )
            self.assertNotIn("company.tfvars", archive.namelist())
            for item in manifest["files"]:
                self.assertEqual(bundle.sha256(archive.read(item["path"])), item["sha256"])
        report = self.repo / "report.json"
        report.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "sourceCommit": self.commit,
                    "payloadDigest": result["payloadDigest"],
                    "platform": "linux-arm64",
                    "deploymentVerified": False,
                    "checks": [
                        {"name": name, "status": "passed"} for name in bundle.REQUIRED_CHECKS
                    ],
                }
            )
        )
        final = self.repo / "final.zip"
        bundle.build(self.repo, self.commit, self.lambda_zip, final, report)
        with zipfile.ZipFile(final) as archive:
            verified = json.loads(archive.read("manifest.json"))
            self.assertEqual(verified["files"], manifest["files"])
            self.assertEqual(verified["verification"]["status"], "passed")
            self.assertIs(verified["verification"]["deploymentVerified"], False)

    def test_mismatched_lambda_is_rejected(self):
        """配置ZIPのコードが指定commitと違えば生成を止める。"""
        import zipfile

        with zipfile.ZipFile(self.lambda_zip, "w") as archive:
            import json

            archive.writestr("handler.py", "# 別版\n")
            archive.writestr("validation.py", "# 別版\n")
            archive.writestr("package-manifest.json", json.dumps(self.runtime))
        with self.assertRaisesRegex(ValueError, "コード"):
            bundle.build(self.repo, self.commit, self.lambda_zip, self.repo / "result.zip")

    def test_existing_destination_is_untouched(self):
        """既存の出力を上書きしない。"""
        destination = self.repo / "existing.zip"
        destination.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            bundle.build(self.repo, self.commit, self.lambda_zip, destination)
        self.assertEqual(destination.read_bytes(), b"keep")

    def test_competing_output_survives(self):
        """存在確認直後に別処理が出力を作った場合もその実体を保護する。"""
        from unittest.mock import patch

        destination = self.repo / "competing.zip"
        original = Path.open

        def competing_open(path, mode="r", *args, **kwargs):
            """新規作成要求の直前に競合する出力を生成する。"""
            if path == destination and mode == "xb":
                with original(path, "wb") as output:
                    output.write(b"other process")
            return original(path, mode, *args, **kwargs)

        with patch.object(Path, "open", competing_open), self.assertRaises(FileExistsError):
            bundle.build(self.repo, self.commit, self.lambda_zip, destination)
        self.assertEqual(destination.read_bytes(), b"other process")

    def test_ambiguous_and_file_child_paths_are_rejected(self):
        """展開先が曖昧になるパスや通常fileの子を配置しない。"""
        import zipfile

        original = self.lambda_zip.read_bytes()
        for unsafe in ["boto3/./extra.txt", "boto3//extra.txt", "handler.py/extra.txt"]:
            with self.subTest(path=unsafe):
                self.lambda_zip.write_bytes(original)
                with zipfile.ZipFile(self.lambda_zip, "a") as archive:
                    archive.writestr(unsafe, "extra")
                with self.assertRaises(ValueError):
                    bundle.build(self.repo, self.commit, self.lambda_zip, self.repo / "result.zip")

    def test_corrupt_sdk_entry_is_rejected(self):
        """外部SDKの破損もdraft生成前に拒否する。"""
        import io
        import struct
        import zipfile

        with zipfile.ZipFile(self.lambda_zip, "a") as archive:
            archive.writestr("boto3/__init__.py", b"hello")
        content = bytearray(self.lambda_zip.read_bytes())
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            position = archive.getinfo("boto3/__init__.py").header_offset
        name_size, extra_size = struct.unpack_from("<HH", content, position + 26)
        content[position + 30 + name_size + extra_size] ^= 1
        self.lambda_zip.write_bytes(content)
        with self.assertRaisesRegex(ValueError, "CRC"):
            bundle.build(self.repo, self.commit, self.lambda_zip, self.repo / "result.zip")
