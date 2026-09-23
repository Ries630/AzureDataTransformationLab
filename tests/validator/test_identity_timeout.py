"""Managed Identity の認証待機がHTTP公開境界を占有し続けないことを確認する。"""

import json
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class HangingIdentityHandler(BaseHTTPRequestHandler):
    """トークン要求を受信してから解放されるまで応答しない。"""

    def do_GET(self) -> None:  # noqa: N802
        """認証クライアントのタイムアウトを発生させるまで接続を保持する。"""
        server = self.server
        server.request_started()
        server.request_seen.set()
        try:
            server.release.wait()
            # クライアントの後処理を止めないため、解放時だけ再試行しない応答を返す。
            self.send_response(400)
            self.end_headers()
        except BrokenPipeError, ConnectionResetError:
            pass
        finally:
            server.request_finished()

    def log_message(self, format: str, *args: object) -> None:
        """テスト中の合成エンドポイントのログを出力しない。"""


class HangingIdentityServer(ThreadingHTTPServer):
    """Managed Identity エンドポイントを模した終了可能なサーバー。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        """未使用ポートでサーバーを作り、認証要求の状態を共有する。"""
        super().__init__(("127.0.0.1", 0), HangingIdentityHandler)
        self.request_seen = threading.Event()
        self.requests_finished = threading.Event()
        self.requests_finished.set()
        self.request_count = 0
        self.request_lock = threading.Lock()
        self.release = threading.Event()

    def request_started(self) -> None:
        """実行中の合成認証要求を記録する。"""
        with self.request_lock:
            self.request_count += 1
            self.requests_finished.clear()

    def request_finished(self) -> None:
        """終了した合成認証要求を記録し、残りがなければ通知する。"""
        with self.request_lock:
            self.request_count -= 1
            if self.request_count == 0:
                self.requests_finished.set()


class IdentityTimeoutTests(unittest.TestCase):
    """認証エンドポイント停止時の公開HTTP応答を確認する。"""

    def test_unresponsive_identity_returns_504_within_forty_five_seconds(self) -> None:
        """トークン発行が応答しなくても、Functionは45秒以内に504を返す。"""
        server = HangingIdentityServer()
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        child_process: subprocess.Popen[str] | None = None
        cleanup_errors: list[str] = []
        functions_directory = Path(__file__).resolve().parents[2] / "functions" / "validator"
        child_script = """\
import json
import azure.functions as func
from function_app import validate

response = validate(func.HttpRequest(
    method="POST",
    url="/api/validate",
    body=json.dumps(
        {"filesystem": "landing", "path": "orders_v1.csv", "etag": '\"0xABC\"'}
    ).encode(),
))
body = json.loads(response.get_body())
print(json.dumps({"status": response.status_code, "code": body.get("code")}))
"""
        try:
            server_thread.start()
            child_environment = {
                "AZURE_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
                "AZURE_FUNCTIONS_ENVIRONMENT": "Production",
                "IDENTITY_ENDPOINT": (
                    f"http://127.0.0.1:{server.server_address[1]}/metadata/identity/oauth2/token"
                ),
                "IDENTITY_HEADER": "synthetic-identity-header",
                "LAB_STORAGE_ACCOUNT_NAME": "testaccount",
                "PYTHONPATH": str(functions_directory),
            }
            started = time.monotonic()
            child_process = subprocess.Popen(
                [sys.executable, "-c", child_script],
                env=child_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertTrue(
                server.request_seen.wait(timeout=1),
                "Managed Identity の合成エンドポイントへ接続されていません",
            )
            try:
                stdout, _stderr = child_process.communicate(
                    timeout=max(0, 45 - (time.monotonic() - started))
                )
            except subprocess.TimeoutExpired:
                child_process.kill()
                try:
                    child_process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    cleanup_errors.append("子プロセスを5秒以内に回収できません")
                self.fail("Managed Identityの停止時に45秒以内のHTTP応答がありません")
            elapsed = time.monotonic() - started
            self.assertLessEqual(elapsed, 45)
            self.assertEqual(0, child_process.returncode)
            self.assertEqual({"status": 504, "code": "STORAGE_TIMEOUT"}, json.loads(stdout))
        finally:
            # 子プロセスを先に回収し、合成サーバーの要求処理を解放して終了を確認する。
            if child_process is not None and child_process.poll() is None:
                child_process.kill()
                try:
                    child_process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    cleanup_errors.append("子プロセスを5秒以内に回収できません")
            server.release.set()
            shutdown_thread = threading.Thread(target=server.shutdown, daemon=True)
            shutdown_thread.start()
            shutdown_thread.join(timeout=5)
            if shutdown_thread.is_alive():
                cleanup_errors.append("HTTPサーバー停止処理が5秒以内に終了しません")
            server.server_close()
            server_thread.join(timeout=5)
            if server_thread.is_alive():
                cleanup_errors.append("HTTPサーバースレッドが5秒以内に終了しません")
            if not server.requests_finished.wait(timeout=5):
                cleanup_errors.append("認証要求スレッドが5秒以内に終了しません")
            if cleanup_errors:
                self.fail("; ".join(cleanup_errors))


if __name__ == "__main__":
    unittest.main()
