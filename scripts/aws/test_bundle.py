# /// script
# requires-python = ">=3.14,<3.15"
# dependencies = []
# ///
"""配布内容の収集とmanifestをAWS認証なしで検査する。"""

import unittest
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.discover(str(root / "tests/aws"), pattern="test_bundle.py")
    )
    raise SystemExit(not result.wasSuccessful())
