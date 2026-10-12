"""配布物の改変・脱出・資格情報混入と対象runtime判定を検査する。"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).resolve().parents[2] / "scripts/aws/check_bundle.py"
spec = importlib.util.spec_from_file_location("check_bundle", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CheckerBoundaryTests(unittest.TestCase):
    """外部の配布物と実行環境を公開境界から扱う。"""

    def fixture(self, root):
        """abcの既知hashを用いた小さな配布物を作る。"""
        root.mkdir()
        (root / "data").write_bytes(b"abc")
        (root / "checksums.sha256").write_bytes(b"")
        (root / "manifest.sha256").write_bytes(b"")
        manifest = {
            "schemaVersion": 1,
            "source": {"commit": "0" * 40},
            "generator": {"name": "scripts/aws/bundle.py", "version": 1},
            "runtimes": {
                "glue": {"version": "5.1", "spark": "3.5.6", "python": "3.11"},
                "lambda": {"python": "3.14", "architecture": "arm64", "platform": "linux-arm64"},
            },
            "files": [
                {
                    "path": "checksums.sha256",
                    "size": 0,
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                },
                {
                    "path": "data",
                    "size": 3,
                    "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                },
            ],
        }
        (root / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def test_traversal_rejected(self):
        """manifestの相対パスで展開先を脱出できない。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            manifest = self.fixture(root)
            manifest["files"][1]["path"] = "../escape"
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(module.CheckFailure, "UNSAFE_FILE_PATH"):
                module.verify_payload(root)

    def test_modified_data_rejected(self):
        """サイズが同じでもデータの改変を拒否する。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            self.fixture(root)
            (root / "data").write_bytes(b"abd")
            with self.assertRaisesRegex(module.CheckFailure, "FILE_INTEGRITY_MISMATCH"):
                module.verify_payload(root)

    def test_extra_file_rejected(self):
        """追跡外の個人ファイルを検査対象へ混ぜない。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            self.fixture(root)
            (root / "personal").write_text("not-in-manifest")
            with self.assertRaisesRegex(module.CheckFailure, "UNLISTED_OR_MISSING_FILE"):
                module.verify_payload(root)

    def test_environment_isolated(self):
        """個人の資格情報・profile・provider cacheをサブプロセスへ渡さない。"""
        with tempfile.TemporaryDirectory() as temp:
            env_root = Path(temp)
            with patch.dict(
                os.environ,
                {
                    "AWS_ACCESS_KEY_ID": "must-not-survive",
                    "AWS_PROFILE": "personal",
                    "TF_PLUGIN_CACHE_DIR": "/personal/cache",
                },
            ):
                environment = module.isolated_environment(env_root)
            self.assertNotIn("AWS_ACCESS_KEY_ID", environment)
            self.assertNotIn("AWS_PROFILE", environment)
            self.assertNotIn("TF_PLUGIN_CACHE_DIR", environment)
            self.assertEqual(environment["HOME"], str(env_root / "home"))
            self.assertEqual(environment["AWS_EC2_METADATA_DISABLED"], "true")

    def test_native_mac_never_reports_linux_passed(self):
        """非Linuxでは失敗証跡だけを外部へ保存し、原本を変更しない。"""
        if module.platform.system() == "Linux":
            self.skipTest("nonLinux gate test")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            self.fixture(root)
            report = Path(temp) / "report.json"
            result = subprocess.run(
                [sys.executable, str(script), str(root), "--report", str(report)],
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1)
            evidence = json.loads(report.read_text())
            self.assertFalse(evidence["deploymentVerified"])
            checks = {item["name"]: item for item in evidence["checks"]}
            self.assertEqual(checks["manifest"]["status"], "passed")
            self.assertEqual(checks["lambda_import"]["status"], "failed")
            self.assertEqual(checks["terraform_init"]["status"], "not_checked")
            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["checksums.sha256", "data", "manifest.json", "manifest.sha256"],
            )

    def test_matching_host_cpu_reports_the_bundle_platform(self):
        """CPUごとの検査成功記録を対象Lambdaのplatformへ結び付ける。"""
        for architecture, machine in [("arm64", "aarch64"), ("x86_64", "x86_64")]:
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "bundle"
                manifest = self.fixture(root)
                manifest["runtimes"]["lambda"].update(
                    {
                        "architecture": architecture,
                        "platform": "linux-" + architecture,
                    }
                )
                (root / "manifest.json").write_text(json.dumps(manifest))
                report = Path(temp) / "report.json"
                with (
                    patch.object(module.platform, "system", return_value="Linux"),
                    patch.object(module.platform, "machine", return_value=machine),
                    patch.object(module.sys, "version_info", (3, 14)),
                    patch.object(module, "extract_package"),
                    patch.object(module, "command"),
                ):
                    self.assertTrue(module.inspect_bundle(root, report))
                evidence = json.loads(report.read_text())
                self.assertEqual(evidence["platform"], "linux-" + architecture)
                self.assertTrue(all(c["status"] == "passed" for c in evidence["checks"]))

    def test_opposite_host_cpu_does_not_report_success(self):
        """異なるCPU上でのimport検査を成功扱いしない。"""
        for architecture, machine in [("arm64", "x86_64"), ("x86_64", "aarch64")]:
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "bundle"
                manifest = self.fixture(root)
                manifest["runtimes"]["lambda"].update(
                    {
                        "architecture": architecture,
                        "platform": "linux-" + architecture,
                    }
                )
                (root / "manifest.json").write_text(json.dumps(manifest))
                report = Path(temp) / "report.json"
                with (
                    patch.object(module.platform, "system", return_value="Linux"),
                    patch.object(module.platform, "machine", return_value=machine),
                    patch.object(module.sys, "version_info", (3, 14)),
                    patch.object(module, "extract_package") as extract,
                ):
                    self.assertFalse(module.inspect_bundle(root, report))
                    extract.assert_not_called()
                evidence = json.loads(report.read_text())
                self.assertEqual(evidence["platform"], "linux-" + architecture)
                self.assertEqual(evidence["checks"][1]["status"], "failed")

    def test_both_architectures_can_extract_matching_package(self):
        """ZIPとmanifestに一致するCPUを固定値で排除しない。"""
        for architecture in ("arm64", "x86_64"):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "functions/aws").mkdir(parents=True)
                (root / "functions/validator").mkdir(parents=True)
                (root / "dist/aws").mkdir(parents=True)
                (root / "functions/aws/handler.py").write_text("# handler")
                validation = root / "functions/validator/validation.py"
                validation.write_text("# validation")
                lock = root / "functions/aws/handler.py.lock"
                lock.write_text("package = []")
                runtime = {
                    "python": "3.14",
                    "architecture": architecture,
                    "platform": "linux-" + architecture,
                    "dependencies": [],
                    "validation_sha256": module.sha256(validation),
                    "lock_sha256": module.sha256(lock),
                }
                with zipfile.ZipFile(root / "dist/aws/lambda.zip", "w") as archive:
                    archive.writestr("handler.py", "# handler")
                    archive.writestr("validation.py", "# validation")
                    archive.writestr("package-manifest.json", json.dumps(runtime))
                target = root / "extracted"
                module.extract_package(root, target, {"runtimes": {"lambda": runtime}})
                self.assertEqual((target / "handler.py").read_text(), "# handler")

    def test_zip_traversal_or_symlink_is_rejected_before_extraction(self):
        """Lambda ZIPの脱出パスやsymlinkを展開前に拒否する。"""
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "dist/aws").mkdir(parents=True)
                with zipfile.ZipFile(root / "dist/aws/lambda.zip", "w") as archive:
                    info = zipfile.ZipInfo("linked" if linked else "../escape")
                    if linked:
                        info.create_system = 3
                        info.external_attr = 0o120777 << 16
                    archive.writestr(info, "outside")
                target = root / "extracted"
                with self.assertRaisesRegex(module.CheckFailure, "UNSAFE_ZIP_ENTRY"):
                    module.extract_package(root, target, {})
                self.assertFalse(target.exists())
                self.assertFalse((root.parent / "escape").exists())


if __name__ == "__main__":
    unittest.main()
