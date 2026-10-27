# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""指定commitの許可済みソースと検査したLambda ZIPを会社向けに収集する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
# 個人設定や追加の実データを追跡しても、ここで明示されないファイルは収集しない。
ALLOWED_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "functions/aws/handler.py",
        "functions/aws/pyproject.toml",
        "functions/validator/pyproject.toml",
        "functions/validator/validation.py",
        "glue/transform_orders.py",
        "workflows/aws/pipeline.asl.json",
        "ruff.toml",
        "infra/aws/pipeline/main.tf",
        "infra/aws/pipeline/iam.tf",
        "infra/aws/pipeline/versions.tf",
        "infra/aws/pipeline/variables.tf",
        "infra/aws/pipeline/outputs.tf",
        "infra/aws/pipeline/.terraform.lock.hcl",
        "infra/aws/pipeline/backend.tf.example",
        "infra/aws/pipeline/backend.hcl.example",
        "infra/aws/pipeline/terraform.tfvars.example",
        "infra/aws/pipeline/README.md",
        "scripts/aws/package.py",
        "scripts/aws/bundle.py",
        "scripts/aws/check_bundle.py",
        "scripts/aws/verify-bundle.ps1",
        "scripts/aws/verify-bundle.sh",
        "scripts/aws/test_pipeline.py",
        "scripts/aws/test_spark.py",
        "scripts/aws/test_spark.py.lock",
        "scripts/aws/test_bundle.py",
        "scripts/aws/test_verify_bundle.py",
        "scripts/aws/test_check_bundle.py",
        "tests/aws/test_check_bundle.py",
        "scripts/validator/test_pure.py",
        "tests/validator/test_validation.py",
        "tests/aws/test_pipeline.py",
        "tests/aws/test_transform.py",
        "tests/aws/test_bundle.py",
        "tests/aws/test_verify_bundle.py",
        "docs/aws-bundle.md",
        "docs/aws-implementation.md",
        "docs/aws-architecture.md",
        "docs/aws-learning-plan.md",
        "docs/architecture.md",
        "docs/project-brief.md",
        "docs/learning-plan.md",
        "docs/tutorials/phase-3-data-factory.md",
        "docs/tutorials/phase-4-schema-evolution.md",
        "docs/adr/0011-coordinate-input-attempts-in-dynamodb.md",
        "docs/adr/0012-use-glue-spark-for-schema-evolution.md",
        "samples/valid/orders_v1.csv",
        "samples/invalid/orders_invalid.csv",
        "samples/schema-evolution/orders_v2.csv",
        "samples/schema-evolution/orders_v3.csv",
        "samples/schema-evolution/orders_drifted_types.csv",
        "samples/schema-evolution/orders_missing_required.csv",
        "samples/schema-evolution/orders_amount_type_change.csv",
        "samples/expected/README.md",
        "samples/expected/validation/orders_v1.json",
        "samples/expected/validation/orders_v2.json",
        "samples/expected/validation/orders_v3.json",
        "samples/expected/validation/orders_drifted_types.json",
        "samples/expected/validation/orders_missing_required.json",
        "samples/expected/validation/orders_amount_type_change.json",
        "samples/expected/validation/orders_invalid.json",
        "samples/expected/transformed/standard/orders_v1.csv",
        "samples/expected/transformed/standard/orders_v2.csv",
        "samples/expected/transformed/standard/orders_v3.csv",
        "samples/expected/transformed/standard/orders_drifted_types.csv",
        "samples/expected/transformed/drift/orders_v2.csv",
        "samples/expected/transformed/drift/orders_v3.csv",
        "samples/expected/transformed/drift/orders_drifted_types.csv",
    }
)
REQUIRED_CHECKS = frozenset(
    {
        "manifest",
        "lambda_import",
        "samples",
        "terraform_init",
        "terraform_validate",
        "bash_checksums",
        "powershell_checksums",
    }
)


def sha256(content: bytes) -> str:
    """検査対象の実体からSHA-256を計算する。"""
    return hashlib.sha256(content).hexdigest()


def canonical(value) -> bytes:
    """検査報告と配布物の参照に同じJSON表現を使う。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def git(repo: Path, *args: str) -> bytes:
    """shellを経由せず対象リポジトリのGitを呼ぶ。"""
    return subprocess.check_output(["git", "-C", str(repo), *args])


def resolve_commit(repo: Path, commit: str) -> str:
    """指定をcommitの不変参照へ解決する。"""
    return (
        git(repo, "rev-parse", "--verify", "--end-of-options", commit + "^{commit}")
        .decode()
        .strip()
    )


def collect(repo: Path, commit: str) -> dict[str, bytes]:
    """作業ツリーを読まず、指定commitの許可済みblobだけを収集する。"""
    resolved = resolve_commit(repo, commit)
    result = {}
    for entry in git(repo, "ls-tree", "-r", "-z", resolved).split(b"\0"):
        if not entry:
            continue
        metadata, filename = entry.split(b"\t", 1)
        name = filename.decode("utf-8", errors="surrogateescape")
        if name not in ALLOWED_FILES:
            continue
        mode, kind, oid = metadata.decode().split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError("配布ソースのsymlink・submoduleは許可しません。")
        result[name] = git(repo, "cat-file", "blob", oid)
    return result


def lambda_dependencies(lock: dict) -> set[tuple[str, str]]:
    """workspaceのlockから、Lambdaメンバーが推移的に依存するパッケージと版を集める。"""
    packages = {item["name"]: item for item in lock["package"]}
    pending = ["aws-lambda"]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        pending.extend(item["name"] for item in packages[name].get("dependencies", []))
    # メンバー自身はビルドしないため、配置される依存には含めない。
    return {(name, packages[name]["version"]) for name in seen - {"aws-lambda"}}


def package_manifest(content: bytes, source: dict[str, bytes]) -> dict:
    """配置物のコード・lock・依存・対象環境を収集したcommitへ結び付ける。"""
    import io

    if len(content) > 64 * 1024 * 1024:
        raise ValueError("Lambda ZIPが上限を超えています。")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(item.file_size for item in members) > 256 * 1024 * 1024:
            raise ValueError("Lambda ZIPの展開サイズが上限を超えています。")
        names = set()
        packages = {"boto3", "botocore", "dateutil", "jmespath", "s3transfer", "urllib3"}
        distributions = {
            "boto3",
            "botocore",
            "python_dateutil",
            "jmespath",
            "s3transfer",
            "urllib3",
            "six",
        }
        for item in members:
            path = PurePosixPath(item.filename)
            if (
                item.filename in names
                or item.is_dir()
                or any(part in ("", ".", "..") for part in item.filename.split("/"))
                or any(ord(character) < 32 for character in item.filename)
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in item.filename
                or ":" in item.filename
                or (item.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("Lambda ZIPに安全でないパスがあります。")
            names.add(item.filename)
            top = path.parts[0]
            allowed_metadata = any(
                top.startswith(name + "-") and top.endswith(".dist-info") for name in distributions
            )
            if (
                top not in packages
                and item.filename
                not in {"handler.py", "validation.py", "six.py", "package-manifest.json"}
                and not allowed_metadata
            ):
                raise ValueError("Lambda ZIPに許可されていないファイルがあります。")
        if archive.testzip() is not None:
            raise ValueError("Lambda ZIPのCRCが一致しません。")
        manifest = json.loads(archive.read("package-manifest.json"))
        if (
            manifest["python"] != "3.14"
            or manifest["architecture"] not in ("arm64", "x86_64")
            or manifest["platform"] != "linux-" + manifest["architecture"]
        ):
            raise ValueError("Lambdaの対象環境が一致しません。")
        for deployed, original in [
            ("handler.py", "functions/aws/handler.py"),
            ("validation.py", "functions/validator/validation.py"),
        ]:
            if archive.read(deployed) != source[original]:
                raise ValueError("Lambda ZIPのコードが指定commitと一致しません。")
        if manifest["validation_sha256"] != sha256(
            source["functions/validator/validation.py"]
        ) or manifest["lock_sha256"] != sha256(source["uv.lock"]):
            raise ValueError("Lambdaの共通コードまたは依存lockが一致しません。")
        lock = tomllib.loads(source["uv.lock"].decode())
        expected = sorted(lambda_dependencies(lock))
        actual = sorted((item["name"], item["version"]) for item in manifest["dependencies"])
        if actual != expected:
            raise ValueError("Lambda依存版がlockと一致しません。")
    return manifest


def build(
    repo: Path, commit: str, lambda_zip: Path, destination: Path, report: Path | None = None
) -> dict:
    """不変ソースから一式を作り、対応した検査報告がある場合だけ検査済みとする。"""
    if destination.exists():
        raise FileExistsError("出力先は新規ファイルを指定してください。")
    source_commit = resolve_commit(repo, commit)
    payload = collect(repo, source_commit)
    if ALLOWED_FILES - payload.keys():
        raise ValueError(
            "指定commitに必要な配布ファイルがありません: "
            + ", ".join(sorted(ALLOWED_FILES - payload.keys()))
        )
    runtime_zip = lambda_zip.read_bytes()
    runtime = package_manifest(runtime_zip, payload)
    payload["dist/aws/lambda.zip"] = runtime_zip
    payload["checksums.sha256"] = "".join(
        f"{sha256(data)}  {name}\n" for name, data in sorted(payload.items())
    ).encode()
    files = [
        {"path": name, "size": len(data), "sha256": sha256(data)}
        for name, data in sorted(payload.items())
    ]
    digest = sha256(canonical(files))
    verification = {"status": "not_checked", "checks": [], "deploymentVerified": False}
    if report:
        evidence = json.loads(report.read_bytes())
        checks = evidence["checks"]
        names = [check["name"] for check in checks]
        if (
            evidence.get("schemaVersion") != 1
            or evidence.get("sourceCommit") != source_commit
            or evidence.get("payloadDigest") != digest
            or evidence.get("platform") != runtime["platform"]
            or evidence.get("deploymentVerified") is not False
            or len(set(names)) != len(names)
            or not REQUIRED_CHECKS.issubset(names)
            or any(check["status"] != "passed" for check in checks)
        ):
            raise ValueError("検査報告が配布内容・対象環境と一致しません。")
        verification.update(
            {"status": "passed", "checks": checks, "platform": evidence["platform"]}
        )
    manifest = {
        "schemaVersion": 1,
        "source": {"commit": source_commit},
        "generator": {"name": "scripts/aws/bundle.py", "version": 1},
        "runtimes": {
            "lambda": runtime,
            "glue": {"version": "5.1", "spark": "3.5.6", "python": "3.11"},
        },
        "files": files,
        "verification": verification,
    }
    payload["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode() + b"\n"
    payload["manifest.sha256"] = "".join(
        f"{sha256(payload[name])}  {name}\n" for name in ["manifest.json", "checksums.sha256"]
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        output = destination.open("xb")
        created = True
        with output, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    result = {
        "zip": str(destination),
        "sha256": sha256(destination.read_bytes()),
        "sourceCommit": source_commit,
        "payloadDigest": digest,
        "verification": verification["status"],
    }
    print(json.dumps(result))
    return result


def main() -> None:
    """指定commit、ZIP、検査報告と新規出力先をCLIで受け取る。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--lambda-zip", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    build(args.repo, args.commit, args.lambda_zip, args.destination, args.report)


if __name__ == "__main__":
    main()
