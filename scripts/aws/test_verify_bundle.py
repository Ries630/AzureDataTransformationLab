# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""配布物検証CLIの回帰テストをAWS接続なしで実行する。"""

import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[2]
suite = unittest.defaultTestLoader.discover(str(root / "tests/aws"), "test_verify_bundle.py")
sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
