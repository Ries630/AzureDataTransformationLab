"""Azure Functions から独立した CSV 入力検証ロジック。"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_BYTES = 1_048_576
"""検証対象として受け付ける CSV の最大バイト数。"""

MAX_ROWS = 1000
"""検証対象として受け付けるデータレコードの最大件数。"""

_REQUIRED_COLUMNS = (
    "order_id",
    "customer_id",
    "amount",
    "currency",
    "ordered_at",
)
_PLAIN_DECIMAL_PATTERN = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")
_DATETIME_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?P<timezone>Z|[+-][0-9]{2}:[0-9]{2})?$"
)

__all__ = ["MAX_BYTES", "MAX_ROWS", "validate_csv"]

csv.field_size_limit(MAX_BYTES)


def _make_error(
    row: int | None,
    column: str | None,
    message: str,
) -> dict[str, Any]:
    """検証エラーを公開 API の形式へ変換する。"""
    return {"row": row, "column": column, "message": message}


def _make_result(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """検証エラーの一覧から公開 API の結果を作成する。"""
    return {
        "status": "INVALID" if errors else "VALID",
        "errorCount": len(errors),
        "errors": errors,
    }


def _has_strict_csv_syntax(text: str) -> bool:
    """CSV の引用符が RFC 形式に従っているかを確認する。

    ``csv.reader(strict=True)`` は閉じていない引用符などを検出するが、
    非引用フィールド内の引用符を受理するため、検証前にこの条件も
    確認する。
    """
    field_start = True
    in_quotes = False
    after_quote = False
    index = 0

    while index < len(text):
        character = text[index]

        if in_quotes:
            if character == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
                after_quote = True
            index += 1
            continue

        if after_quote:
            if character == ",":
                field_start = True
                after_quote = False
            elif character in "\r\n":
                field_start = True
                after_quote = False
            else:
                return False
            index += 1
            continue

        if field_start and character == '"':
            in_quotes = True
        elif character == '"':
            return False
        elif character == ",":
            field_start = True
        elif character in "\r\n":
            field_start = True
        else:
            field_start = False
        index += 1

    return not in_quotes


def _validate_header(header: list[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """ヘッダーを検証し、列名から列番号への対応を返す。"""
    errors: list[dict[str, Any]] = []
    first_indexes: dict[str, int] = {}

    blank_reported = False
    duplicate_columns: set[str] = set()
    for index, column_name in enumerate(header):
        if not column_name.strip():
            if not blank_reported:
                errors.append(_make_error(1, None, "header column name must not be blank"))
                blank_reported = True
            continue
        if column_name in first_indexes:
            if column_name not in duplicate_columns:
                errors.append(_make_error(1, column_name, "header column names must be unique"))
                duplicate_columns.add(column_name)
            continue
        first_indexes[column_name] = index

    for required_column in _REQUIRED_COLUMNS:
        if required_column not in first_indexes:
            errors.append(
                _make_error(
                    1,
                    required_column,
                    f"missing required column: {required_column}",
                )
            )

    return errors, first_indexes


def _validate_order_id(value: str) -> str | None:
    """注文 ID の値を検証し、問題があればエラーメッセージを返す。"""
    if not value.strip():
        return "order_id must not be blank"
    return None


def _validate_customer_id(value: str) -> str | None:
    """顧客 ID の値を検証し、問題があればエラーメッセージを返す。"""
    if not value.strip():
        return "customer_id must not be blank"
    return None


def _validate_amount(value: str) -> str | None:
    """金額が平文の十進数であり、0 以上で有限かを検証する。"""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return "amount must be a plain decimal"

    if not amount.is_finite():
        return "amount must be a finite decimal"
    if not _PLAIN_DECIMAL_PATTERN.fullmatch(value):
        return "amount must be a plain decimal"
    if amount < 0:
        return "amount must be >= 0"
    return None


def _validate_currency(value: str) -> str | None:
    """通貨コードが JPY であることを検証する。"""
    if value != "JPY":
        return "currency must be JPY"
    return None


def _validate_ordered_at(value: str) -> str | None:
    """日時が指定された ISO 8601 の日時形式であることを検証する。"""
    match = _DATETIME_PATTERN.fullmatch(value)
    if match is None:
        return "ordered_at must be a valid ISO 8601 datetime"
    timezone = match.group("timezone")
    if timezone and timezone != "Z":
        offset_hour = int(timezone[1:3])
        offset_minute = int(timezone[4:6])
        if offset_hour > 23 or offset_minute > 59:
            return "ordered_at must be a valid ISO 8601 datetime"

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "ordered_at must be a valid ISO 8601 datetime"
    return None


_COLUMN_VALIDATORS = {
    "order_id": _validate_order_id,
    "customer_id": _validate_customer_id,
    "amount": _validate_amount,
    "currency": _validate_currency,
    "ordered_at": _validate_ordered_at,
}


def validate_csv(content: bytes, filename: str) -> dict[str, Any]:
    """CSV バイト列を検証し、構造化された判定結果を返す。

    ``filename`` は大文字小文字を区別して ``.csv`` で終わる必要がある。
    CSV は UTF-8（先頭の BOM は許可）で、必須列を持つヘッダーと、
    列数が一致する最大 ``MAX_ROWS`` 件のデータレコードで構成する。
    データレコードの行番号は、複数行の quoted field を 1 件として数え、
    ヘッダーを 1 行目、最初のデータを 2 行目とする。

    Args:
        content: 検証対象の UTF-8 CSV バイト列。
        filename: 入力ファイル名またはパス。

    Returns:
        ``status``, ``errorCount``, ``errors`` を含む検証結果。
    """
    errors: list[dict[str, Any]] = []

    if not isinstance(filename, str) or not filename.endswith(".csv"):
        errors.append(_make_error(None, None, "filename must end with .csv"))

    if not isinstance(content, bytes):
        errors.append(_make_error(None, None, "content must be bytes"))
        return _make_result(errors)

    if len(content) > MAX_BYTES:
        errors.append(_make_error(None, None, f"file size must be <= {MAX_BYTES} bytes"))
        return _make_result(errors)

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        errors.append(_make_error(None, None, "content must be valid UTF-8"))
        return _make_result(errors)

    if not _has_strict_csv_syntax(text):
        errors.append(_make_error(None, None, "CSV syntax is invalid"))
        return _make_result(errors)

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        errors.append(
            _make_error(None, None, "CSV must contain a header and at least one data row")
        )
        return _make_result(errors)
    except csv.Error:
        errors.append(_make_error(None, None, "CSV syntax is invalid"))
        return _make_result(errors)

    header_errors, column_indexes = _validate_header(header)
    errors.extend(header_errors)
    records: list[list[str]] = []
    try:
        for record in reader:
            if len(records) >= MAX_ROWS:
                errors.append(_make_error(None, None, f"data row count must be <= {MAX_ROWS}"))
                return _make_result(errors)
            records.append(record)
    except csv.Error:
        errors.append(_make_error(None, None, "CSV syntax is invalid"))
        return _make_result(errors)

    if not records:
        errors.append(_make_error(1, None, "CSV must contain at least one data row"))

    expected_width = len(header)

    for row_number, record in enumerate(records, start=2):
        if len(record) != expected_width:
            errors.append(
                _make_error(
                    row_number,
                    None,
                    f"row must contain exactly {expected_width} columns",
                )
            )
            continue

        if header_errors:
            continue

        for column_name in _REQUIRED_COLUMNS:
            value = record[column_indexes[column_name]]
            message = _COLUMN_VALIDATORS[column_name](value)
            if message is not None:
                errors.append(_make_error(row_number, column_name, message))

    return _make_result(errors)
