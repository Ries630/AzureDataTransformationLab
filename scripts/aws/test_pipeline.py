# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = ["boto3==1.42.88"]
# ///
"""AWS接続なしでLambda・ワークフローの境界テストを実行する。"""

import unittest
from pathlib import Path

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parents[2] / "tests/aws"), pattern="test_pipeline.py"
    )
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
