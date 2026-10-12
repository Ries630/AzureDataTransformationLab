# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = ["pyspark==3.5.6"]
# ///
"""Glue 5.1と同じSpark/Python版で変換契約を検査する（Java 17が必要）。"""

import os
import sys
import unittest
from pathlib import Path


def main() -> None:
    """実Spark検査を有効にし、driverとworkerから同じ変換モジュールを参照する。"""
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    os.environ["PYTHONPATH"] = str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["PYSPARK_PYTHON"] = sys.executable
    os.environ["AWS_TEST_SPARK"] = "1"
    suite = unittest.defaultTestLoader.discover(
        str(root / "tests/aws"), pattern="test_transform.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
