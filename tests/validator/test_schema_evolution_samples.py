"""Schema Evolutionのサンプルを、Functionの層で受け入れるか拒否するかを検証するテスト。

Data Flowの比較（Phase 4）は、Functionが受け入れたサンプルだけがPipeline上で
Data Flowへ届くことを前提にする。サンプルを変更したときにこの前提が崩れないよう確認する。
"""

import unittest
from pathlib import Path

from functions.validator.validation import validate_csv

_SAMPLES = Path(__file__).resolve().parents[2] / "samples" / "schema-evolution"


def _validate_sample(name: str) -> dict:
    """schema-evolutionのサンプルを読み込み、検証結果を返す。"""
    return validate_csv((_SAMPLES / name).read_bytes(), name)


class SchemaEvolutionSampleTests(unittest.TestCase):
    """列・型の変化を含むサンプルに対するFunctionの判定を検証する。"""

    def test_added_columns_are_accepted(self) -> None:
        """必須列がそろっていれば、追加列・未知の列があってもVALIDになりData Flowへ進む。"""
        for name in (
            "orders_v2.csv",
            "orders_v3.csv",
            "orders_drifted_types.csv",
        ):
            with self.subTest(sample=name):
                self.assertEqual(
                    _validate_sample(name),
                    {"status": "VALID", "errorCount": 0, "errors": []},
                )

    def test_missing_required_column_is_rejected_at_header(self) -> None:
        """必須列の欠落はヘッダーエラーとしてINVALIDになり、Data Flowへ進まない。"""
        result = _validate_sample("orders_missing_required.csv")

        self.assertEqual(
            result,
            {
                "status": "INVALID",
                "errorCount": 1,
                "errors": [
                    {
                        "row": 1,
                        "column": "customer_id",
                        "message": "missing required column: customer_id",
                    }
                ],
            },
        )

    def test_amount_type_change_is_rejected_per_cell(self) -> None:
        """amountが数値として読めない形式に変わると、セルごとにINVALIDになる。"""
        result = _validate_sample("orders_amount_type_change.csv")

        self.assertEqual(
            result,
            {
                "status": "INVALID",
                "errorCount": 2,
                "errors": [
                    {"row": 2, "column": "amount", "message": "amount must be a plain decimal"},
                    {"row": 3, "column": "amount", "message": "amount must be a plain decimal"},
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
