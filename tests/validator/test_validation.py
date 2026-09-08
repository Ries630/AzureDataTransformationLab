"""CSV入力検証の公開契約を検証するテスト。"""

import unittest
from pathlib import Path

from functions.validator.validation import MAX_BYTES, MAX_ROWS, validate_csv


class CsvValidationTests(unittest.TestCase):
    """CSV検証関数の振る舞いを検証する。"""

    def test_valid_csv_returns_valid_result(self) -> None:
        """必須列と正常な値を含むCSVはVALIDになる。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b"10001,C001,12800,JPY,2026-08-27T10:30:00\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result,
            {"status": "VALID", "errorCount": 0, "errors": []},
        )

    def test_invalid_sample_returns_five_cell_errors(self) -> None:
        """既存の不正サンプルは、問題のある5セルをそれぞれ報告する。"""
        content = (
            Path(__file__).resolve().parents[2] / "samples" / "invalid" / "orders_invalid.csv"
        ).read_bytes()

        result = validate_csv(content, "orders_invalid.csv")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 5)
        self.assertEqual(
            result["errors"],
            [
                {
                    "row": 2,
                    "column": "amount",
                    "message": "amount must be >= 0",
                },
                {
                    "row": 3,
                    "column": "customer_id",
                    "message": "customer_id must not be blank",
                },
                {
                    "row": 4,
                    "column": "amount",
                    "message": "amount must be a plain decimal",
                },
                {
                    "row": 4,
                    "column": "currency",
                    "message": "currency must be JPY",
                },
                {
                    "row": 4,
                    "column": "ordered_at",
                    "message": "ordered_at must be a valid ISO 8601 datetime",
                },
            ],
        )

    def test_required_columns_can_be_in_any_order_and_extra_columns_are_allowed(
        self,
    ) -> None:
        """必須列の順番に依存せず、追加列を含むCSVを受け付ける。"""
        content = (
            b"source_system,ordered_at,currency,amount,customer_id,order_id,extra\n"
            b"SYSTEM_A,2026-08-27T10:30:00,JPY,12800,C001,10001,ignored\n"
        )

        result = validate_csv(content, "orders_v2.csv")

        self.assertEqual(result, {"status": "VALID", "errorCount": 0, "errors": []})

    def test_utf8_bom_is_allowed(self) -> None:
        """UTF-8 BOMを含むCSVも先頭のBOMを列名として扱わず検証する。"""
        content = (
            "order_id,customer_id,amount,currency,ordered_at\n"
            "10001,C001,12800,JPY,2026-08-27T10:30:00\n"
        ).encode("utf-8-sig")

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(result["status"], "VALID")

    def test_uppercase_csv_suffix_is_rejected(self) -> None:
        """ファイル拡張子は大文字小文字を区別して検証する。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b"10001,C001,12800,JPY,2026-08-27T10:30:00\n"
        )

        result = validate_csv(content, "orders_v1.CSV")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 1)
        self.assertEqual(result["errors"][0]["row"], None)
        self.assertEqual(result["errors"][0]["column"], None)

    def test_invalid_utf8_is_reported_as_file_error(self) -> None:
        """UTF-8として復号できない入力をファイルエラーとして報告する。"""
        result = validate_csv(b"\xff", "orders_v1.csv")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 1)
        self.assertEqual(result["errors"][0]["row"], None)
        self.assertEqual(result["errors"][0]["column"], None)

    def test_empty_and_header_only_csv_are_invalid(self) -> None:
        """空ファイルとヘッダーだけのファイルをINVALIDとして扱う。"""
        empty_result = validate_csv(b"", "orders_v1.csv")
        header_only_result = validate_csv(
            b"order_id,customer_id,amount,currency,ordered_at\n",
            "orders_v1.csv",
        )

        self.assertEqual(empty_result["status"], "INVALID")
        self.assertEqual(empty_result["errors"][0]["row"], None)
        self.assertEqual(header_only_result["status"], "INVALID")
        self.assertEqual(
            header_only_result["errors"],
            [{"row": 1, "column": None, "message": "CSV must contain at least one data row"}],
        )

    def test_missing_required_columns_stop_cell_validation(self) -> None:
        """必須列が不足する場合は、データセルの値検証を行わない。"""
        content = b"order_id,customer_id,amount,currency\n10001,,ABC,XXX\n"

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 1)
        self.assertEqual(
            result["errors"],
            [{"row": 1, "column": "ordered_at", "message": "missing required column: ordered_at"}],
        )

    def test_missing_required_columns_still_allow_row_width_checks(self) -> None:
        """必須列不足でも、独立したデータ行の列数エラーは報告する。"""
        content = b"order_id,customer_id,amount,currency\n10001,C001,12800\n"

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result["errors"],
            [
                {
                    "row": 1,
                    "column": "ordered_at",
                    "message": "missing required column: ordered_at",
                },
                {"row": 2, "column": None, "message": "row must contain exactly 4 columns"},
            ],
        )

    def test_duplicate_and_blank_header_names_are_rejected(self) -> None:
        """ヘッダー列名の重複と空欄をINVALIDとして報告する。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at,order_id, \n"
            b"10001,C001,12800,JPY,2026-08-27T10:30:00,10001,extra\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 2)
        self.assertEqual(
            result["errors"],
            [
                {"row": 1, "column": "order_id", "message": "header column names must be unique"},
                {"row": 1, "column": None, "message": "header column name must not be blank"},
            ],
        )

    def test_row_width_mismatch_is_reported_without_cell_checks(self) -> None:
        """列数がヘッダーと異なるレコードを1件の構造エラーとして
        報告する。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b"10001,C001,12800,JPY\n"
            b"10002,C002,4500,JPY,2026-08-27T10:31:00,unexpected\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result["errors"],
            [
                {"row": 2, "column": None, "message": "row must contain exactly 5 columns"},
                {"row": 3, "column": None, "message": "row must contain exactly 5 columns"},
            ],
        )

    def test_multiline_quoted_field_uses_logical_record_numbers(self) -> None:
        """quoted field内の改行を1レコードとして数え、後続行を正しい番号で
        報告する。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b'10001,"C\n'
            b'001",12800,JPY,2026-08-27T10:30:00\n'
            b"10002,,4500,JPY,2026-08-27T10:31:00\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result["errors"],
            [{"row": 3, "column": "customer_id", "message": "customer_id must not be blank"}],
        )

    def test_malformed_csv_is_reported_as_parse_error(self) -> None:
        """閉じていない引用符などのCSV構文エラーをセルエラーに
        変換しない。"""
        result = validate_csv(
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b'10001,C001,"12800,JPY,2026-08-27T10:30:00\n',
            "orders_v1.csv",
        )

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(
            result["errors"], [{"row": None, "column": None, "message": "CSV syntax is invalid"}]
        )

    def test_value_rules_report_at_most_one_error_per_invalid_cell(self) -> None:
        """各必須セルの値エラーは1件にまとめ、複数列の不備はすべて
        報告する。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b" ,\t,1e3,JPY,2026-08-27 10:30:00\n"
            b"10002,C002,NaN,USD,2026-02-30T10:30:00\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result["errors"],
            [
                {"row": 2, "column": "order_id", "message": "order_id must not be blank"},
                {"row": 2, "column": "customer_id", "message": "customer_id must not be blank"},
                {"row": 2, "column": "amount", "message": "amount must be a plain decimal"},
                {
                    "row": 2,
                    "column": "ordered_at",
                    "message": "ordered_at must be a valid ISO 8601 datetime",
                },
                {"row": 3, "column": "amount", "message": "amount must be a finite decimal"},
                {"row": 3, "column": "currency", "message": "currency must be JPY"},
                {
                    "row": 3,
                    "column": "ordered_at",
                    "message": "ordered_at must be a valid ISO 8601 datetime",
                },
            ],
        )

    def test_datetime_accepts_optional_fraction_and_timezone(self) -> None:
        """日時は秒以下、UTCのZ、UTCオフセットを受け付ける。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b"10001,C001,+0.50,JPY,2026-08-27T10:30:00.123Z\n"
            b"10002,C002,1,JPY,2026-08-27T19:30:00+09:00\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(result, {"status": "VALID", "errorCount": 0, "errors": []})

    def test_datetime_rejects_invalid_timezone_minutes(self) -> None:
        """日時のUTCオフセット分が60以上の場合は受け付けない。"""
        content = (
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b"10001,C001,1,JPY,2026-08-27T10:30:00+01:60\n"
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result["errors"],
            [
                {
                    "row": 2,
                    "column": "ordered_at",
                    "message": "ordered_at must be a valid ISO 8601 datetime",
                }
            ],
        )

    def test_file_size_limit_is_measured_in_bytes(self) -> None:
        """最大バイト数を超えた入力を、解析前に1件のファイルエラーに
        する。"""
        result = validate_csv(b"x" * (MAX_BYTES + 1), "orders_v1.csv")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 1)
        self.assertEqual(
            result["errors"],
            [{"row": None, "column": None, "message": f"file size must be <= {MAX_BYTES} bytes"}],
        )

    def test_data_row_limit_is_measured_in_logical_records(self) -> None:
        """最大データレコード件数を超えた入力を、行番号なしの
        上限エラーにする。"""
        header = "order_id,customer_id,amount,currency,ordered_at\n"
        row = "10001,C001,1,JPY,2026-08-27T10:30:00\n"

        result = validate_csv(
            (header + row * (MAX_ROWS + 1)).encode(),
            "orders_v1.csv",
        )

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["errorCount"], 1)
        self.assertEqual(
            result["errors"],
            [{"row": None, "column": None, "message": f"data row count must be <= {MAX_ROWS}"}],
        )

    def test_unquoted_quote_is_rejected_as_strict_csv_syntax(self) -> None:
        """非引用フィールド内に現れた引用符を構文エラーとして扱う。"""
        result = validate_csv(
            b"order_id,customer_id,amount,currency,ordered_at\n"
            b'10001,C00"1,1,JPY,2026-08-27T10:30:00\n',
            "orders_v1.csv",
        )

        self.assertEqual(
            result["errors"], [{"row": None, "column": None, "message": "CSV syntax is invalid"}]
        )

    def test_repeated_blank_header_cells_are_reported_once(self) -> None:
        """上限サイズに近い空ヘッダーでも構造エラーを重複して返さない。"""
        content = b"," * (MAX_BYTES - 1)

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(
            [
                error
                for error in result["errors"]
                if error["message"] == "header column name must not be blank"
            ],
            [{"row": 1, "column": None, "message": "header column name must not be blank"}],
        )
        self.assertLessEqual(result["errorCount"], 7)

    def test_repeated_duplicate_header_names_are_reported_once_per_name(self) -> None:
        """同じ重複列名が何度現れても、列名ごとに構造エラーを1件だけ返す。"""
        content = b"order_id,customer_id,amount,currency,ordered_at,extra,extra,extra\n"

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(
            result["errors"],
            [
                {
                    "row": 1,
                    "column": "extra",
                    "message": "header column names must be unique",
                },
                {"row": 1, "column": None, "message": "CSV must contain at least one data row"},
            ],
        )

    def test_large_quoted_extra_column_is_not_limited_by_csv_default(self) -> None:
        """128KiBを超える追加列でも、ファイル上限内ならCSV解析を続ける。"""
        extra = b"x" * (128 * 1024 + 1)
        content = (
            b"order_id,customer_id,amount,currency,ordered_at,extra\n"
            b'10001,C001,1,JPY,2026-08-27T10:30:00,"' + extra + b'"\n'
        )

        result = validate_csv(content, "orders_v1.csv")

        self.assertEqual(result, {"status": "VALID", "errorCount": 0, "errors": []})


if __name__ == "__main__":
    unittest.main()
