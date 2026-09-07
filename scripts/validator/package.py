# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""固定依存を含むAzure Functions配置ディレクトリをLinux x86_64で構築する。"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tempfile
from importlib.metadata import distributions
from pathlib import Path

BUILD_IMAGE = (
    "ghcr.io/astral-sh/uv@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1"
)


def build_in_docker(destination: Path) -> None:
    """アプリと構築コードだけを渡し、Macでも固定Linuxイメージで構築する。"""
    if destination.exists():
        raise FileExistsError("配置先は新規ディレクトリを指定してください。")
    root = Path(__file__).resolve().parents[2]
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--mount",
            f"type=bind,src={root / 'functions/validator'},dst=/src/functions/validator,readonly",
            "--mount",
            f"type=bind,src={root / 'scripts/validator'},dst=/src/scripts/validator,readonly",
            "--mount",
            f"type=bind,src={destination.parent},dst=/out",
            "-w",
            "/src",
            BUILD_IMAGE,
            "uv",
            "run",
            "scripts/validator/package.py",
            f"/out/{destination.name}",
        ],
        check=True,
    )


def build(destination: Path) -> None:
    """新規ディレクトリにコードと検証済みのLinux依存を配置する。"""
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise RuntimeError("Azure向けの構築はLinux x86_64環境で実行してください。")
    source = Path(__file__).resolve().parents[2] / "functions/validator"
    destination.mkdir(parents=True, exist_ok=False)
    for filename in ["function_app.py", "validation.py", "storage.py", "host.json", ".funcignore"]:
        shutil.copyfile(source / filename, destination / filename)
    # 依存の正はアプリのPEP 723とlock。配置用リストはこの処理内だけで使う。
    requirements = subprocess.check_output(
        [
            "uv",
            "export",
            "--locked",
            "--script",
            str(source / "function_app.py"),
            "--format",
            "requirements.txt",
            "--no-header",
        ]
    )
    target = destination / ".python_packages/lib/site-packages"
    with tempfile.TemporaryDirectory(prefix="adtl-dependencies-") as temporary:
        dependency_file = Path(temporary) / "dependencies.txt"
        dependency_file.write_bytes(requirements)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                "3.14",
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--requirements",
                str(dependency_file),
                "--target",
                str(target),
            ],
            check=True,
        )
    # wheelのネイティブ部分を含め、配置先だけを使ってimportできるか確認する。
    verification = (
        "import sys; sys.path[:0]=sys.argv[1:]; "
        "import azure.functions, azure.identity, azure.storage.blob; "
        "from cryptography.hazmat.bindings._rust import openssl; "
        "import function_app; "
        "assert len(function_app.app.get_functions()) == 1"
    )
    subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--python",
            "3.14",
            "python",
            "-I",
            "-c",
            verification,
            str(target),
            str(destination),
        ],
        check=True,
    )
    manifest = {
        "python": "3.14",
        "platform": "linux-x86_64",
        "lock_sha256": hashlib.sha256((source / "function_app.py.lock").read_bytes()).hexdigest(),
        "dependencies": sorted(
            (
                {"name": item.metadata["Name"], "version": item.version}
                for item in distributions(path=[str(target)])
            ),
            key=lambda item: item["name"],
        ),
    }
    (destination / "package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "package": str(destination),
                "platform": "linux-x86_64",
                "python": "3.14",
                "imports": "passed",
            }
        )
    )


def main() -> None:
    """既存成果物を上書きしない配置先を受け取る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="新規に作成する配置ディレクトリ")
    parser.add_argument("--docker", action="store_true", help="固定Linux x86_64コンテナで構築する")
    args = parser.parse_args()
    if args.docker:
        build_in_docker(args.destination.resolve())
    else:
        build(args.destination.resolve())


if __name__ == "__main__":
    main()
