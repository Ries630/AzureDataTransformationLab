"""Glue変換の契約と派生期待値を比較する。"""

from __future__ import annotations

import csv
import io
import unittest
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from glue.transform_orders import TransformError, check_rows, parse_source, serialize_rows

ROOT = Path(__file__).resolve().parents[2]


class ParseTests(unittest.TestCase):
    """論理レコードと出力安全性を検証する。"""

    def test_bom_reordered_multiline_duplicate(self):
        """BOM・列順変更・quoted改行・重複を論理レコードとして保つ。"""
        header, rows = parse_source(
            (
                "\ufeffnote,amount,ordered_at,currency,customer_id,order_id\n"
                '"a\nb",0.0001,2026-10-01T10:00:00,JPY,c,o\n'
                '"a\nb",0.0001,2026-10-01T10:00:00,JPY,c,o\n'
            ).encode()
        )
        self.assertEqual(header[0], "note")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0][0], "a\nb")

    def test_rename_collision_fails(self):
        """未知列を既存の出力列で上書きする前に変換を拒否する。"""
        for name in ("orderId", "customerId", "orderedAt", "taxIncludedAmount"):
            with self.subTest(name=name), self.assertRaises(TransformError):
                parse_source(
                    f"order_id,customer_id,amount,currency,ordered_at,{name}\no,c,1,JPY,2026-10-01T00:00:00,x\n".encode()
                )

    def test_row_loss_fails(self):
        """入力行の欠落を変換成功として扱わない。"""
        with self.assertRaises(TransformError):
            check_rows(
                [{"amount": Decimal("1"), "taxIncludedAmount": Decimal("1.1"), "orderedAt": "x"}], 2
            )

    def test_null_cast_fails(self):
        """必須castがnullを返した場合は変換を失敗させる。"""
        with self.assertRaises(TransformError):
            check_rows([{"amount": None, "taxIncludedAmount": Decimal("1.1"), "orderedAt": "x"}], 1)

    def test_serialization_preserves_empty_multiline_unknown(self):
        """未知列の空文字・改行・引用符をCSVの往復で保持する。"""
        data = serialize_rows(["note", "empty"], [{"note": 'a\nb,"x"', "empty": ""}])
        self.assertEqual(
            list(csv.DictReader(io.StringIO(data.decode()))), [{"note": 'a\nb,"x"', "empty": ""}]
        )


class SparkTests(unittest.TestCase):
    """Glueと同じSpark版で値・精度・論理レコード保持を確認する。"""

    @classmethod
    def setUpClass(cls):
        """明示されたSpark検査時だけローカルセッションを起動する。"""
        import os

        if os.environ.get("AWS_TEST_SPARK") != "1":
            raise unittest.SkipTest("scripts/aws/test_spark.py でSpark検査を実行する")
        from pyspark.sql import SparkSession

        cls.spark = (
            SparkSession.builder.master("local[2]").appName("aws-transform-contract").getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")

    @classmethod
    def tearDownClass(cls):
        """起動したSparkセッションを終了する。"""
        cls.spark.stop()

    @staticmethod
    def canonical(row):
        """CSV表記差を除き、十進数・日時・未知文字列を厳密に比較する。"""
        values = dict(row)
        for column in ("amount", "taxIncludedAmount"):
            values[column] = Decimal(values[column])
        instant = datetime.fromisoformat(values["orderedAt"].replace("Z", "+00:00"))
        if instant.tzinfo is not None:
            instant = instant.astimezone(UTC)
        values["orderedAt"] = instant
        return tuple(sorted(values.items()))

    def test_valid_fixtures_independent_expected(self):
        """固定入力4件を仕様から派生した独立期待CSVと照合する。"""
        from glue.transform_orders import transform

        for stem in ("orders_v1", "orders_v2", "orders_v3", "orders_drifted_types"):
            expected_path = (
                ROOT
                / "samples/expected/transformed"
                / ("standard" if stem == "orders_v1" else "drift")
                / (stem + ".csv")
            )
            with self.subTest(stem=stem):
                sample_dir = "valid" if stem == "orders_v1" else "schema-evolution"
                names, rows, count = transform(
                    self.spark, (ROOT / "samples" / sample_dir / (stem + ".csv")).read_bytes()
                )
                expected = list(csv.DictReader(io.StringIO(expected_path.read_text())))
                self.assertEqual(set(names), set(expected[0]))
                self.assertEqual(count, len(expected))
                self.assertEqual(
                    Counter(map(self.canonical, rows)), Counter(map(self.canonical, expected))
                )

    def test_decimal_boundary_timezone_and_naive(self):
        """金額境界・日時zone・未知列と重複の保持を同時に確認する。"""
        from glue.transform_orders import transform

        content = (
            b"order_id,customer_id,amount,currency,ordered_at,note,empty,Amount,a.b,a`b\n"
            b'a,c,0.0001,JPY,2026-10-01T10:00:00.123+09:00,"quoted\nline",,007,x,y\n'
            b"b,c,99999999999999.9999,JPY,2026-10-01T10:00:00.123,n,,,x,y\n"
            b'a,c,0.0001,JPY,2026-10-01T10:00:00.123+09:00,"quoted\nline",,007,x,y\n'
        )
        names, rows, count = transform(self.spark, content)
        self.assertEqual(count, 3)
        self.assertEqual(rows[0], rows[2])
        self.assertEqual(rows[0]["taxIncludedAmount"], Decimal("0.00011"))
        self.assertEqual(rows[1]["taxIncludedAmount"], Decimal("109999999999999.99989"))
        self.assertEqual(rows[0]["orderedAt"], "2026-10-01T01:00:00.123Z")
        self.assertEqual(rows[1]["orderedAt"], "2026-10-01T10:00:00.123")
        self.assertEqual(rows[0]["empty"], "")
        self.assertEqual(rows[0]["Amount"], "007")
        self.assertEqual(rows[0]["note"], "quoted\nline")
        self.assertEqual(
            list(csv.DictReader(io.StringIO(serialize_rows(names, rows).decode())))[0]["empty"], ""
        )

    def test_actual_invalid_cast_fails(self):
        """変換不可能な金額・日時と小数の丸めを成功として扱わない。"""
        from glue.transform_orders import transform

        for amount, instant in (
            ("bad", "2026-10-01T00:00:00"),
            ("1", "bad"),
            ("0.00001", "2026-10-01T00:00:00"),
        ):
            with self.subTest(amount=amount, instant=instant), self.assertRaises(TransformError):
                transform(
                    self.spark,
                    f"order_id,customer_id,amount,currency,ordered_at\no,c,{amount},JPY,{instant}\n".encode(),
                )

    def test_staging_manifest_and_no_publication(self):
        """stagingだけへ書き、実体のサイズとhashをmanifestへ記録する。"""
        import hashlib
        import json
        from unittest.mock import Mock

        from glue.transform_orders import run

        data = (ROOT / "samples/valid/orders_v1.csv").read_bytes()
        s3 = Mock()
        s3.get_object.return_value = {"Body": io.BytesIO(data), "ContentLength": len(data)}
        input_id, attempt_id = "a" * 64, "execution_1"
        prefix = f"staging/{input_id}/{attempt_id}/"
        manifest = run(
            self.spark,
            s3,
            {
                "source_bucket": "test",
                "source_key": f"validated/{input_id}/{attempt_id}/source.csv",
                "staging_prefix": prefix,
                "input_id": input_id,
                "attempt_id": attempt_id,
            },
        )
        written = [call.kwargs for call in s3.put_object.call_args_list]
        self.assertEqual(
            [item["Key"] for item in written], [prefix + "part-00000.csv", prefix + "manifest.json"]
        )
        self.assertEqual(
            manifest["files"][0]["sha256"], hashlib.sha256(written[0]["Body"]).hexdigest()
        )
        self.assertEqual(manifest["files"][0]["size"], len(written[0]["Body"]))
        self.assertEqual(json.loads(written[1]["Body"]), manifest)
        self.assertEqual(manifest["inputRows"], manifest["outputRows"])

    def test_invalid_prefix_prevents_storage_access(self):
        """別attemptやoutput領域を引数として指定できないことを確認する。"""
        from unittest.mock import Mock

        from glue.transform_orders import run

        s3 = Mock()
        with self.assertRaises(TransformError):
            run(
                self.spark,
                s3,
                {
                    "source_bucket": "test",
                    "source_key": "landing/x.csv",
                    "staging_prefix": "output/x/",
                    "input_id": "a" * 64,
                    "attempt_id": "attempt",
                },
            )
        s3.get_object.assert_not_called()


class ArgumentTests(unittest.TestCase):
    """Glue引数のうち任意のdata_prefixを読み分ける。"""

    def test_data_prefix_is_optional(self):
        """省略・空値・値ありのいずれでも、Glueの必須引数解析に頼らず読む。"""
        from glue.transform_orders import read_data_prefix

        cases = {
            "omitted": (["script.py", "--input_id", "a"], ""),
            "empty_before_next": (["script.py", "--data_prefix", "--input_id", "a"], ""),
            "empty_at_end": (["script.py", "--data_prefix"], ""),
            "empty_value": (["script.py", "--data_prefix", ""], ""),
            "equals_empty": (["script.py", "--data_prefix="], ""),
            "value": (["script.py", "--data_prefix", "team-ries/"], "team-ries/"),
            "equals_value": (["script.py", "--data_prefix=team-ries/"], "team-ries/"),
        }
        for name, (argv, expected) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(read_data_prefix(argv), expected)


if __name__ == "__main__":
    unittest.main()
