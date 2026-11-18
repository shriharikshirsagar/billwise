"""Billwise database helper.

* One place that knows where the database lives (``BILLWISE_DB`` overrides it,
  which is how the tests point everything at a temporary database).
* ``connect()`` is a context manager that always closes the connection.
* ``transaction()`` gives an explicit BEGIN IMMEDIATE ... COMMIT block that is
  rolled back on any exception.
* ``init_db()`` creates the legacy-compatible tables and applies additive,
  versioned migrations. A timestamped backup is taken before migrating a
  database that already contains data.
"""
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(APP_DIR, "Database", "store.db")
BACKUP_DIR = os.path.join(APP_DIR, "backups")

log = logging.getLogger("billwise.db")


def get_db_path():
    return os.environ.get("BILLWISE_DB") or DEFAULT_DB_PATH


def app_path(*parts):
    """Absolute path inside the application folder (never depends on the CWD)."""
    return os.path.join(APP_DIR, *parts)


@contextmanager
def connect(db_path=None):
    """Open a connection in autocommit mode; writes must use ``transaction()``."""
    path = db_path or get_db_path()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        if conn.in_transaction:  # never leave a half-finished write behind
            conn.rollback()
        conn.close()


@contextmanager
def transaction(conn):
    """Atomic block. Nested use becomes a SAVEPOINT."""
    if conn.in_transaction:
        name = "sp_%d" % id(object())
        conn.execute("SAVEPOINT %s" % name)
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK TO %s" % name)
            conn.execute("RELEASE %s" % name)
            raise
        conn.execute("RELEASE %s" % name)
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def backup_database(db_path=None, reason="manual", dest_dir=None):
    """Copy the database with SQLite's online backup API.

    Returns the backup path, or None when there is no database file yet.
    """
    src = db_path or get_db_path()
    if not os.path.exists(src):
        return None
    dest_dir = dest_dir or BACKUP_DIR
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base = os.path.splitext(os.path.basename(src))[0]
    dest = os.path.join(dest_dir, "%s_%s_%s.db" % (base, stamp, reason))
    with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
        s.backup(d)
    s.close()
    d.close()
    return dest


# ---------------------------------------------------------------- schema
# Version 1 reproduces the column order the original code relies on
# (it reads rows from ``SELECT *`` by position).
LEGACY_TABLES = [
    """CREATE TABLE IF NOT EXISTS employee (
        emp_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        contact_num TEXT,
        address TEXT,
        aadhar_num TEXT,
        password TEXT NOT NULL,
        designation TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS raw_inventory (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        product_cat TEXT,
        product_subcat TEXT,
        stock INTEGER NOT NULL DEFAULT 0,
        mrp REAL NOT NULL,
        cost_price REAL,
        vendor_phn TEXT)""",
    """CREATE TABLE IF NOT EXISTS bill (
        bill_no TEXT PRIMARY KEY,
        date TEXT,
        customer_name TEXT,
        customer_no TEXT,
        bill_details TEXT)""",
]


def _columns(conn, table):
    return [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)]


def _is_pk(conn, table, column):
    for r in conn.execute("PRAGMA table_info(%s)" % table):
        if r["name"] == column:
            return bool(r["pk"])
    return False


def _add_column(conn, table, column, decl):
    if column not in _columns(conn, table):
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))


def _migration_2(conn):
    """Billwise structure: GST, structured invoices, stock history, people."""
    for col, decl in [("hsn_code", "TEXT"), ("gst_rate", "TEXT"),
                      ("reorder_level", "INTEGER"), ("supplier_id", "INTEGER")]:
        _add_column(conn, "raw_inventory", col, decl)

    for col, decl in [
        ("subtotal", "TEXT"), ("discount_total", "TEXT"), ("taxable_total", "TEXT"),
        ("cgst_total", "TEXT"), ("sgst_total", "TEXT"), ("igst_total", "TEXT"),
        ("tax_total", "TEXT"), ("round_off", "TEXT"), ("grand_total", "TEXT"),
        ("supply_type", "TEXT"), ("place_of_supply", "TEXT"), ("customer_id", "INTEGER"),
        ("customer_gstin", "TEXT"), ("payment_mode", "TEXT"), ("payment_ref", "TEXT"),
        ("amount_tendered", "TEXT"), ("change_due", "TEXT"), ("status", "TEXT"),
        ("created_by", "TEXT"), ("created_at", "TEXT"), ("cancelled_at", "TEXT"),
        ("cancelled_by", "TEXT"), ("cancel_reason", "TEXT"), ("calc_version", "INTEGER"),
    ]:
        _add_column(conn, "bill", col, decl)

    # Foreign keys to legacy tables are only declared when the parent column
    # really is a primary key, otherwise SQLite raises "foreign key mismatch".
    prod_fk = ("REFERENCES raw_inventory(product_id) ON DELETE SET NULL"
               if _is_pk(conn, "raw_inventory", "product_id") else "")

    conn.execute("""CREATE TABLE IF NOT EXISTS supplier (
        supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT, email TEXT, address TEXT, gstin TEXT,
        created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS customer (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, phone TEXT UNIQUE, email TEXT, address TEXT,
        state_code TEXT, gstin TEXT, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS invoice_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_no TEXT NOT NULL,
        line_no INTEGER NOT NULL,
        product_id INTEGER %s,
        product_name TEXT NOT NULL, hsn_code TEXT,
        qty INTEGER NOT NULL CHECK (qty > 0),
        unit_price TEXT NOT NULL, discount_pct TEXT NOT NULL,
        gross_amount TEXT NOT NULL, discount_amount TEXT NOT NULL,
        taxable_amount TEXT NOT NULL, gst_rate TEXT NOT NULL,
        cgst_amount TEXT NOT NULL, sgst_amount TEXT NOT NULL, igst_amount TEXT NOT NULL,
        line_total TEXT NOT NULL, cost_price TEXT,
        UNIQUE (bill_no, line_no))""" % prod_fk)
    conn.execute("""CREATE TABLE IF NOT EXISTS stock_movement (
        movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER %s,
        product_name TEXT NOT NULL,
        change_qty INTEGER NOT NULL,
        balance_after INTEGER NOT NULL,
        movement_type TEXT NOT NULL CHECK (movement_type IN
            ('OPENING','SALE','CANCEL','PURCHASE','RETURN','DAMAGE','CORRECTION')),
        reference TEXT, note TEXT, created_by TEXT, created_at TEXT NOT NULL)""" % prod_fk)
    conn.execute("""CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, value TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS invoice_counter (
        fy TEXT PRIMARY KEY, last_no INTEGER NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_items_bill ON invoice_items(bill_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_move_product ON stock_movement(product_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_bill_date ON bill(date)")
    try:  # legacy databases may lack a key on bill_no; never fail because of old data
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_bill_no ON bill(bill_no)")
    except sqlite3.IntegrityError:
        log.warning("bill.bill_no has duplicate legacy values; unique index not created")
    for key, value in [("store_name", ""), ("store_address", ""), ("store_phone", ""),
                       ("store_gstin", ""), ("store_state_code", ""),
                       ("low_stock_threshold", "5")]:
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))


def _migration_3(conn):
    """Retail catalogue fields. is_demo = 1 marks demonstration products."""
    for col, decl in [("sku", "TEXT"), ("brand", "TEXT"), ("pack_size", "TEXT"),
                      ("is_demo", "INTEGER NOT NULL DEFAULT 0")]:
        _add_column(conn, "raw_inventory", col, decl)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_product_sku ON raw_inventory(sku) "
                 "WHERE sku IS NOT NULL AND sku <> ''")


MIGRATIONS = [
    (1, "legacy tables (employee, raw_inventory, bill)",
     lambda c: [c.execute(sql) for sql in LEGACY_TABLES]),
    (2, "billwise: GST, invoice items, stock movements, customers, suppliers, settings",
     _migration_2),
    (3, "retail catalogue: sku, brand, pack size, demo flag", _migration_3),
]
LATEST_VERSION = MIGRATIONS[-1][0]


def _current_version(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT NOT NULL)""")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def _has_data(conn):
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("employee", "raw_inventory", "bill"):
        if t in tables and conn.execute("SELECT 1 FROM %s LIMIT 1" % t).fetchone():
            return True
    return False


def init_db(db_path=None):
    """Create/upgrade the schema. Returns the backup path if one was taken."""
    path = db_path or get_db_path()
    backup = None
    existed = os.path.exists(path)
    with connect(path) as conn:
        with transaction(conn):
            current = _current_version(conn)
        pending = [m for m in MIGRATIONS if m[0] > current]
        if not pending:
            return None
        if existed and _has_data(conn):
            backup = backup_database(path, reason="before_migration_v%d" % pending[-1][0])
            log.info("Backup written to %s", backup)
        for version, desc, apply in pending:
            with transaction(conn):
                apply(conn)
                conn.execute("INSERT INTO schema_version(version, description, applied_at) "
                             "VALUES (?, ?, ?)", (version, desc, now_iso()))
    return backup


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_settings(conn, values):
    with transaction(conn):
        for k, v in values.items():
            conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))
