"""AWS入口の契約を外部API境界で確認する。"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "functions/validator"))
spec = importlib.util.spec_from_file_location("aws_handler", ROOT / "functions/aws/handler.py")
# 読込に失敗した場合はここで止め、型チェッカーにもNoneでないことを伝える。
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PipelineTests(unittest.TestCase):
    """イベント・世代固定・公開の公開境界を検査する。"""

    def test_event_keeps_literal_key_and_normalizes_etag(self):
        """EventBridgeのkeyをURLデコードしない。"""
        pipeline = module.Pipeline(
            Mock(), Mock(), Mock(), Mock(), "bucket", "table", "crawler", "job"
        )
        state = pipeline.initialize(
            {
                "source": "aws.s3",
                "detail-type": "Object Created",
                "detail": {
                    "bucket": {"name": "bucket"},
                    "object": {"key": "landing/a%20b.csv", "etag": '"abc"'},
                },
            },
            "arn:execution:1",
        )
        self.assertEqual(state["input"]["key"], "landing/a%20b.csv")
        self.assertEqual(state["input"]["etag"], "abc")
        self.assertEqual(len(state["input"]["inputId"]), 64)


class ServiceBoundaryCase(unittest.TestCase):
    """SDK境界のモックと初期状態を、境界を検査するテストクラスで共有する。"""

    def setUp(self):
        """各ケースへ独立したSDK境界を渡す。"""
        self.s3, self.table, self.glue, self.sfn = (Mock() for _ in range(4))
        self.pipeline = module.Pipeline(
            self.s3, self.table, self.glue, self.sfn, "bucket", "table", "crawler", "job"
        )
        self.state = self.pipeline.initialize(
            {"input": {"bucket": "bucket", "key": "landing/orders.csv", "etag": "abc"}},
            "execution-new",
        )
        self.state["accepted"] = True


class ServiceBoundaryTests(ServiceBoundaryCase):
    """世代条件・所有者条件・非公開失敗をAWS API境界で確認する。"""

    def test_rejects_other_bucket_and_downstream_keys(self):
        """対象外の直接実行を拒否する。"""
        for bucket, key in [
            ("other", "landing/a.csv"),
            ("bucket", "validated/a.csv"),
            ("bucket", "landing/a.txt"),
        ]:
            with self.assertRaises(module.ContractError):
                self.pipeline.initialize(
                    {"input": {"bucket": bucket, "key": key, "etag": "abc"}}, "exec"
                )

    def test_duplicate_running_does_not_write(self):
        """RUNNING重複は既存実行を返し副作用を持たない。"""
        self.table.get_item.return_value = {
            "Item": {
                "executionArn": "previous",
                "attemptId": "previous-attempt",
                "status": "RUNNING",
            }
        }
        self.sfn.describe_execution.return_value = {"status": "RUNNING"}
        result = self.pipeline.acquire(self.state)
        self.assertFalse(result["accepted"])
        self.table.put_item.assert_not_called()

    def test_completed_duplicate_does_not_force(self):
        """通常の成功重複はサービス照会も更新もしない。"""
        self.table.get_item.return_value = {
            "Item": {"executionArn": "previous", "attemptId": "old", "status": "SUCCEEDED"}
        }
        self.assertFalse(self.pipeline.acquire(self.state)["accepted"])
        self.sfn.describe_execution.assert_not_called()
        self.table.put_item.assert_not_called()

    def test_failed_retry_requires_terminal_execution_and_previous_owner(self):
        """FAILED再実行も旧実行の終端を確認して条件付きで引き継ぐ。"""
        self.table.get_item.return_value = {
            "Item": {"executionArn": "previous", "attemptId": "old", "status": "FAILED"}
        }
        self.sfn.describe_execution.return_value = {"status": "FAILED"}
        self.assertTrue(self.pipeline.acquire(self.state)["accepted"])
        call = self.table.put_item.call_args.kwargs
        self.assertEqual(call["ExpressionAttributeValues"][":previous"], "previous")
        self.assertEqual(call["ExpressionAttributeValues"][":oldAttempt"], "old")
        self.assertEqual(call["Item"]["status"], "RUNNING")

    def test_stale_successful_execution_is_not_taken_over(self):
        """RUNNING状態が成功実行と矛盾する場合は勝手に横取りしない。"""
        self.table.get_item.return_value = {
            "Item": {"executionArn": "previous", "attemptId": "old", "status": "RUNNING"}
        }
        self.sfn.describe_execution.return_value = {"status": "SUCCEEDED"}
        with self.assertRaises(module.ContractError):
            self.pipeline.acquire(self.state)
        self.table.put_item.assert_not_called()

    def test_valid_input_has_conditional_read_and_copy(self):
        """原本の読取と保存が同一ETagに固定される。"""
        import io

        content = (ROOT / "samples/valid/orders_v1.csv").read_bytes()
        self.s3.get_object.return_value = {
            "Body": io.BytesIO(content),
            "ContentLength": len(content),
        }
        result = self.pipeline.validate(self.state)
        self.assertEqual(result["validation"]["status"], "VALID")
        self.assertEqual(self.s3.get_object.call_args.kwargs["IfMatch"], '"abc"')
        self.assertEqual(self.s3.copy_object.call_args.kwargs["CopySourceIfMatch"], '"abc"')
        self.assertGreater(result["validation"]["inputRows"], 0)
        self.assertNotIn("errors", result["validation"])

    def test_oversized_input_rejected_without_unbounded_read(self):
        """上限超過を共通Rejectとして原本・JSON保存後に確定する。"""
        import io

        stream = io.BytesIO(b"a" * (module.MAX_BYTES + 100))
        self.s3.get_object.return_value = {"Body": stream, "ContentLength": module.MAX_BYTES + 100}
        result = self.pipeline.validate(self.state)
        self.assertEqual(result["validation"]["status"], "INVALID")
        calls = self.table.update_item.call_args_list
        self.assertEqual(calls[-1].kwargs["ExpressionAttributeValues"][":status"], "REJECTED")
        self.assertIn("executionArn = :execution", calls[-1].kwargs["ConditionExpression"])

    def test_reject_save_failure_never_marks_rejected(self):
        """Reject証跡が保存できない場合は業務成功にしない。"""
        import io

        self.s3.get_object.return_value = {"Body": io.BytesIO(b""), "ContentLength": 0}
        self.s3.put_object.side_effect = RuntimeError("storage failed")
        with self.assertRaises(RuntimeError):
            self.pipeline.validate(self.state)
        self.table.update_item.assert_not_called()

    def test_running_glue_keeps_lock_even_when_crawler_ready(self):
        """実行中Glueを残して共有ロックを解放しない。"""
        lock = self.state["attempt"] | {"gluePending": True, "jobRunId": "jr1"}
        self.table.get_item.return_value = {"Item": lock}
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        self.glue.get_job_run.return_value = {"JobRun": {"JobRunState": "RUNNING"}}
        with self.assertRaises(module.ContractError):
            self.pipeline.release(self.state)
        self.table.delete_item.assert_not_called()

    def test_uncertain_glue_start_keeps_lock(self):
        """開始応答消失後のjobが見つからなければ排他を維持する。"""
        self.table.get_item.return_value = {"Item": self.state["attempt"] | {"gluePending": True}}
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        self.glue.get_job_runs.return_value = {"JobRuns": []}
        with self.assertRaises(module.ContractError):
            self.pipeline.release(self.state)
        self.table.delete_item.assert_not_called()

    def test_record_glue_accepts_sync_result_id_and_records_owned_lock(self):
        """同期Glue応答のIdを変換ロックへ所有者条件付きで記録する。"""
        self.state["transform"] = {"stagingPrefix": "staging/"}
        self.state["glueResult"] = {
            "Id": "jr-sync",
            "JobName": "job",
            "JobRunState": "SUCCEEDED",
        }

        result = self.pipeline.record_glue(self.state)

        self.assertEqual(result["transform"]["jobRunId"], "jr-sync")
        update = self.table.update_item.call_args.kwargs
        self.assertEqual(update["Key"], {"inputId": "__transform_lock__"})
        self.assertEqual(update["ExpressionAttributeValues"][":run"], "jr-sync")
        self.assertEqual(update["ExpressionAttributeValues"][":execution"], "execution-new")
        self.assertIn("attemptId = :attempt", update["ConditionExpression"])

    def test_record_glue_prefers_id_then_accepts_legacy_keys(self):
        """新しいIdを優先しつつ旧応答キーも受け入れる。"""
        for glue_result, expected in (
            ({"Id": "jr-id", "JobRunId": "jr-lower", "JobRunID": "jr-upper"}, "jr-id"),
            ({"JobRunId": "jr-lower", "JobRunID": "jr-upper"}, "jr-lower"),
            ({"JobRunID": "jr-upper"}, "jr-upper"),
        ):
            with self.subTest(glue_result=glue_result):
                self.table.update_item.reset_mock()
                result = self.pipeline.record_glue(
                    self.state
                    | {"transform": {"stagingPrefix": "staging/"}, "glueResult": glue_result}
                )
                self.assertEqual(result["transform"]["jobRunId"], expected)
                self.assertEqual(
                    self.table.update_item.call_args.kwargs["ExpressionAttributeValues"][":run"],
                    expected,
                )

    def test_record_glue_rejects_empty_or_missing_run_id_without_writes(self):
        """空または欠損した実行IDは契約エラーにしロックを書き換えない。"""
        for glue_result in ({"Id": "", "JobRunId": "", "JobRunID": ""}, {}):
            with self.subTest(glue_result=glue_result):
                self.table.update_item.reset_mock()
                with self.assertRaisesRegex(module.ContractError, "MISSING_GLUE_RUN_ID"):
                    self.pipeline.record_glue(self.state | {"glueResult": glue_result})
                self.table.update_item.assert_not_called()

    def test_old_attempt_cannot_release_new_lock(self):
        """旧attemptの完了が新attemptのロックを削除しない。"""
        self.table.get_item.return_value = {"Item": {"attemptId": "other", "executionArn": "other"}}
        with self.assertRaises(module.OwnershipLost):
            self.pipeline.release(self.state)
        self.table.delete_item.assert_not_called()

    def test_cleanup_does_not_overwrite_committed_success(self):
        """公開応答消失時も成功世代をFAILEDに書き換えない。"""
        from botocore.exceptions import ClientError

        self.table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
        )
        self.table.get_item.return_value = {}
        self.pipeline.cleanup(self.state)
        self.assertIn(
            "#status = :running", self.table.update_item.call_args.kwargs["ConditionExpression"]
        )

    def publish_fixture(self):
        """公開検査用の既知行数と実体を設定する。"""
        import hashlib
        import io
        import json

        state = self.state | {
            "validation": {"inputRows": 1, "key": "validated/result.json"},
            "transform": {"stagingPrefix": "staging/id/attempt/", "jobRunId": "jr1"},
        }
        content = b"orderId,amount\nA1,1.0000\n"
        manifest = {
            "inputId": state["input"]["inputId"],
            "attemptId": state["attempt"]["attemptId"],
            "inputRows": 1,
            "outputRows": 1,
            "files": [
                {
                    "key": "staging/id/attempt/part-0.csv",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        }
        self.s3.get_object.side_effect = [
            {"Body": io.BytesIO(json.dumps(manifest).encode())},
            {"Body": io.BytesIO(content), "ETag": '"part-etag"'},
        ]
        self.s3.head_object.return_value = {"ETag": '"abc"'}
        return state

    def test_partial_copy_failure_never_publishes(self):
        """part配置途中の失敗でmanifestやSUCCESSを公開しない。"""
        state = self.publish_fixture()
        self.s3.copy_object.side_effect = RuntimeError("copy failed")
        with self.assertRaises(RuntimeError):
            self.pipeline.publish(state)
        self.s3.put_object.assert_not_called()
        self.table.update_item.assert_not_called()

    def test_input_changed_never_publishes(self):
        """公開直前の世代不一致は部分出力を未公開に保つ。"""
        state = self.publish_fixture()
        self.s3.head_object.return_value = {"ETag": '"new"'}
        with self.assertRaises(module.InputChanged):
            self.pipeline.publish(state)
        self.s3.put_object.assert_not_called()
        self.table.update_item.assert_not_called()

    def test_publish_commits_manifest_after_parts_with_owner_condition(self):
        """全part配置後のmanifestだけを所有者条件付きで公開する。"""
        state = self.publish_fixture()
        result = self.pipeline.publish(state)
        self.assertTrue(result["publication"]["key"].endswith("manifest.json"))
        update = self.table.update_item.call_args.kwargs
        self.assertEqual(update["ExpressionAttributeValues"][":status"], "SUCCEEDED")
        self.assertIn("attemptId = :attempt", update["ConditionExpression"])
        self.assertIn("#status = :running", update["ConditionExpression"])


class WorkflowContractTests(unittest.TestCase):
    """サービス開始の再送と公開後の失敗経路を状態機械で確認する。"""

    def setUp(self):
        """ASLテンプレートの数値と参照だけをローカル値に置換する。"""
        import json

        source = (
            (ROOT / "workflows/aws/pipeline.asl.json")
            .read_text()
            .replace("${workflow_timeout_seconds}", "1800")
        )
        self.workflow = json.loads(source)
        self.states = self.workflow["States"]

    def test_side_effect_start_and_publish_do_not_have_blind_retry(self):
        """不確定な開始・公開は無条件に再送しない。"""
        for name in ["StartCrawler", "Glue", "Publish"]:
            self.assertNotIn("Retry", self.states[name])
        self.assertEqual(self.states["Glue"]["Resource"], "arn:aws:states:::glue:startJobRun.sync")

    def test_reject_is_success_and_shared_lock_is_not_acquired(self):
        """業務Rejectは共有変換に入らず正常終了する。"""
        choice = next(
            item
            for item in self.states["Validation"]["Choices"]
            if item["StringEquals"] == "INVALID"
        )
        self.assertEqual(choice["Next"], "Done")
        self.assertEqual(self.states["Done"]["Type"], "Succeed")

    def test_post_publication_failure_never_enters_cleanup(self):
        """公開後の掃除失敗は成功世代を失敗にしない。"""
        for name in ["Release", "CleanStaging"]:
            self.assertEqual(self.states[name]["Catch"][0]["Next"], "Failed")
        self.assertEqual(self.states["Publish"]["Next"], "Release")

    def test_all_transitions_have_targets_and_shared_wait_is_bounded(self):
        """遷移先が存在し、全体と共有待機に有限の上限を持つ。"""
        self.assertEqual(self.workflow["TimeoutSeconds"], 1800)
        for state in self.states.values():
            targets = [state.get("Next"), state.get("Default")]
            targets += [item["Next"] for item in state.get("Choices", []) + state.get("Catch", [])]
            for target in filter(None, targets):
                self.assertIn(target, self.states)
        self.assertEqual(self.states["WaitLock"]["Next"], "Lock")


class RecoveryRegressionTests(ServiceBoundaryCase):
    """起動拒否と開始不確定を区別する回帰検査。"""

    def test_crawler_denied_start_clears_pending_with_owner_condition(self):
        """StartCrawlerの明確な未開始拒否は復旧を妨げない。"""
        from botocore.exceptions import ClientError

        self.state["validation"] = {"sourceKey": "validated/id/attempt/source.csv"}
        self.table.get_item.return_value = {
            "Item": self.state["attempt"] | {"crawlerPending": False}
        }
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        self.glue.start_crawler.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException"}}, "StartCrawler"
        )
        with self.assertRaises(ClientError):
            self.pipeline.start_crawler(self.state)
        call = self.table.update_item.call_args.kwargs
        self.assertEqual(call["ExpressionAttributeValues"][":no"], False)
        self.assertIn("attemptId = :attempt", call["ConditionExpression"])

    def test_glue_start_authorization_rejection_allows_cleanup(self):
        """StartJobRunの明確な拒否だけが未開始確認になる。"""
        self.table.get_item.return_value = {"Item": self.state["attempt"] | {"gluePending": True}}
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        self.state["failure"] = {
            "Error": "Glue.AccessDeniedException",
            "Cause": "is not authorized to perform glue:StartJobRun on resource job",
        }
        self.pipeline.cleanup(self.state)
        self.table.delete_item.assert_called_once()

    def test_glue_poll_authorization_failure_does_not_clear_pending(self):
        """GetJobRun拒否は開始済みjobの不存在を示さない。"""
        self.table.get_item.return_value = {"Item": self.state["attempt"] | {"gluePending": True}}
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        self.glue.get_job_runs.return_value = {"JobRuns": []}
        self.state["failure"] = {
            "Error": "Glue.AccessDeniedException",
            "Cause": "is not authorized to perform glue:GetJobRun on resource job",
        }
        self.pipeline.cleanup(self.state)
        self.table.delete_item.assert_not_called()

    def test_crawler_uncertain_start_keeps_lock(self):
        """応答消失後の未確認Crawler開始は横取りしない。"""
        self.table.get_item.return_value = {
            "Item": self.state["attempt"]
            | {"crawlerPending": True, "crawlerStarted": 1, "crawlerPrevious": ""}
        }
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        with self.assertRaises(module.ContractError):
            self.pipeline.release(self.state)
        self.table.delete_item.assert_not_called()


class RetryReviewTests(ServiceBoundaryCase):
    """開始前の安全な復旧と通信障害分類を公開境界で検査する。"""

    def test_prepare_failure_clears_pending_before_glue_can_start(self):
        """準備Lambdaが書込み後に応答を失ってもロックを残さない。"""
        self.table.get_item.return_value = {"Item": self.state["attempt"] | {"gluePending": True}}
        self.glue.get_crawler.return_value = {"Crawler": {"State": "READY"}}
        self.state["glueNotStarted"] = True
        self.pipeline.cleanup(self.state)
        self.table.delete_item.assert_called_once()
        self.glue.get_job_runs.assert_not_called()
        update = self.table.update_item.call_args.kwargs
        self.assertEqual(update["ExpressionAttributeValues"][":no"], False)
        self.assertIn("attemptId = :attempt", update["ConditionExpression"])

    def test_prepare_failure_path_marks_unstarted_but_glue_failure_does_not(self):
        """ASLの準備失敗だけが未開始と確定する。"""
        import json

        source = (ROOT / "workflows/aws/pipeline.asl.json").read_text()
        states = json.loads(source.replace("${workflow_timeout_seconds}", "1800"))["States"]
        target = states["PrepareGlue"]["Catch"][0]["Next"]
        self.assertEqual(states[target]["ResultPath"], "$.glueNotStarted")
        self.assertTrue(states[target]["Result"])
        self.assertEqual(states[target]["Next"], "Cleanup")
        self.assertEqual(states["Glue"]["Catch"][0]["Next"], "Cleanup")

    def test_handler_retries_safe_sdk_errors_but_never_restarts_side_effects(self):
        """通信断とSlowDownは安全な操作だけの再試行対象になる。"""
        from unittest.mock import patch

        from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

        errors = [
            ConnectTimeoutError(endpoint_url="https://example.invalid"),
            ReadTimeoutError(endpoint_url="https://example.invalid"),
            ClientError({"Error": {"Code": "SlowDown"}}, "ListObjectsV2"),
        ]
        env = {
            "BUCKET_NAME": "bucket",
            "STATE_TABLE": "table",
            "CRAWLER_NAME": "crawler",
            "GLUE_JOB_NAME": "job",
        }
        for operation in [
            "validate",
            "poll_crawler",
            "prepare_glue",
            "clean_staging",
            "start_crawler",
            "publish",
        ]:
            for error in errors:
                expected = (
                    module.ServiceFailure
                    if operation in ("start_crawler", "publish")
                    else module.TransientServiceError
                )
                with (
                    self.subTest(operation=operation, error=type(error).__name__),
                    patch.dict(module.os.environ, env),
                    patch.object(module.boto3, "client"),
                    patch.object(module.boto3, "resource"),
                    patch.object(module, "Pipeline") as pipeline,
                ):
                    getattr(pipeline.return_value, operation).side_effect = error
                    with self.assertRaises(expected):
                        module.handler({"operation": operation, "state": {}}, None)

    def test_handler_logs_identifiers_and_error_code_without_content(self):
        """操作ごとに識別子と結果codeだけを1行のJSONで記録する。"""
        import contextlib
        import io
        import json
        from unittest.mock import patch

        env = {
            "BUCKET_NAME": "bucket",
            "STATE_TABLE": "table",
            "CRAWLER_NAME": "crawler",
            "GLUE_JOB_NAME": "job",
        }
        state = {
            "input": {"bucket": "bucket", "key": "landing/a.csv", "etag": "e", "inputId": "i" * 64},
            "attempt": {"attemptId": "attempt", "executionArn": "arn:execution"},
            "transform": {"jobRunId": "jr_1"},
            "csv": "order_id,secret-content",
        }
        with (
            patch.dict(module.os.environ, env),
            patch.object(module.boto3, "client"),
            patch.object(module.boto3, "resource"),
            patch.object(module, "Pipeline") as pipeline,
        ):
            pipeline.return_value.publish.return_value = state
            pipeline.return_value.release.side_effect = module.ContractError(
                "SERVICES_STILL_RUNNING"
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                module.handler({"operation": "publish", "state": state}, None)
                with self.assertRaises(module.ContractError):
                    module.handler({"operation": "release", "state": state}, None)
        success, failure = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            success,
            {
                "operation": "publish",
                "outcome": "ok",
                "inputId": "i" * 64,
                "attemptId": "attempt",
                "executionArn": "arn:execution",
                "jobRunId": "jr_1",
            },
        )
        self.assertEqual(failure["outcome"], "error")
        self.assertEqual(failure["code"], "SERVICES_STILL_RUNNING")
        self.assertNotIn("secret-content", output.getvalue())
        self.assertNotIn("landing/a.csv", output.getvalue())

    def test_handler_logs_glue_run_id_after_record_and_cleanup_failures(self):
        """記録更新失敗と後続CleanupでもGlue実行IDを本文なしで記録する。"""
        import contextlib
        import io
        import json
        from unittest.mock import patch

        from botocore.exceptions import ClientError

        env = {
            "BUCKET_NAME": "bucket",
            "STATE_TABLE": "table",
            "CRAWLER_NAME": "crawler",
            "GLUE_JOB_NAME": "job",
        }
        for spelling, run_id in (
            ("Id", "jr-id"),
            ("JobRunId", "jr-lower"),
            ("JobRunID", "jr-upper"),
        ):
            for error_code, expected_error, logged_code in (
                ("InternalServerError", module.TransientServiceError, "InternalServerError"),
                ("ConditionalCheckFailedException", module.OwnershipLost, "OWNER_CHANGED"),
            ):
                with self.subTest(spelling=spelling, code=error_code):
                    s3, glue, sfn, table = (Mock() for _ in range(4))
                    table.update_item.side_effect = [
                        ClientError({"Error": {"Code": error_code}}, "UpdateItem"),
                        {},
                    ]
                    table.get_item.return_value = {}
                    sdk_clients = {"s3": s3, "glue": glue, "stepfunctions": sfn}
                    state = {
                        "input": {
                            "bucket": "bucket",
                            "key": "landing/private.csv",
                            "etag": "etag-secret",
                            "inputId": "i" * 64,
                        },
                        "attempt": {"attemptId": "attempt", "executionArn": "arn:execution"},
                        "accepted": True,
                        "transform": {"stagingPrefix": "staging/private/"},
                        "glueResult": {
                            spelling: run_id,
                            **(
                                {"JobRunId": "legacy-lower", "JobRunID": "legacy-upper"}
                                if spelling == "Id"
                                else {}
                            ),
                            "Result": "private-result",
                        },
                        "csv": "private-csv-body",
                    }
                    output = io.StringIO()
                    with (
                        patch.dict(module.os.environ, env),
                        patch.object(
                            module.boto3,
                            "client",
                            side_effect=lambda name, clients=sdk_clients, **_: clients[name],
                        ),
                        patch.object(module.boto3, "resource") as resource,
                        contextlib.redirect_stdout(output),
                    ):
                        resource.return_value.Table.return_value = table
                        with self.assertRaises(expected_error):
                            module.handler({"operation": "record_glue", "state": state}, None)
                        self.assertNotIn("jobRunId", state["transform"])
                        state["failure"] = {"Error": logged_code, "Cause": "private-cause"}
                        module.handler({"operation": "cleanup", "state": state}, None)
                    failure, cleanup = [json.loads(line) for line in output.getvalue().splitlines()]
                    self.assertEqual(failure["jobRunId"], run_id)
                    self.assertEqual(failure["outcome"], "error")
                    self.assertEqual(failure["code"], logged_code)
                    self.assertEqual(cleanup["jobRunId"], run_id)
                    self.assertEqual(cleanup["outcome"], "ok")
                    self.assertNotIn("code", cleanup)
                    self.assertEqual(table.update_item.call_count, 2)
                    for private_value in (
                        "private.csv",
                        "etag-secret",
                        "private-result",
                        "private-csv-body",
                        "private-cause",
                    ):
                        self.assertNotIn(private_value, output.getvalue())

        output = io.StringIO()
        state = {"transform": {"jobRunId": "preferred"}, "glueResult": {"JobRunId": "fallback"}}
        with contextlib.redirect_stdout(output):
            module._log_operation("cleanup", {"state": state}, None, None)
        self.assertEqual(json.loads(output.getvalue())["jobRunId"], "preferred")

    def test_handler_records_and_logs_sync_glue_result_id(self):
        """公開handlerが同期応答のIdを記録し、ログにも同じIDを出す。"""
        import contextlib
        import io
        import json
        from unittest.mock import patch

        env = {
            "BUCKET_NAME": "bucket",
            "STATE_TABLE": "table",
            "CRAWLER_NAME": "crawler",
            "GLUE_JOB_NAME": "job",
        }
        s3, glue, sfn = (Mock() for _ in range(3))
        table = Mock()
        sdk_clients = {"s3": s3, "glue": glue, "stepfunctions": sfn}
        state = {
            "input": {"bucket": "bucket", "key": "landing/a.csv", "etag": "e", "inputId": "i"},
            "attempt": {"attemptId": "attempt", "executionArn": "arn:execution"},
            "accepted": True,
            "transform": {"stagingPrefix": "staging/id/attempt/"},
            "glueResult": {
                "Id": "jr-id",
                "JobRunId": "jr-lower",
                "JobRunID": "jr-upper",
                "JobName": "job",
                "JobRunState": "SUCCEEDED",
            },
        }
        output = io.StringIO()
        with (
            patch.dict(module.os.environ, env),
            patch.object(
                module.boto3,
                "client",
                side_effect=lambda name, clients=sdk_clients, **_: clients[name],
            ),
            patch.object(module.boto3, "resource") as resource,
            contextlib.redirect_stdout(output),
        ):
            resource.return_value.Table.return_value = table
            result = module.handler({"operation": "record_glue", "state": state}, None)

        self.assertEqual(result["transform"]["jobRunId"], "jr-id")
        self.assertEqual(
            table.update_item.call_args.kwargs["ExpressionAttributeValues"][":run"], "jr-id"
        )
        self.assertEqual(json.loads(output.getvalue())["jobRunId"], "jr-id")


if __name__ == "__main__":
    unittest.main()
