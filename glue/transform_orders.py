"""検証済み注文CSVをSparkで変換し、公開前のstagingとmanifestを保存する。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

MAX_BYTES = 1_048_576
MAX_ROWS = 1000
REQUIRED = ("order_id", "customer_id", "amount", "currency", "ordered_at")
RENAMES = {"order_id": "orderId", "customer_id": "customerId", "ordered_at": "orderedAt"}
OUTPUT_REQUIRED = ("orderId", "customerId", "amount", "currency", "orderedAt", "taxIncludedAmount")


class TransformError(RuntimeError):
    """変換によるデータ欠落または処理契約の違反を表す。"""


def parse_source(content: bytes) -> tuple[list[str], list[list[str]]]:
    """上限内の固定原本を論理CSVレコードとして読み、列衝突を拒否する。"""
    if len(content) > MAX_BYTES:
        raise TransformError("INPUT_SIZE_EXCEEDED")
    csv.field_size_limit(MAX_BYTES)
    try:
        records = list(
            csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        )
    except (UnicodeDecodeError, csv.Error) as error:
        raise TransformError("INVALID_CSV") from error
    if not records:
        raise TransformError("EMPTY_INPUT")
    header, rows = records[0], records[1:]
    if len(header) != len(set(header)) or not all(name in header for name in REQUIRED):
        raise TransformError("INVALID_HEADER")
    if any(name in header for name in (*RENAMES.values(), "taxIncludedAmount")):
        raise TransformError("OUTPUT_COLUMN_COLLISION")
    if not rows or len(rows) > MAX_ROWS or any(len(row) != len(header) for row in rows):
        raise TransformError("INVALID_ROW_COUNT_OR_WIDTH")
    return header, rows


def normalize_datetime(value: str) -> tuple[datetime, bool] | None:
    """zone付き日時はUTCへ、zone省略日時は壁時計のままNTZへ変換する。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        zoned = parsed.tzinfo is not None
        if zoned:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed, zoned
    except (ValueError, OverflowError):
        return None


def check_rows(rows: list[dict[str, Any]], input_rows: int) -> None:
    """行数不一致と必須castのnullを公開前に拒否する。"""
    if len(rows) != input_rows:
        raise TransformError("ROW_COUNT_MISMATCH")
    if any(
        row.get(name) is None
        for row in rows
        for name in ("amount", "orderedAt", "taxIncludedAmount")
    ):
        raise TransformError("CAST_NULL")


def transform(spark: Any, content: bytes) -> tuple[list[str], list[dict[str, Any]], int]:
    """必須列のcast・rename・派生列をSparkで計算し、未知文字列と重複を保つ。"""
    from pyspark.sql import functions as F
    from pyspark.sql.types import BooleanType, StringType, StructField, StructType, TimestampNTZType

    header, source_rows = parse_source(content)
    # 大文字小文字やドットを含む未知列も、その名前と文字列を変更しない。
    spark.conf.set("spark.sql.caseSensitive", "true")
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    spark.conf.set("spark.sql.ansi.enabled", "false")
    schema = StructType([StructField(name, StringType(), False) for name in header])
    source = spark.createDataFrame(source_rows, schema)
    datetime_type = StructType(
        [StructField("value", TimestampNTZType()), StructField("zoned", BooleanType())]
    )
    parse_datetime = F.udf(normalize_datetime, datetime_type)

    def column(name: str) -> Any:
        """特殊文字を持つ列名をSparkの式として解釈せず参照する。"""
        return F.col("`" + name.replace("`", "``") + "`")

    parsed_datetime = parse_datetime(column("ordered_at"))
    timestamp = F.date_format(parsed_datetime["value"], "yyyy-MM-dd'T'HH:mm:ss.SSS")
    normalized_time = F.when(parsed_datetime["zoned"], F.concat(timestamp, F.lit("Z"))).otherwise(
        timestamp
    )
    amount = column("amount").cast("decimal(18,4)")
    # 14桁の整数部に1.1を掛けると15桁になるため、精度20・小数5桁を確保する。
    tax = (amount * F.lit(Decimal("1.1"))).cast("decimal(20,5)")
    unknown = [name for name in header if name not in REQUIRED]
    output_names = list(OUTPUT_REQUIRED) + unknown
    transformed = source.select(
        column("order_id").alias("orderId"),
        column("customer_id").alias("customerId"),
        amount.alias("amount"),
        column("currency"),
        normalized_time.alias("orderedAt"),
        tax.alias("taxIncludedAmount"),
        *[column(name) for name in unknown],
    )
    # 上限1000行のためdriver収集が有界。CSVの空欄とquoted改行も明示的に保存できる。
    output_rows = [row.asDict() for row in transformed.collect()]
    check_rows(output_rows, len(source_rows))
    amount_index = header.index("amount")
    source_amounts = Counter(Decimal(row[amount_index]) for row in source_rows)
    if source_amounts != Counter(row["amount"] for row in output_rows):
        raise TransformError("CAST_VALUE_CHANGED")
    return output_names, output_rows, len(source_rows)


def serialize_rows(names: list[str], rows: list[dict[str, Any]]) -> bytes:
    """十進数と未知文字列を浮動小数点を経由せずUTF-8 CSVへ保存する。"""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(names)
    for row in rows:
        writer.writerow(
            [
                format(row[name], "f") if isinstance(row[name], Decimal) else row[name]
                for name in names
            ]
        )
    return stream.getvalue().encode("utf-8")


def run(spark: Any, s3: Any, arguments: dict[str, str]) -> dict[str, Any]:
    """固定原本を読み、変換済みデータとmanifestを当該attemptのstagingへ置く。"""
    input_id, attempt_id = arguments["input_id"], arguments["attempt_id"]
    if not re.fullmatch(r"[a-f0-9]{64}", input_id) or not re.fullmatch(
        r"[A-Za-z0-9_-]+", attempt_id
    ):
        raise TransformError("INVALID_PROCESSING_ID")
    prefix = arguments.get("data_prefix", "")
    if prefix and not re.fullmatch(r"[a-zA-Z0-9_-]+/", prefix):
        raise TransformError("INVALID_DATA_PREFIX")
    expected_source = f"{prefix}validated/{input_id}/{attempt_id}/source.csv"
    expected_staging = f"{prefix}staging/{input_id}/{attempt_id}/"
    if (
        arguments["source_key"] != expected_source
        or arguments["staging_prefix"] != expected_staging
    ):
        raise TransformError("INVALID_ATTEMPT_PREFIX")
    bucket = arguments["source_bucket"]
    response = s3.get_object(Bucket=bucket, Key=expected_source)
    body = response["Body"]
    try:
        if response["ContentLength"] > MAX_BYTES:
            raise TransformError("INPUT_SIZE_EXCEEDED")
        content = body.read(MAX_BYTES + 1)
    finally:
        body.close()
    names, rows, input_rows = transform(spark, content)
    data = serialize_rows(names, rows)
    data_key = expected_staging + "part-00000.csv"
    s3.put_object(Bucket=bucket, Key=data_key, Body=data, ContentType="text/csv; charset=utf-8")
    manifest = {
        "inputId": input_id,
        "attemptId": attempt_id,
        "inputRows": input_rows,
        "outputRows": len(rows),
        "columns": names,
        "files": [{"key": data_key, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
    }
    s3.put_object(
        Bucket=bucket,
        Key=expected_staging + "manifest.json",
        Body=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode(),
        ContentType="application/json",
    )
    return manifest


def main() -> None:
    """Glue jobの引数とセッションを取得し、staging保存完了後にcommitする。"""
    import boto3
    from awsglue.context import GlueContext
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from pyspark.context import SparkContext

    arguments = getResolvedOptions(
        sys.argv,
        [
            "JOB_NAME",
            "source_bucket",
            "source_key",
            "staging_prefix",
            "input_id",
            "attempt_id",
            "data_prefix",
        ],
    )
    context = GlueContext(SparkContext.getOrCreate())
    job = Job(context)
    job.init(arguments["JOB_NAME"], arguments)
    run(context.spark_session, boto3.client("s3"), arguments)
    job.commit()


if __name__ == "__main__":
    main()
