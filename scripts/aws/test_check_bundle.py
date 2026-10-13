# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""AWS接続なしで配布物検査CLIの安全境界を検査する。"""

import unittest
from pathlib import Path


def main() -> None:
    """manifest・隔離環境・ZIPの回帰検査を実行する。"""
    root = Path(__file__).resolve().parents[2]
    suite = unittest.defaultTestLoader.discover(str(root / "tests/aws"), "test_check_bundle.py")
    raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())


if __name__ == "__main__":
    main()
