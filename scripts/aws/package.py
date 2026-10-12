# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""LambdaのPEP 723 lockから対象Linux用ZIPを生成し、実importを検証する。"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from importlib.metadata import distributions
from pathlib import Path


def build(destination: Path, architecture: str, python_version: str) -> None:
    """対象CPU上で固定依存を配置し、共通検証コードと成果物の整合性を確認する。"""
    machines = {"arm64": {"aarch64", "arm64"}, "x86_64": {"x86_64", "AMD64"}}
    if platform.system() != "Linux" or platform.machine() not in machines[architecture]:
        raise RuntimeError("指定したCPUのLinux環境で実行してください。")
    if destination.exists():
        raise FileExistsError("ZIPの出力先は新規ファイルにしてください。")
    root = Path(__file__).resolve().parents[2]
    source = root / "functions/aws"
    validation = root / "functions/validator/validation.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="adtl-lambda-") as temporary:
        staging = Path(temporary) / "package"
        staging.mkdir()
        for item in source.glob("*.py"):
            shutil.copyfile(item, staging / item.name)
        shutil.copyfile(validation, staging / "validation.py")
        validation_sha = hashlib.sha256(validation.read_bytes()).hexdigest()
        if hashlib.sha256((staging / "validation.py").read_bytes()).hexdigest() != validation_sha:
            raise RuntimeError("共通検証コードのSHA-256が一致しません。")
        dependencies = subprocess.check_output(
            [
                "uv",
                "export",
                "--locked",
                "--script",
                str(source / "handler.py"),
                "--format",
                "requirements.txt",
                "--no-header",
            ]
        )
        dependency_file = Path(temporary) / "dependencies.txt"
        dependency_file.write_bytes(dependencies)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                python_version,
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--requirements",
                str(dependency_file),
                "--target",
                str(staging),
            ],
            check=True,
        )
        manifest = {
            "python": python_version,
            "architecture": architecture,
            "platform": f"linux-{architecture}",
            "validation_sha256": validation_sha,
            "lock_sha256": hashlib.sha256((source / "handler.py.lock").read_bytes()).hexdigest(),
            "dependencies": sorted(
                (
                    {"name": item.metadata["Name"], "version": item.version}
                    for item in distributions(path=[str(staging)])
                ),
                key=lambda item: item["name"],
            ),
        }
        (staging / "package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        temporary_zip = Path(temporary) / "lambda.zip"
        with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(staging.rglob("*")):
                if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                    # ZIPのmtimeを固定し、同じ入力から同じhashの成果物を作る。
                    info = zipfile.ZipInfo(
                        item.relative_to(staging).as_posix(), (2020, 1, 1, 0, 0, 0)
                    )
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, item.read_bytes())
        extracted = Path(temporary) / "extracted"
        with zipfile.ZipFile(temporary_zip) as archive:
            if hashlib.sha256(archive.read("validation.py")).hexdigest() != validation_sha:
                raise RuntimeError("ZIP内の共通検証コードが一致しません。")
            archive.extractall(extracted)
        # ランタイム付属のBoto3に偶然依存せず、展開したZIPを実際にimportする。
        subprocess.run(
            [
                "uv",
                "run",
                "--no-project",
                "--python",
                python_version,
                "python",
                "-I",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import boto3, handler, validation; "
                "assert callable(handler.handler)",
                str(extracted),
            ],
            check=True,
            env={
                **os.environ,
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_DEFAULT_REGION": "ap-northeast-1",
                "BUCKET_NAME": "import-check",
                "STATE_TABLE": "import-check",
                "CRAWLER_NAME": "import-check",
                "GLUE_JOB_NAME": "import-check",
            },
        )
        # importまで成功したZIPだけを指定された出力先へ渡す。
        with temporary_zip.open("rb") as package, destination.open("xb") as output:
            shutil.copyfileobj(package, output)
    print(json.dumps({"zip": str(destination), "imports": "passed", **manifest}))


def main() -> None:
    """配置先と対象runtimeをCLIから受け取る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--architecture", choices=["arm64", "x86_64"], default="arm64")
    parser.add_argument("--python-version", default="3.14")
    args = parser.parse_args()
    build(args.destination.resolve(), args.architecture, args.python_version)


if __name__ == "__main__":
    main()
