"""HTTP入口から、入力契約と検証結果の区別を確認する。"""

import json
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import azure.functions as func
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ServiceResponseError
from function_app import app
from validation import MAX_BYTES

REGISTERED = app.get_functions()[0]
HANDLER = REGISTERED.get_user_function()
ROOT = Path(__file__).resolve().parents[2]


def request(body: object, headers: dict[str, str] | None = None) -> func.HttpRequest:
    """HTTPクライアントが送るJSONを組み立てる。"""
    return func.HttpRequest(
        method="POST",
        url="/api/validate",
        body=json.dumps(body).encode(),
        headers=headers or {},
    )


def valid_request() -> func.HttpRequest:
    """取得したオブジェクトの単一世代を指定する。"""
    return request({"filesystem": "landing", "path": "orders.csv", "etag": '"0xABC"'})


class HttpContractTests(unittest.TestCase):
    """Azure Functionsに登録された公開ハンドラーの契約。"""

    def test_registered_http_trigger_requires_function_key(self) -> None:
        """ホストへ渡すHTTP登録が匿名公開へ変わらないことを確認する。"""
        bindings = json.loads(REGISTERED.get_function_json())["bindings"]
        trigger = next(binding for binding in bindings if binding["type"] == "httpTrigger")
        self.assertEqual("FUNCTION", trigger["authLevel"])
        self.assertEqual(["POST"], trigger["methods"])
        self.assertEqual("validate", trigger["route"])

    def test_invalid_request_is_400(self) -> None:
        """入力を特定できない要求は業務Rejectに変換しない。"""
        response = HANDLER(request({}))
        self.assertEqual(400, response.status_code)
        self.assertEqual("INVALID_REQUEST", json.loads(response.get_body())["code"])

    def test_request_rejects_other_locations_and_unsafe_paths(self) -> None:
        """要求値から任意のStorageや別Filesystemへアクセスできない。"""
        for changes in [
            {"filesystem": "output"},
            {"path": "../orders.csv"},
            {"path": "/orders.csv"},
            {"path": "https://other.example/x.csv"},
            {"path": "a//b.csv"},
            {"path": "a\\b.csv"},
            {"path": "a/%2e%2e/b.csv"},
            {"etag": "*"},
            {"etag": ""},
            {"etag": None},
            {"path": 1},
            {"storageAccount": "other"},
        ]:
            with self.subTest(changes=changes):
                body = {"filesystem": "landing", "path": "orders.csv", "etag": '"0xABC"'} | changes
                self.assertEqual(400, HANDLER(request(body)).status_code)

    def test_non_objects_and_malformed_json_are_400(self) -> None:
        """JSONの型や構文が不正でも500にしない。"""
        for body in [b"[1]", b"null", b"{", b"\xff", b" " * 8193, b"[" * 1100 + b"]" * 1100]:
            with self.subTest(body=body[:10]):
                response = HANDLER(func.HttpRequest(method="POST", url="/api/validate", body=body))
                self.assertEqual(400, response.status_code)

    @patch.dict(
        os.environ,
        {
            "LAB_STORAGE_ACCOUNT_NAME": "testaccount",
            "WEBSITE_HOSTNAME": "localhost:7071",
            "AZURE_FUNCTIONS_ENVIRONMENT": "Development",
        },
        clear=True,
    )
    @patch("storage.AzureCliCredential")
    @patch("storage.BlobClient")
    def test_sample_csv_results_through_http(
        self, client: MagicMock, credential: MagicMock
    ) -> None:
        """実CSVをHTTPから判定し、SDKに対するETag・上限指定も確認する。"""
        blob = client.return_value.__enter__.return_value
        for sample, status, count in [
            ("valid/orders_v1.csv", "VALID", 0),
            ("invalid/orders_invalid.csv", "INVALID", 5),
        ]:
            with self.subTest(sample=sample):
                blob.download_blob.return_value.readall.return_value = (
                    ROOT / "samples" / sample
                ).read_bytes()
                response = HANDLER(valid_request())
                self.assertEqual(200, response.status_code)
                result = json.loads(response.get_body())
                self.assertEqual(status, result["status"])
                self.assertEqual(count, result["errorCount"])
        self.assertEqual("landing", client.call_args.kwargs["container_name"])
        credential.assert_called()
        self.assertEqual(
            "https://testaccount.blob.core.windows.net", client.call_args.kwargs["account_url"]
        )
        options = blob.download_blob.call_args.kwargs
        self.assertEqual('"0xABC"', options["etag"])
        self.assertEqual(MatchConditions.IfNotModified, options["match_condition"])
        self.assertEqual(MAX_BYTES + 1, options["length"])

    @patch.dict(os.environ, {"LAB_STORAGE_ACCOUNT_NAME": "testaccount"}, clear=True)
    @patch("storage.AzureCliCredential")
    @patch("storage.BlobClient")
    def test_empty_blob_is_invalid_after_conditional_size_check(
        self, client: MagicMock, credential: MagicMock
    ) -> None:
        """空Blobの範囲外応答を、同じETagのサイズ確認後に業務Rejectへ変換する。"""
        blob = client.return_value.__enter__.return_value
        error = HttpResponseError(message="range not satisfiable")
        error.status_code = 416
        blob.download_blob.side_effect = error
        blob.get_blob_properties.return_value.size = 0
        response = HANDLER(valid_request())
        self.assertEqual(200, response.status_code)
        self.assertEqual("INVALID", json.loads(response.get_body())["status"])
        options = blob.get_blob_properties.call_args.kwargs
        self.assertEqual('"0xABC"', options["etag"])
        self.assertEqual(MatchConditions.IfNotModified, options["match_condition"])
        changed = HttpResponseError(message="changed")
        changed.status_code = 412
        blob.get_blob_properties.side_effect = changed
        self.assertEqual(409, HANDLER(valid_request()).status_code)

    @patch.dict(os.environ, {"LAB_STORAGE_ACCOUNT_NAME": "testaccount"}, clear=True)
    @patch("storage.AzureCliCredential")
    @patch("storage.BlobClient")
    def test_storage_errors_do_not_become_invalid(
        self, client: MagicMock, credential: MagicMock
    ) -> None:
        """世代競合・取得不可・通信タイムアウトを入力不備から区別する。"""
        blob = client.return_value.__enter__.return_value
        for upstream, expected, code in [
            (412, 409, "INPUT_CHANGED"),
            (404, 502, "STORAGE_READ_FAILED"),
            (403, 502, "STORAGE_READ_FAILED"),
        ]:
            with self.subTest(upstream=upstream):
                error = HttpResponseError(message="private URL and credentials")
                error.status_code = upstream
                blob.download_blob.side_effect = error
                response = HANDLER(valid_request())
                self.assertEqual(expected, response.status_code)
                self.assertEqual(code, json.loads(response.get_body())["code"])
                self.assertNotIn(b"private", response.get_body())
        blob.download_blob.side_effect = ServiceResponseError("private", error=TimeoutError())
        self.assertEqual(504, HANDLER(valid_request()).status_code)

    @patch.dict(
        os.environ,
        {
            "LAB_STORAGE_ACCOUNT_NAME": "testaccount",
            "WEBSITE_HOSTNAME": "localhost:7071",
            "AZURE_FUNCTIONS_ENVIRONMENT": "Development",
        },
        clear=True,
    )
    @patch("storage.AzureCliCredential")
    @patch("storage.BlobClient")
    def test_each_http_response_emits_one_safe_structured_event(
        self, client: MagicMock, credential: MagicMock
    ) -> None:
        """全HTTP結果のログを相関し、入力やStorage詳細を含めない。"""
        correlation = str(uuid.uuid4()).upper()
        valid = request(
            {"filesystem": "landing", "path": "orders.csv", "etag": '"0xABC"'},
            {"x-adf-pipeline-run-id": correlation},
        )
        cases = [
            (valid, 200, "VALID", "INFO", "valid"),
            (valid_request(), 200, "INVALID", "INFO", "invalid"),
            (request({}), 400, "INVALID_REQUEST", "INFO", "request"),
            (valid_request(), 409, "INPUT_CHANGED", "INFO", "changed"),
            (valid_request(), 504, "STORAGE_TIMEOUT", "ERROR", "timeout"),
            (valid_request(), 502, "STORAGE_READ_FAILED", "ERROR", "storage"),
            (valid_request(), 500, "INTERNAL_ERROR", "ERROR", "internal"),
        ]

        for req, status, outcome, level, scenario in cases:
            blob = client.return_value.__enter__.return_value
            blob.download_blob.side_effect = None
            if scenario == "valid":
                blob.download_blob.return_value.readall.return_value = (
                    ROOT / "samples/valid/orders_v1.csv"
                ).read_bytes()
            elif scenario == "invalid":
                blob.download_blob.return_value.readall.return_value = (
                    ROOT / "samples/invalid/orders_invalid.csv"
                ).read_bytes()
            elif scenario in {"changed", "storage"}:
                error = HttpResponseError(message="https://secret.example/private?token=secret")
                error.status_code = 412 if scenario == "changed" else 404
                blob.download_blob.side_effect = error
            elif scenario == "timeout":
                blob.download_blob.side_effect = ServiceResponseError(
                    "secret timeout detail", error=TimeoutError()
                )
            elif scenario == "internal":
                blob.download_blob.side_effect = RuntimeError("body and secret")
            with self.subTest(outcome=outcome), self.assertLogs(level=level) as captured:
                response = HANDLER(req)
            self.assertEqual(status, response.status_code)
            self.assertEqual(1, len(captured.records))
            self.assertEqual(level, captured.records[0].levelname)
            event = json.loads(captured.records[0].getMessage())
            self.assertEqual(
                (
                    {"event", "http_status", "outcome", "pipeline_run_id"}
                    if req is valid
                    else {"event", "http_status", "outcome"}
                ),
                set(event),
            )
            self.assertEqual("csv_validation", event["event"])
            self.assertEqual(status, event["http_status"])
            self.assertEqual(outcome, event["outcome"])
            if req is valid:
                self.assertEqual(correlation.lower(), event["pipeline_run_id"])
            log_text = "\n".join(record.getMessage() for record in captured.records)
            self.assertNotIn("orders.csv", log_text)
            self.assertNotIn("secret", log_text)
            self.assertNotIn("0xABC", log_text)
            self.assertNotIn("private", log_text)
            self.assertNotIn("https://", log_text)

    def test_invalid_pipeline_run_id_is_omitted(self) -> None:
        """UUID形式でない相関ヘッダーはイベントへ含めない。"""
        req = request({}, {"x-adf-pipeline-run-id": "bad-secret-value"})
        with self.assertLogs(level="INFO") as captured:
            HANDLER(req)
        event = json.loads(captured.records[0].getMessage())
        self.assertNotIn("pipeline_run_id", event)
        log_text = "\n".join(record.getMessage() for record in captured.records)
        self.assertNotIn("bad-secret-value", log_text)

    @patch.dict(
        os.environ,
        {
            "LAB_STORAGE_ACCOUNT_NAME": "testaccount",
            "AZURE_CLIENT_ID": "test-client",
            "WEBSITE_HOSTNAME": "test.azurewebsites.net",
        },
        clear=True,
    )
    @patch("storage.ManagedIdentityCredential")
    @patch("storage.BlobClient")
    def test_azure_uses_user_assigned_identity(
        self, client: MagicMock, credential: MagicMock
    ) -> None:
        """Azureでは指定したIdentityで接続し、入力を書き換えない。"""
        blob = client.return_value.__enter__.return_value
        blob.download_blob.return_value.readall.return_value = (
            ROOT / "samples/valid/orders_v1.csv"
        ).read_bytes()
        self.assertEqual(200, HANDLER(valid_request()).status_code)
        self.assertEqual("test-client", credential.call_args.kwargs["client_id"])
        self.assertLessEqual(credential.call_args.kwargs["connection_timeout"], 5)

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_configuration_is_system_error(self) -> None:
        """アプリ設定不足はINVALIDではなく500とする。"""
        self.assertEqual(500, HANDLER(valid_request()).status_code)

    @patch.dict(
        os.environ,
        {
            "LAB_STORAGE_ACCOUNT_NAME": "testaccount",
            "WEBSITE_HOSTNAME": "test.azurewebsites.net",
            "AZURE_FUNCTIONS_ENVIRONMENT": "Production",
        },
        clear=True,
    )
    @patch("storage.AzureCliCredential")
    def test_azure_without_identity_does_not_use_cli(self, credential: MagicMock) -> None:
        """AzureでIdentity指定が欠けても開発用の認証へ切り替えない。"""
        for environment in ("Production", "Development"):
            with (
                self.subTest(environment=environment),
                patch.dict(os.environ, {"AZURE_FUNCTIONS_ENVIRONMENT": environment}),
            ):
                self.assertEqual(500, HANDLER(valid_request()).status_code)
                credential.assert_not_called()
