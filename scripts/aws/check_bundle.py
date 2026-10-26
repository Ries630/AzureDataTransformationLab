# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""空ディレクトリへ展開したAWS配布物を資格情報なしで検査し、外部へ証跡を保存する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from importlib.metadata import distributions
from pathlib import Path, PurePosixPath

MACHINES = {"arm64": {"aarch64", "arm64"}, "x86_64": {"x86_64", "AMD64"}}

CHECK_NAMES = (
    "manifest",
    "lambda_import",
    "samples",
    "terraform_init",
    "terraform_validate",
    "bash_checksums",
    "powershell_checksums",
)


class CheckFailure(RuntimeError):
    """配布物または検査環境が受入条件を満たさないことを表す。"""


def canonical(value: object) -> bytes:
    """生成器と同じJSON表現で検査対象を識別する。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def safe_path(root: Path, name: str) -> Path:
    """脱出・曖昧なパス・symlinkを拒否して通常ファイルだけを返す。"""
    if (
        not isinstance(name, str)
        or not name
        or any(character in name for character in "\\:|")
        or any(ord(character) < 32 for character in name)
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise CheckFailure("UNSAFE_FILE_PATH")
    current = root
    for part in PurePosixPath(name).parts:
        current /= part
        if current.is_symlink():
            raise CheckFailure("LINKED_FILE_PATH")
    if not current.exists() or not stat.S_ISREG(current.stat().st_mode):
        raise CheckFailure("NOT_REGULAR_FILE")
    return current


def sha256(path: Path) -> str:
    """ファイルを有界の読み取りでhash化する。"""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_payload(root: Path) -> dict:
    """manifestの全件・サイズ・hashと展開済み実体の完全一致を確かめる。"""
    manifest = json.loads(safe_path(root, "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1 or not isinstance(manifest.get("files"), list):
        raise CheckFailure("INVALID_MANIFEST_SCHEMA")
    commit = manifest.get("source", {}).get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise CheckFailure("INVALID_SOURCE_COMMIT")
    if manifest.get("generator") != {"name": "scripts/aws/bundle.py", "version": 1}:
        raise CheckFailure("UNSUPPORTED_GENERATOR")
    if manifest.get("runtimes", {}).get("glue") != {
        "version": "5.1",
        "spark": "3.5.6",
        "python": "3.11",
    }:
        raise CheckFailure("GLUE_RUNTIME_MISMATCH")
    names = []
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise CheckFailure("INVALID_FILE_RECORD")
        path = safe_path(root, item["path"])
        if item["path"] in {"manifest.json", "manifest.sha256"} or item["path"] in names:
            raise CheckFailure("DUPLICATE_OR_CONTROL_FILE")
        if (
            type(item["size"]) is not int
            or item["size"] < 0
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        ):
            raise CheckFailure("INVALID_FILE_METADATA")
        if path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise CheckFailure("FILE_INTEGRITY_MISMATCH")
        names.append(item["path"])
    if not names or names != sorted(names) or "checksums.sha256" not in names:
        raise CheckFailure("INVALID_FILE_INVENTORY")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or (not path.is_dir() and not stat.S_ISREG(path.stat().st_mode)):
            raise CheckFailure("LINKED_OR_SPECIAL_FILE")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != set(names) | {"manifest.json", "manifest.sha256"}:
        raise CheckFailure("UNLISTED_OR_MISSING_FILE")
    return manifest


def isolated_environment(temporary: Path) -> dict[str, str]:
    """個人HOME・cache・認証設定を継承しないサブプロセス環境を作る。"""
    home = temporary / "home"
    home.mkdir()
    configuration = temporary / "terraform.rc"
    configuration.write_text("provider_installation {\n  direct {}\n}\n", encoding="utf-8")
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "LANG": "C.UTF-8",
        "UV_CACHE_DIR": str(temporary / "uv-cache"),
        "XDG_CACHE_HOME": str(temporary / "cache"),
        "XDG_CONFIG_HOME": str(temporary / "config"),
        "TF_CLI_CONFIG_FILE": str(configuration),
        "TF_DATA_DIR": str(temporary / "terraform-data"),
        "TF_INPUT": "0",
        "TF_IN_AUTOMATION": "1",
        "CHECKPOINT_DISABLE": "1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_DEFAULT_REGION": "ap-northeast-1",
        "AWS_CONFIG_FILE": str(home / "absent-aws-config"),
        "AWS_SHARED_CREDENTIALS_FILE": str(home / "absent-aws-credentials"),
    }


def command(arguments: list[str], cwd: Path, environment: dict[str, str]) -> None:
    """外部ツールの結果を判定し、stdoutや個人情報をreportに取り込まない。"""
    result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise CheckFailure("COMMAND_FAILED:" + Path(arguments[0]).name)


def lambda_runtime(manifest: dict) -> dict:
    """CPUとplatformが対応するサポート済みLambda runtimeを返す。"""
    runtime = manifest["runtimes"]["lambda"]
    architecture = runtime.get("architecture")
    if (
        runtime.get("python") != "3.14"
        or architecture not in MACHINES
        or runtime.get("platform") != "linux-" + architecture
    ):
        raise CheckFailure("PACKAGE_RUNTIME_MISMATCH")
    return runtime


def extract_package(root: Path, target: Path, manifest: dict) -> None:
    """ZIP内の脱出・リンク・重複を拒否し、対象runtimeと原本hashを照合する。"""
    package = safe_path(root, "dist/aws/lambda.zip")
    with zipfile.ZipFile(package) as archive:
        names = set()
        total = 0
        for item in archive.infolist():
            name = item.filename.rstrip("/") if item.is_dir() else item.filename
            if (
                not name
                or name.startswith("/")
                or "\\" in name
                or ":" in name
                or any(ord(character) < 32 for character in name)
                or any(part in ("", ".", "..") for part in name.split("/"))
                or name in names
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise CheckFailure("UNSAFE_ZIP_ENTRY")
            names.add(name)
            total += item.file_size
            if total > 250 * 1024 * 1024:
                raise CheckFailure("ZIP_TOO_LARGE")
        runtime = json.loads(archive.read("package-manifest.json"))
        if runtime != lambda_runtime(manifest):
            raise CheckFailure("PACKAGE_RUNTIME_MISMATCH")
        validation = safe_path(root, "functions/validator/validation.py")
        lock = safe_path(root, "uv.lock")
        if (
            runtime.get("validation_sha256") != sha256(validation)
            or hashlib.sha256(archive.read("validation.py")).hexdigest() != sha256(validation)
            or runtime.get("lock_sha256") != sha256(lock)
        ):
            raise CheckFailure("PACKAGE_SOURCE_MISMATCH")
        for source in (root / "functions/aws").glob("*.py"):
            safe_path(root, source.relative_to(root).as_posix())
            if hashlib.sha256(archive.read(source.name)).hexdigest() != sha256(source):
                raise CheckFailure("PACKAGE_CODE_MISMATCH")
        archive.extractall(target)
    installed = {
        re.sub(r"[-_.]+", "-", item.metadata["Name"]).lower(): item.version
        for item in distributions(path=[str(target)])
    }
    declared = {
        re.sub(r"[-_.]+", "-", item["name"]).lower(): item["version"]
        for item in runtime["dependencies"]
    }
    locked = {
        re.sub(r"[-_.]+", "-", item["name"]).lower(): item["version"]
        for item in tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    }
    if installed != declared or installed != locked:
        raise CheckFailure("PACKAGE_DEPENDENCY_MISMATCH")


def inspect_bundle(root: Path, report_path: Path) -> bool:
    """ソースを一時領域へ複製して検査し、前後に配布物の不変性を照合する。"""
    root, report_path = root.resolve(), report_path.resolve()
    if report_path.is_relative_to(root):
        raise CheckFailure("REPORT_MUST_BE_OUTSIDE_BUNDLE")
    if report_path.exists():
        raise CheckFailure("REPORT_ALREADY_EXISTS")
    checks = [{"name": name, "status": "not_checked"} for name in CHECK_NAMES]
    report = {
        "schemaVersion": 1,
        "sourceCommit": "",
        "payloadDigest": "",
        "platform": "",
        "checks": checks,
        "deploymentVerified": False,
    }
    index = 0
    try:
        manifest = verify_payload(root)
        report["sourceCommit"] = manifest["source"]["commit"]
        report["payloadDigest"] = hashlib.sha256(canonical(manifest["files"])).hexdigest()
        checks[index]["status"] = "passed"
        index += 1
        runtime = lambda_runtime(manifest)
        report["platform"] = runtime["platform"]
        if (
            platform.system() != "Linux"
            or platform.machine() not in MACHINES[runtime["architecture"]]
            or sys.version_info[:2] != (3, 14)
        ):
            raise CheckFailure("MATCHING_LINUX_ARCHITECTURE_PYTHON_314_REQUIRED")
        with tempfile.TemporaryDirectory(prefix="adtl-bundle-check-") as temporary:
            scratch = Path(temporary)
            environment = isolated_environment(scratch)
            source = scratch / "source"
            shutil.copytree(root, source)
            package = scratch / "package"
            extract_package(source, package, manifest)
            command(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                    "import boto3,handler,validation; assert callable(handler.handler); "
                    "assert all(Path(m.__file__).is_relative_to(Path(sys.argv[1])) "
                    "for m in (boto3,handler,validation))",
                    str(package),
                ],
                source,
                environment,
            )
            checks[index]["status"] = "passed"
            index += 1
            sample_code = """import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from validation import validate_csv
root=Path(sys.argv[2]); expected=root/'samples/expected/validation'
fixtures={p.stem:p for p in (root/'samples').rglob('*.csv') if 'expected' not in p.parts}
assert len(list(expected.glob('*.json')))==7
for result in expected.glob('*.json'):
 actual=validate_csv(fixtures[result.stem].read_bytes(),fixtures[result.stem].name)
 assert actual==json.loads(result.read_text()),result.stem
"""
            command(
                [sys.executable, "-I", "-c", sample_code, str(package), str(source)],
                source,
                environment,
            )
            checks[index]["status"] = "passed"
            index += 1
            terraform = source / "infra/aws/pipeline"
            command(
                [
                    "terraform",
                    "init",
                    "-backend=false",
                    "-input=false",
                    "-lockfile=readonly",
                    "-no-color",
                ],
                terraform,
                environment,
            )
            checks[index]["status"] = "passed"
            index += 1
            command(["terraform", "validate", "-no-color"], terraform, environment)
            checks[index]["status"] = "passed"
            index += 1
            command(
                ["bash", str(source / "scripts/aws/verify-bundle.sh"), str(source)],
                source,
                environment,
            )
            checks[index]["status"] = "passed"
            index += 1
            command(
                [
                    "pwsh",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(source / "scripts/aws/verify-bundle.ps1"),
                    "-BundleRoot",
                    str(source),
                ],
                source,
                environment,
            )
            checks[index]["status"] = "passed"
        after = verify_payload(root)
        if after != manifest:
            raise CheckFailure("BUNDLE_CHANGED_DURING_CHECK")
    except (
        CheckFailure,
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        zipfile.BadZipFile,
        subprocess.TimeoutExpired,
    ) as error:
        checks[min(index, len(checks) - 1)]["status"] = "failed"
        checks[min(index, len(checks) - 1)]["details"] = (
            str(error) if isinstance(error, CheckFailure) else type(error).__name__
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return all(check["status"] == "passed" for check in checks)


def main() -> None:
    """配布物の展開先と、その外に置く検査reportをCLIから受け取る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        succeeded = inspect_bundle(args.bundle_root, args.report)
    except CheckFailure as error:
        parser.exit(1, str(error) + "\n")
    raise SystemExit(not succeeded)


if __name__ == "__main__":
    main()
