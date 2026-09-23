# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = [
#   "azure-functions>=1.24,<2",
#   "azure-identity>=1.25,<2",
#   "azure-storage-blob>=12.27,<13",
# ]
# ///
"""CSV検証のHTTP入口と、同じ依存環境で実行する学習用コマンド。"""

import argparse
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import azure.functions as func
from storage import InputChangedError, StorageReadError, StorageTimeoutError, read_csv
from validation import validate_csv

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def json_response(body: dict, status: int = 200) -> func.HttpResponse:
    """ADFで参照できるJSONオブジェクトをHTTP応答にする。"""
    return func.HttpResponse(
        json.dumps(body, ensure_ascii=False), status_code=status, mimetype="application/json"
    )


def parse_request(request: func.HttpRequest) -> tuple[str, str]:
    """検証対象を固定Storage内のlandingと単一ETagへ制限する。"""
    if request.method != "POST" or len(request.get_body()) > 8192:
        raise ValueError("POSTの小さなJSONオブジェクトが必要です。")
    body = request.get_json()
    if not isinstance(body, dict) or set(body) != {"filesystem", "path", "etag"}:
        raise ValueError("filesystem・path・etagが必要です。")
    path, etag = body["path"], body["etag"]
    if body["filesystem"] != "landing" or not isinstance(path, str) or not 1 <= len(path) <= 1024:
        raise ValueError("landing内の相対パスが必要です。")
    if any(part in {"", ".", ".."} for part in path.split("/")) or re.search(
        r"[\\\x00-\x1f\x7f:?#%]", path
    ):
        raise ValueError("pathにはURLやパス移動表現を指定できません。")
    if not isinstance(etag, str) or not re.fullmatch(r'"[A-Za-z0-9_-]{1,128}"', etag):
        raise ValueError("etagには取得した引用符付きETagが必要です。")
    return path, etag


@app.route(route="validate", methods=["POST"], trigger_arg_name="request")
def validate(request: func.HttpRequest) -> func.HttpResponse:
    """入力内容の判定と、呼び出し・読み取りの失敗を区別して返す。"""
    try:
        path, etag = parse_request(request)
    except ValueError, UnicodeDecodeError:
        return json_response(
            {"code": "INVALID_REQUEST", "message": "filesystem・path・etagを確認してください。"},
            400,
        )
    try:
        return json_response(validate_csv(read_csv(path, etag), path))
    except InputChangedError:
        return json_response(
            {"code": "INPUT_CHANGED", "message": "入力のETagが変わっています。"}, 409
        )
    except StorageTimeoutError:
        return json_response(
            {"code": "STORAGE_TIMEOUT", "message": "入力の取得がタイムアウトしました。"}, 504
        )
    except StorageReadError:
        return json_response(
            {"code": "STORAGE_READ_FAILED", "message": "入力を取得できませんでした。"}, 502
        )
    except Exception:
        # SDKの例外本文にはURLや認証情報が含まれ得るため、応答とログへ展開しない。
        return json_response(
            {"code": "INTERNAL_ERROR", "message": "入力検証を完了できませんでした。"}, 500
        )


def main() -> None:
    """PEP 723の固定依存を使い、検証・サンプル実行・ローカルホストを起動する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["test", "sample", "serve"])
    parser.add_argument("path", nargs="?")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.command == "test":
        sys.path.insert(0, str(root))
        suite = unittest.defaultTestLoader.discover(str(root / "tests/validator"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(not result.wasSuccessful())
    if args.command == "sample":
        if not args.path:
            parser.error("sampleにはCSVのパスが必要です。")
        path = Path(args.path)
        print(json.dumps(validate_csv(path.read_bytes(), path.name), ensure_ascii=False, indent=2))
        return
    environment = os.environ.copy()
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment["PATH"]
    environment["FUNCTIONS_WORKER_RUNTIME"] = "python"
    try:
        raise SystemExit(
            subprocess.call(["func", "start"], cwd=Path(__file__).parent, env=environment)
        )
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
