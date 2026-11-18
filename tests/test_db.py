import os
import sqlite3

from tests.helpers import TempDBTestCase
import db


class DatabaseHelperTests(TempDBTestCase):
    def test_schema_created_at_latest_version(self):
        with db.connect() as conn:
            v = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(v, db.LATEST_VERSION)
        for t in ("employee", "raw_inventory", "bill", "invoice_items", "stock_movement",
                  "customer", "supplier", "settings", "invoice_counter"):
            self.assertIn(t, tables)

    def test_legacy_column_order_preserved(self):
        with db.connect() as conn:
            emp = [r[1] for r in conn.execute("PRAGMA table_info(employee)")]
            inv = [r[1] for r in conn.execute("PRAGMA table_info(raw_inventory)")]
            bill = [r[1] for r in conn.execute("PRAGMA table_info(bill)")]
        self.assertEqual(emp[:7], ["emp_id", "name", "contact_num", "address",
                                   "aadhar_num", "password", "designation"])
        self.assertEqual(inv[:8], ["product_id", "product_name", "product_cat", "product_subcat",
                                   "stock", "mrp", "cost_price", "vendor_phn"])
        self.assertEqual(bill[:5], ["bill_no", "date", "customer_name", "customer_no", "bill_details"])

    def test_init_is_idempotent(self):
        self.assertIsNone(db.init_db())
        self.assertIsNone(db.init_db())

    def test_connection_is_closed_after_context(self):
        with db.connect() as conn:
            pass
        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_transaction_rolls_back_on_error(self):
        with db.connect() as conn:
            with self.assertRaises(ValueError):
                with db.transaction(conn):
                    conn.execute("INSERT INTO settings(key, value) VALUES ('TEST_key', 'x')")
                    raise ValueError("boom")
            self.assertIsNone(conn.execute("SELECT 1 FROM settings WHERE key='TEST_key'").fetchone())

    def test_nested_transaction_savepoint(self):
        with db.connect() as conn:
            with db.transaction(conn):
                conn.execute("INSERT INTO settings(key, value) VALUES ('TEST_outer', '1')")
                try:
                    with db.transaction(conn):
                        conn.execute("INSERT INTO settings(key, value) VALUES ('TEST_inner', '1')")
                        raise ValueError
                except ValueError:
                    pass
            keys = {r[0] for r in conn.execute("SELECT key FROM settings WHERE key LIKE 'TEST_%'")}
        self.assertEqual(keys, {"TEST_outer"})

    def test_backup_copies_database(self):
        dest = db.backup_database(reason="TEST", dest_dir=os.path.join(self.tmp, "bk"))
        self.assertTrue(os.path.exists(dest))
        with sqlite3.connect(dest) as c:
            self.assertEqual(c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
                             db.LATEST_VERSION)
        c.close()

    def test_backup_returns_none_without_database(self):
        self.assertIsNone(db.backup_database(os.path.join(self.tmp, "missing.db")))


class LegacyMigrationTests(TempDBTestCase):
    """A database shaped like the original app's gets upgraded additively."""

    def test_legacy_rows_survive_and_backup_is_taken(self):
        legacy = os.path.join(self.tmp, "TEST_legacy.db")
        c = sqlite3.connect(legacy)
        for sql in db.LEGACY_TABLES:
            c.execute(sql)
        c.execute("INSERT INTO raw_inventory(product_name, product_cat, product_subcat, stock, mrp, "
                  "cost_price, vendor_phn) VALUES ('TEST legacy item','TEST','TEST',7,10.5,8,'9000000000')")
        c.execute("INSERT INTO bill VALUES ('TESTBILL1','2025-01-01','TEST customer','9000000000',"
                  "'TEST legacy item\t1\t10.5')")
        c.commit()
        c.close()
        bk_dir = os.path.join(self.tmp, "backups")
        old = db.BACKUP_DIR
        db.BACKUP_DIR = bk_dir
        try:
            backup = db.init_db(legacy)
        finally:
            db.BACKUP_DIR = old
        self.assertIsNotNone(backup)
        self.assertTrue(os.path.exists(backup))
        with db.connect(legacy) as conn:
            row = conn.execute("SELECT * FROM bill WHERE bill_no='TESTBILL1'").fetchone()
            self.assertEqual(row["bill_details"], "TEST legacy item\t1\t10.5")
            self.assertIsNone(row["calc_version"])
            p = conn.execute("SELECT stock, mrp, gst_rate FROM raw_inventory").fetchone()
            self.assertEqual((p["stock"], p["mrp"], p["gst_rate"]), (7, 10.5, None))
        with sqlite3.connect(backup) as b:
            self.assertEqual(b.execute("SELECT COUNT(*) FROM bill").fetchone()[0], 1)
            cols = [r[1] for r in b.execute("PRAGMA table_info(bill)")]
        b.close()
        self.assertNotIn("grand_total", cols)  # backup is the untouched original
