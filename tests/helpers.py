"""Shared test scaffolding.

Every test runs against a brand-new temporary database (BILLWISE_DB points
at it). The real Database/store.db is never opened by the test suite.
All fixture rows are clearly labelled "TEST" - they are not real data.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402


class TempDBTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="billwise_test_")
        self.db_path = os.path.join(self.tmp, "TEST_store.db")
        if os.path.abspath(self.db_path) == os.path.abspath(db.DEFAULT_DB_PATH):
            raise RuntimeError("Refusing to run tests against the real database")
        self._old_env = os.environ.get("BILLWISE_DB")
        os.environ["BILLWISE_DB"] = self.db_path
        db.init_db()

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("BILLWISE_DB", None)
        else:
            os.environ["BILLWISE_DB"] = self._old_env
        shutil.rmtree(self.tmp, ignore_errors=True)
