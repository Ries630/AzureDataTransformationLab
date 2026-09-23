# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""Azure SDKをインストールしない環境でCSV検証ロジックをテストする。"""

import sys
import unittest
from pathlib import Path


def main() -> None:
    """純粋なCSV検証の公開インターフェースだけを実行する。"""
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(
        str(root / "tests/validator"), pattern="test_validation.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
