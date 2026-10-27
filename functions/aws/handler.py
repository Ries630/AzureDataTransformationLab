"""AWSサービス境界と世代所有権を接続するLambda入口。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
from datetime import UTC, datetime

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
    ResponseStreamingError,
)
from validation import MAX_BYTES, validate_csv

# 同じ所有者条件で安全に繰り返せる操作だけを再試行する。
RETRYABLE_OPERATIONS = frozenset(
    {
        "initialize",
        "acquire",
        "validate",
        "lock",
        "poll_crawler",
        "prepare_glue",
        "record_glue",
        "release",
        "clean_staging",
        "cleanup",
    }
)


class ContractError(Exception):
    """処理契約または公開条件の違反。"""


class InputChanged(Exception):
    """入力世代が変わったため継続できない。"""


class OwnershipLost(Exception):
    """旧attemptには処理状態を更新する権限がない。"""


class TransientServiceError(Exception):
    """副作用を重ねず再試行できる一時障害。"""


class ServiceFailure(Exception):
    """サービス操作が完了できなかった。"""


class OwnedBucket:
    """固定bucketへのSDK操作に会社所有者の照合条件を付ける。"""

    def __init__(self, client):
        """S3クライアントと会社設定の所有者を保持する。"""
        self.client = client
        self.owner = os.environ.get("EXPECTED_BUCKET_OWNER")

    def __getattr__(self, operation):
        """すべてのS3操作へ対象bucketの所有者条件を渡す。"""

        def call(**kwargs):
            """コピー元にも同じ所有者照合条件を設定する。"""
            if self.owner:
                kwargs["ExpectedBucketOwner"] = self.owner
                if operation == "copy_object":
                    kwargs["ExpectedSourceBucketOwner"] = self.owner
            return getattr(self.client, operation)(**kwargs)

        return call


def digest(value):
    """衝突しないJSON表現から識別子を作る。"""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def utc_now():
    """監査用時刻をUTCで返す。"""
    return datetime.now(UTC).isoformat()


class Pipeline:
    """SDKクライアントを境界とする入力受付・検証・公開処理。"""

    def __init__(self, s3, table, glue, sfn, bucket, table_name, crawler, job):
        """固定された実行環境と外部サービスを受け取る。"""
        self.s3, self.table, self.glue, self.sfn = OwnedBucket(s3), table, glue, sfn
        self.bucket, self.table_name, self.crawler, self.job = bucket, table_name, crawler, job
        self.prefix = os.environ.get("DATA_PREFIX", "")

    def initialize(self, event, execution_arn):
        """直接実行とEventBridgeを区別して入力参照を正規化する。"""
        automatic = event.get("source") == "aws.s3"
        if automatic:
            if event.get("detail-type") != "Object Created" or event.get("force"):
                raise ContractError("INVALID_EVENT")
            ref = {
                "bucket": event.get("detail", {}).get("bucket", {}).get("name"),
                "key": event.get("detail", {}).get("object", {}).get("key"),
                "etag": event.get("detail", {}).get("object", {}).get("etag"),
            }
        else:
            ref = dict(event.get("input", {}))
            if type(event.get("force", False)) is not bool:
                raise ContractError("INVALID_FORCE")
        if set(ref) != {"bucket", "key", "etag"} or ref["bucket"] != self.bucket:
            raise ContractError("INVALID_REFERENCE")
        if (
            not isinstance(ref["key"], str)
            or not ref["key"].startswith(self.prefix + "landing/")
            or not ref["key"].endswith(".csv")
        ):
            raise ContractError("INVALID_KEY")
        if not isinstance(ref["etag"], str) or not ref["etag"].strip('"'):
            raise ContractError("INVALID_ETAG")
        ref["etag"] = ref["etag"].strip('"')
        ref["inputId"] = digest([ref["bucket"], ref["key"], ref["etag"]])
        return {
            "input": ref,
            "attempt": {"attemptId": digest(execution_arn), "executionArn": execution_arn},
            "force": event.get("force", False) if not automatic else False,
            "dataPrefix": self.prefix,
        }

    def _key(self, state):
        """世代状態itemの主キーを返す。"""
        return {"inputId": state["input"]["inputId"]}

    def _owner(self, state):
        """所有者一致を条件にする値を返す。"""
        return {
            ":execution": state["attempt"]["executionArn"],
            ":attempt": state["attempt"]["attemptId"],
        }

    def _owned_update(self, state, expression, values=None, names=None, key=None, running=False):
        """古いattemptによる状態更新を条件式で拒否する。"""
        condition = "executionArn = :execution AND attemptId = :attempt"
        if running:
            condition += " AND #status = :running"
            values = (values or {}) | {":running": "RUNNING"}
            names = (names or {}) | {"#status": "status"}
        self.table.update_item(
            Key=key or self._key(state),
            UpdateExpression=expression,
            ConditionExpression=condition,
            ExpressionAttributeValues=self._owner(state) | (values or {}),
            **({"ExpressionAttributeNames": names} if names else {}),
        )

    def _terminal(self, arn):
        """経過時間ではなく実行サービスの状態を確認する。"""
        return self.sfn.describe_execution(executionArn=arn)["status"]

    def acquire(self, state, conflicts=0):
        """重複をno-opにし、終端済み世代だけ条件付きで引き継ぐ。"""
        if conflicts >= 5:
            raise TransientServiceError("CONCURRENT_ACQUISITION")
        existing = self.table.get_item(Key=self._key(state), ConsistentRead=True).get("Item")
        item = (
            self._key(state)
            | state["input"]
            | state["attempt"]
            | {"status": "RUNNING", "updatedAt": utc_now()}
        )
        if not existing:
            try:
                self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(inputId)")
                return state | {"accepted": True}
            except ClientError as error:
                if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
                return self.acquire(state, conflicts + 1)
        # 自身のLambda応答消失後も受付を継続できる。
        if (
            existing["executionArn"] == state["attempt"]["executionArn"]
            and existing["attemptId"] == state["attempt"]["attemptId"]
        ):
            return state | {"accepted": existing["status"] == "RUNNING"}
        status = existing["status"]
        if status in ("SUCCEEDED", "REJECTED") and not state["force"]:
            return state | {
                "accepted": False,
                "existing": {"status": status, "executionArn": existing["executionArn"]},
            }
        previous = self._terminal(existing["executionArn"])
        if previous == "RUNNING":
            return state | {
                "accepted": False,
                "existing": {"status": status, "executionArn": existing["executionArn"]},
            }
        if status == "RUNNING" and previous not in ("FAILED", "TIMED_OUT", "ABORTED"):
            raise ContractError("INCONSISTENT_EXECUTION")
        if status not in ("RUNNING", "FAILED", "SUCCEEDED", "REJECTED"):
            raise ContractError("UNKNOWN_STATUS")
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=(
                    "executionArn = :previous AND attemptId = :oldAttempt AND #status = :status"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":previous": existing["executionArn"],
                    ":oldAttempt": existing["attemptId"],
                    ":status": status,
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            return self.acquire(state, conflicts + 1)
        return state | {"accepted": True}

    def validate(self, state):
        """条件付きで原本を読み、判定と固定原本を同じattemptへ保存する。"""
        ref = state["input"]
        response = self.s3.get_object(
            Bucket=self.bucket, Key=ref["key"], IfMatch='"' + ref["etag"] + '"'
        )
        body = response["Body"]
        try:
            content = body.read(MAX_BYTES + 1)
        finally:
            body.close()
        if response["ContentLength"] > MAX_BYTES:
            content = b" " * (MAX_BYTES + 1)
        result = validate_csv(content, ref["key"])
        if result["status"] not in ("VALID", "INVALID"):
            raise ContractError("UNKNOWN_VALIDATION_STATUS")
        prefix = (
            self.prefix
            + ("validated" if result["status"] == "VALID" else "rejected")
            + "/"
            + ref["inputId"]
            + "/"
            + state["attempt"]["attemptId"]
            + "/"
        )
        self.s3.copy_object(
            Bucket=self.bucket,
            Key=prefix + "source.csv",
            CopySource={"Bucket": self.bucket, "Key": ref["key"]},
            CopySourceIfMatch='"' + ref["etag"] + '"',
        )
        self.s3.put_object(
            Bucket=self.bucket,
            Key=prefix + "validation.json",
            Body=json.dumps(result, ensure_ascii=False).encode(),
            ContentType="application/json",
        )
        validation = {
            "status": result["status"],
            "errorCount": result["errorCount"],
            "bucket": self.bucket,
            "key": prefix + "validation.json",
            "sourceKey": prefix + "source.csv",
        }
        if result["status"] == "VALID":
            validation["inputRows"] = (
                len(list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))) - 1
            )
        self._owned_update(
            state,
            "SET validation = :validation, updatedAt = :now",
            {":validation": validation, ":now": utc_now()},
        )
        if result["status"] == "INVALID":
            self._owned_update(
                state, "SET #status = :status", {":status": "REJECTED"}, {"#status": "status"}
            )
        return state | {"validation": validation}

    def lock(self, state):
        """共有Crawler・Catalog区間の排他を取得し、待機期限を守る。"""
        started = state.get("lockStarted", int(time.time()))
        if time.time() - started > int(os.environ.get("LOCK_WAIT_SECONDS", "900")):
            raise ContractError("LOCK_TIMEOUT")
        key = {"inputId": "__transform_lock__"}
        item = (
            key
            | state["attempt"]
            | {
                "ownerInputId": state["input"]["inputId"],
                "crawlerPending": False,
                "gluePending": False,
            }
        )
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(inputId)")
            return state | {"locked": True, "lockStarted": started}
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        previous = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
        if (
            previous
            and previous["attemptId"] == state["attempt"]["attemptId"]
            and previous["executionArn"] == state["attempt"]["executionArn"]
        ):
            return state | {"locked": True, "lockStarted": started}
        # ロックの復旧は明示されたrecover操作だけで行う。
        return state | {"locked": False, "lockStarted": started}

    def start_crawler(self, state):
        """起動を記録してから一度だけCrawlerを起動する。"""
        key = {"inputId": "__transform_lock__"}
        owner = self.table.get_item(Key=key, ConsistentRead=True)["Item"]
        if (
            owner["attemptId"] != state["attempt"]["attemptId"]
            or owner["executionArn"] != state["attempt"]["executionArn"]
        ):
            raise OwnershipLost("LOCK_OWNER_CHANGED")
        if owner.get("crawlerPending"):
            raise ContractError("CRAWLER_START_UNCERTAIN")
        info = self.glue.get_crawler(Name=self.crawler)["Crawler"]
        if info["State"] != "READY":
            raise ContractError("CRAWLER_NOT_READY")
        self.glue.update_crawler(
            Name=self.crawler,
            Targets={
                "S3Targets": [
                    {
                        "Path": "s3://"
                        + self.bucket
                        + "/"
                        + state["validation"]["sourceKey"].rsplit("/", 1)[0]
                        + "/",
                        "Exclusions": ["**/validation.json"],
                    }
                ]
            },
        )
        started = int(time.time())
        previous = str(info.get("LastCrawl", {}).get("StartTime", ""))
        self._owned_update(
            state,
            "SET crawlerPending = :yes, crawlerStarted = :started, crawlerPrevious = :previous",
            {":yes": True, ":started": started, ":previous": previous},
            key=key,
        )
        try:
            self.glue.start_crawler(Name=self.crawler)
        except ClientError as error:
            # サーバーが明確に起動を拒否した場合は不確定開始として残さない。
            if error.response["Error"]["Code"] in (
                "AccessDeniedException",
                "EntityNotFoundException",
                "InvalidInputException",
            ):
                self._owned_update(state, "SET crawlerPending = :no", {":no": False}, key=key)
            raise
        return state | {"crawlerStarted": started, "crawlerPrevious": previous}

    def poll_crawler(self, state):
        """今回のCrawler完了とLastCrawl成功を照合する。"""
        info = self.glue.get_crawler(Name=self.crawler)["Crawler"]
        if time.time() - state["crawlerStarted"] > int(
            os.environ.get("CRAWLER_WAIT_SECONDS", "600")
        ):
            raise ContractError("CRAWLER_TIMEOUT")
        crawl = info.get("LastCrawl", {})
        if info["State"] != "READY":
            return state | {"crawlerDone": False}
        if (
            not crawl.get("StartTime")
            or str(crawl["StartTime"]) == state["crawlerPrevious"]
            or crawl["StartTime"].timestamp() < state["crawlerStarted"]
            or crawl.get("Status") != "SUCCEEDED"
        ):
            raise ContractError("CRAWLER_FAILED")
        return state | {"crawlerDone": True}

    def prepare_glue(self, state):
        """副作用の開始前にロックへ不確定起動を記録する。"""
        prefix = (
            self.prefix
            + "staging/"
            + state["input"]["inputId"]
            + "/"
            + state["attempt"]["attemptId"]
            + "/"
        )
        self._owned_update(
            state, "SET gluePending = :yes", {":yes": True}, key={"inputId": "__transform_lock__"}
        )
        return state | {"transform": {"stagingPrefix": prefix}}

    def record_glue(self, state):
        """同期サービス連携で完了したjobの識別子を固定する。"""
        run_id = (
            state["glueResult"].get("Id")
            or state["glueResult"].get("JobRunId")
            or state["glueResult"].get("JobRunID")
        )
        if not isinstance(run_id, str) or not run_id:
            raise ContractError("MISSING_GLUE_RUN_ID")
        self._owned_update(
            state, "SET jobRunId = :run", {":run": run_id}, key={"inputId": "__transform_lock__"}
        )
        return state | {"transform": state["transform"] | {"jobRunId": run_id}}

    def publish(self, state):
        """全partを検査・コピーし、最後に所有者条件付きで公開する。"""
        prefix = state["transform"]["stagingPrefix"]
        raw = self.s3.get_object(Bucket=self.bucket, Key=prefix + "manifest.json")["Body"]
        try:
            payload = raw.read(MAX_BYTES + 1)
        finally:
            raw.close()
        if len(payload) > MAX_BYTES:
            raise ContractError("MANIFEST_TOO_LARGE")
        manifest = json.loads(payload)
        if (
            manifest["inputId"] != state["input"]["inputId"]
            or manifest["attemptId"] != state["attempt"]["attemptId"]
        ):
            raise ContractError("MANIFEST_OWNER_MISMATCH")
        if (
            type(manifest["inputRows"]) is not int
            or manifest["inputRows"] < 1
            or manifest["inputRows"] > 1000
            or manifest["inputRows"] != manifest["outputRows"]
        ):
            raise ContractError("ROW_LOSS")
        if manifest["inputRows"] != state["validation"]["inputRows"]:
            raise ContractError("SOURCE_ROW_MISMATCH")
        files = manifest["files"]
        if not isinstance(files, list) or not files or len(files) > 1000:
            raise ContractError("INVALID_PARTS")
        output = (
            self.prefix
            + "output/"
            + state["input"]["inputId"]
            + "/"
            + state["attempt"]["attemptId"]
            + "/"
        )
        keys = set()
        published = []
        total_size = 0
        actual_rows = 0
        header = None
        for part in files:
            key = part["key"]
            if (
                not isinstance(key, str)
                or not key.startswith(prefix)
                or not key.endswith(".csv")
                or "/" in key[len(prefix) :]
                or key in keys
            ):
                raise ContractError("INVALID_PART_KEY")
            keys.add(key)
            obj = self.s3.get_object(Bucket=self.bucket, Key=key)
            body = obj["Body"]
            try:
                content = body.read(8 * MAX_BYTES + 1)
            finally:
                body.close()
            total_size += len(content)
            if (
                total_size > 8 * MAX_BYTES
                or len(content) != part["size"]
                or hashlib.sha256(content).hexdigest() != part["sha256"]
            ):
                raise ContractError("PART_INTEGRITY")
            records = list(
                csv.reader(io.StringIO(content.decode("utf-8"), newline=""), strict=True)
            )
            if not records or any(len(row) != len(records[0]) for row in records[1:]):
                raise ContractError("OUTPUT_CSV_STRUCTURE")
            if header is not None and header != records[0]:
                raise ContractError("PART_SCHEMA_MISMATCH")
            header = records[0]
            actual_rows += len(records) - 1
            dest = output + key[len(prefix) :]
            self.s3.copy_object(
                Bucket=self.bucket,
                Key=dest,
                CopySource={"Bucket": self.bucket, "Key": key},
                CopySourceIfMatch=obj["ETag"],
            )
            published.append(part | {"key": dest})
        if actual_rows != manifest["outputRows"]:
            raise ContractError("OUTPUT_ROW_MISMATCH")
        current = self.s3.head_object(Bucket=self.bucket, Key=state["input"]["key"])
        if current["ETag"].strip('"') != state["input"]["etag"]:
            raise InputChanged("INPUT_CHANGED")
        manifest.update(
            {
                "files": published,
                "input": state["input"],
                "validation": state["validation"],
                "jobRunId": state["transform"]["jobRunId"],
            }
        )
        manifest_key = output + "manifest.json"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=manifest_key,
            Body=json.dumps(manifest).encode(),
            ContentType="application/json",
        )
        publication = {"bucket": self.bucket, "key": manifest_key}
        self._owned_update(
            state,
            "SET #status = :status, publication = :publication, updatedAt = :now",
            {":status": "SUCCEEDED", ":publication": publication, ":now": utc_now()},
            {"#status": "status"},
            running=True,
        )
        return state | {"publication": publication}

    def _safe_services(self, lock):
        """共有サービスの終端を確認できない場合は排他を維持する。"""
        crawler = self.glue.get_crawler(Name=self.crawler)["Crawler"]
        if crawler["State"] != "READY":
            return False
        if lock.get("crawlerPending"):
            crawl = crawler.get("LastCrawl", {})
            if (
                not crawl.get("StartTime")
                or str(crawl["StartTime"]) == lock.get("crawlerPrevious")
                or crawl["StartTime"].timestamp() < lock["crawlerStarted"]
                or crawl.get("Status") not in ("SUCCEEDED", "FAILED", "CANCELLED")
            ):
                return False
        if lock.get("gluePending"):
            if lock.get("jobRunId"):
                runs = [self.glue.get_job_run(JobName=self.job, RunId=lock["jobRunId"])["JobRun"]]
            else:
                runs = []
                token = None
                while True:
                    response = self.glue.get_job_runs(
                        JobName=self.job, **({"NextToken": token} if token else {})
                    )
                    runs.extend(
                        run
                        for run in response["JobRuns"]
                        if run.get("Arguments", {}).get("--attempt_id") == lock["attemptId"]
                    )
                    token = response.get("NextToken")
                    if not token:
                        break
            if not runs or any(
                run["JobRunState"]
                not in ("SUCCEEDED", "FAILED", "STOPPED", "TIMEOUT", "ERROR", "EXPIRED")
                for run in runs
            ):
                return False
        return True

    def release(self, state):
        """成功時もサービス終了と所有者一致を確認してロックを解放する。"""
        key = {"inputId": "__transform_lock__"}
        lock = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
        if lock:
            if (
                lock["attemptId"] != state["attempt"]["attemptId"]
                or lock["executionArn"] != state["attempt"]["executionArn"]
            ):
                raise OwnershipLost("LOCK_OWNER_CHANGED")
            if not self._safe_services(lock):
                raise ContractError("SERVICES_STILL_RUNNING")
            self.table.delete_item(
                Key=key,
                ConditionExpression="executionArn = :execution AND attemptId = :attempt",
                ExpressionAttributeValues=self._owner(state),
            )
        # 公開確定後の掃除失敗は公開を取り消さず、運用で再実行できる。
        return state

    def clean_staging(self, state):
        """公開済みattemptだけのstagingを削除する。"""
        item = self.table.get_item(Key=self._key(state), ConsistentRead=True).get("Item")
        if (
            not item
            or item["status"] != "SUCCEEDED"
            or item["attemptId"] != state["attempt"]["attemptId"]
            or item["executionArn"] != state["attempt"]["executionArn"]
        ):
            raise OwnershipLost("PUBLICATION_OWNER_CHANGED")
        prefix = state["transform"]["stagingPrefix"]
        token = None
        while True:
            page = self.s3.list_objects_v2(
                Bucket=self.bucket, Prefix=prefix, **({"ContinuationToken": token} if token else {})
            )
            for obj in page.get("Contents", []):
                self.s3.delete_object(Bucket=self.bucket, Key=obj["Key"])
            token = page.get("NextContinuationToken")
            if not token:
                break
        return state

    def cleanup(self, state):
        """失敗を記録し、終了確認ができる場合だけロックを解放する。"""
        if not state.get("accepted"):
            return state
        try:
            self._owned_update(
                state,
                "SET #status = :failed, updatedAt = :now",
                {":failed": "FAILED", ":now": utc_now()},
                {"#status": "status"},
                running=True,
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        key = {"inputId": "__transform_lock__"}
        lock = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
        failure = state.get("failure", {})
        # .syncの起動拒否を示す認可エラーだけを扱う。GetJobRun失敗は未開始の証拠にならない。
        denied_start = "AccessDenied" in failure.get(
            "Error", ""
        ) and "glue:StartJobRun" in failure.get("Cause", "")
        if (
            lock
            and lock["attemptId"] == state["attempt"]["attemptId"]
            and lock["executionArn"] == state["attempt"]["executionArn"]
            and (denied_start or state.get("glueNotStarted") is True)
        ):
            self._owned_update(state, "SET gluePending = :no", {":no": False}, key=key)
            lock["gluePending"] = False
        if (
            lock
            and lock["attemptId"] == state["attempt"]["attemptId"]
            and lock["executionArn"] == state["attempt"]["executionArn"]
            and self._safe_services(lock)
        ):
            self.table.delete_item(
                Key=key,
                ConditionExpression="executionArn = :execution AND attemptId = :attempt",
                ExpressionAttributeValues=self._owner(state),
            )
        return state

    def recover(self, event):
        """手動復旧時に旧実行・サービスの終端を確認して排他を解除する。"""
        key = {"inputId": "__transform_lock__"}
        lock = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
        if not lock:
            return {"recovered": True}
        if (
            event.get("executionArn") != lock["executionArn"]
            or event.get("attemptId") != lock["attemptId"]
        ):
            raise ContractError("RECOVERY_OWNER_REQUIRED")
        if self._terminal(lock["executionArn"]) == "RUNNING" or not self._safe_services(lock):
            raise ContractError("RECOVERY_NOT_SAFE")
        self.table.delete_item(
            Key=key,
            ConditionExpression="executionArn = :execution AND attemptId = :attempt",
            ExpressionAttributeValues={
                ":execution": lock["executionArn"],
                ":attempt": lock["attemptId"],
            },
        )
        return {"recovered": True}


def handler(event, context):
    """固定された環境と操作名を検査し、安全な例外codeだけを公開する。"""
    config = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=25)
    pipeline = Pipeline(
        boto3.client("s3", config=config),
        boto3.resource("dynamodb", config=config).Table(os.environ["STATE_TABLE"]),
        boto3.client("glue", config=config),
        boto3.client("stepfunctions", config=config),
        os.environ["BUCKET_NAME"],
        os.environ["STATE_TABLE"],
        os.environ["CRAWLER_NAME"],
        os.environ["GLUE_JOB_NAME"],
    )
    operation = event.get("operation")
    try:
        result = _dispatch(pipeline, operation, event)
    except Exception as error:
        code = (
            error.args[0]
            if isinstance(
                error,
                (ContractError, InputChanged, OwnershipLost, TransientServiceError, ServiceFailure),
            )
            and error.args
            else type(error).__name__
        )
        _log_operation(operation, event, None, code)
        raise
    _log_operation(operation, event, result, None)
    return result


def _mapping(value):
    """ログ用に辞書だけを取り出し、それ以外は空として扱う。"""
    return value if isinstance(value, dict) else {}


def _log_operation(operation, event, result, code):
    """本文を含めず、処理の識別子と結果codeだけを1行のJSONで記録する。"""
    state = _mapping(event.get("state"))
    source = result if isinstance(result, dict) and "input" in result else state
    attempt = _mapping(source.get("attempt"))
    transform = _mapping(source.get("transform"))
    glue_result = _mapping(source.get("glueResult"))
    record = {
        "operation": operation if isinstance(operation, str) else None,
        "outcome": "error" if code else "ok",
        "code": code,
        "inputId": _mapping(source.get("input")).get("inputId"),
        "attemptId": attempt.get("attemptId") or state.get("attemptId"),
        "executionArn": attempt.get("executionArn")
        or event.get("executionArn")
        or state.get("executionArn"),
        "jobRunId": transform.get("jobRunId")
        or glue_result.get("Id")
        or glue_result.get("JobRunId")
        or glue_result.get("JobRunID"),
    }
    print(
        json.dumps(
            {key: value for key, value in record.items() if isinstance(value, str) and value}
        ),
        flush=True,
    )


def _dispatch(pipeline, operation, event):
    """操作名に対応する処理を実行し、SDKの失敗を公開できるcodeへ変換する。"""
    try:
        if operation == "initialize":
            return pipeline.initialize(event["event"], event["executionArn"])
        if operation not in (
            "acquire",
            "validate",
            "lock",
            "start_crawler",
            "poll_crawler",
            "prepare_glue",
            "record_glue",
            "publish",
            "release",
            "clean_staging",
            "cleanup",
            "recover",
        ):
            raise ContractError("UNKNOWN_OPERATION")
        return getattr(pipeline, operation)(event["state"])
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code in ("PreconditionFailed", "412"):
            raise InputChanged("INPUT_CHANGED") from None
        if code == "ConditionalCheckFailedException":
            raise OwnershipLost("OWNER_CHANGED") from None
        # 開始APIと公開処理は応答消失時の無条件再送を避ける。
        if operation in RETRYABLE_OPERATIONS and code in (
            "SlowDown",
            "ThrottlingException",
            "TooManyRequestsException",
            "ServiceUnavailable",
            "InternalError",
            "InternalServerError",
        ):
            raise TransientServiceError(code) from None
        raise ServiceFailure(code) from None
    except (
        ConnectionClosedError,
        ConnectTimeoutError,
        EndpointConnectionError,
        ReadTimeoutError,
        ResponseStreamingError,
    ):
        if operation in RETRYABLE_OPERATIONS:
            raise TransientServiceError("SDK_COMMUNICATION_FAILED") from None
        raise ServiceFailure("SDK_OPERATION_FAILED") from None
    except BotoCoreError:
        raise ServiceFailure("SDK_OPERATION_FAILED") from None
