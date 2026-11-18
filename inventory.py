"""Products, stock movements and low-stock alerts."""
import db
import security
from billing import BillingError, money, parse_rate, to_decimal
from people import ValidationError

ADJUST_TYPES = ("PURCHASE", "RETURN", "DAMAGE", "CORRECTION")


class StockError(BillingError):
    pass


def low_stock_threshold(conn):
    try:
        return int(db.get_setting(conn, "low_stock_threshold", "5"))
    except ValueError:
        return 5


def _product_sql(where="1=1"):
    return ("SELECT p.*, s.name AS supplier_name FROM raw_inventory p "
            "LEFT JOIN supplier s ON s.supplier_id = p.supplier_id WHERE %s "
            "ORDER BY p.product_name" % where)


def _decorate(conn, rows):
    threshold = low_stock_threshold(conn)
    out = []
    for r in rows:
        d = dict(r)
        level = d["reorder_level"] if d.get("reorder_level") is not None else threshold
        d["effective_reorder_level"] = level
        d["is_low"] = d["stock"] <= level
        out.append(d)
    return out


def list_products(conn, search="", low_only=False):
    like = "%%%s%%" % (search or "").strip()
    rows = conn.execute(_product_sql("(p.product_name LIKE ? OR p.product_cat LIKE ? "
                                     "OR p.brand LIKE ? OR p.sku LIKE ? "
                                     "OR CAST(p.product_id AS TEXT) = ?)"),
                        (like, like, like, like, (search or "").strip())).fetchall()
    items = _decorate(conn, rows)
    return [p for p in items if p["is_low"]] if low_only else items


def low_stock(conn):
    return list_products(conn, low_only=True)


def get_product(conn, product_id):
    row = conn.execute(_product_sql("p.product_id = ?"), (product_id,)).fetchone()
    return _decorate(conn, [row])[0] if row else None


def categories(conn):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT product_cat FROM raw_inventory ORDER BY product_cat")]


def subcategories(conn, category):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT product_subcat FROM raw_inventory WHERE product_cat = ? "
        "ORDER BY product_subcat", (category,))]


def search_products(conn, text, limit=40):
    """Quick lookup for the billing counter: name, brand or SKU."""
    text = (text or "").strip()
    if not text:
        return []
    like = "%%%s%%" % text
    return [dict(r) for r in conn.execute(
        "SELECT product_id, product_name, stock, mrp, gst_rate FROM raw_inventory "
        "WHERE product_name LIKE ? OR brand LIKE ? OR sku = ? ORDER BY product_name LIMIT ?",
        (like, like, text.upper(), limit))]


def products_in(conn, category, subcategory):
    return [dict(r) for r in conn.execute(
        "SELECT product_id, product_name, stock, mrp, gst_rate FROM raw_inventory "
        "WHERE product_cat = ? AND product_subcat = ? ORDER BY product_name",
        (category, subcategory))]


def _validate(data, new):
    g = lambda k: str(data.get(k) if data.get(k) is not None else "").strip()  # noqa: E731
    name, cat, subcat = g("product_name"), g("product_cat"), g("product_subcat")
    if not name:
        raise ValidationError("Please enter product name.")
    if not cat:
        raise ValidationError("Please enter product category.")
    if not subcat:
        raise ValidationError("Please enter product sub-category.")
    stock = 0
    if new:
        if not g("stock").isdigit():
            raise ValidationError("Opening stock must be a whole number (0 or more).")
        stock = int(g("stock"))
    try:
        mrp = money(to_decimal(g("mrp"), "MRP"))
        cost = money(to_decimal(g("cost_price"), "cost price"))
        rate = parse_rate(g("gst_rate"))
    except BillingError as e:
        raise ValidationError(str(e)) from None
    if mrp <= 0:
        raise ValidationError("MRP must be greater than zero.")
    if cost < 0:
        raise ValidationError("Cost price cannot be negative.")
    hsn = g("hsn_code")
    if hsn and not (hsn.isdigit() and 4 <= len(hsn) <= 8):
        raise ValidationError("HSN code must be 4 to 8 digits.")
    level = g("reorder_level")
    if level and not level.isdigit():
        raise ValidationError("Low-stock level must be a whole number.")
    vendor = g("vendor_phn")
    supplier_id = data.get("supplier_id") or None
    if vendor and not security.valid_phone(vendor):
        raise ValidationError("Invalid vendor phone number.")
    sku = g("sku").upper()
    if sku and not all(ch.isalnum() or ch in "-_" for ch in sku):
        raise ValidationError("SKU may contain only letters, digits, - and _.")
    return dict(product_name=name, product_cat=cat, product_subcat=subcat, stock=stock,
                mrp=float(mrp), cost_price=float(cost), vendor_phn=vendor,
                gst_rate=str(rate), hsn_code=hsn,
                reorder_level=int(level) if level else None, supplier_id=supplier_id,
                sku=sku or None, brand=g("brand"), pack_size=g("pack_size"),
                is_demo=1 if data.get("is_demo") else 0)


def _sku_taken(conn, sku, exclude_id=None):
    if not sku:
        return False
    row = conn.execute("SELECT product_id FROM raw_inventory WHERE sku = ?", (sku,)).fetchone()
    return bool(row) and row[0] != exclude_id


def _record(conn, product_id, name, change, balance, mtype, reference="", note="", user=""):
    conn.execute("INSERT INTO stock_movement(product_id, product_name, change_qty, balance_after, "
                 "movement_type, reference, note, created_by, created_at) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (product_id, name, change, balance, mtype, reference, note, user, db.now_iso()))


def add_product(conn, data, user=""):
    p = _validate(data, True)
    with db.transaction(conn):
        if _sku_taken(conn, p["sku"]):
            raise ValidationError("SKU %s is already used by another product." % p["sku"])
        pid = conn.execute(
            "INSERT INTO raw_inventory(product_name, product_cat, product_subcat, stock, mrp, "
            "cost_price, vendor_phn, gst_rate, hsn_code, reorder_level, supplier_id, sku, brand, "
            "pack_size, is_demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p["product_name"], p["product_cat"], p["product_subcat"], p["stock"], p["mrp"],
             p["cost_price"], p["vendor_phn"], p["gst_rate"], p["hsn_code"],
             p["reorder_level"], p["supplier_id"], p["sku"], p["brand"], p["pack_size"],
             p["is_demo"])).lastrowid
        if p["stock"]:
            _record(conn, pid, p["product_name"], p["stock"], p["stock"], "OPENING",
                    note="DEMO catalogue" if p["is_demo"] else "", user=user)
    return pid


def update_product(conn, product_id, data):
    """Edits product details. Stock is changed only through adjust_stock()."""
    p = _validate(data, False)
    with db.transaction(conn):
        if _sku_taken(conn, p["sku"], product_id):
            raise ValidationError("SKU %s is already used by another product." % p["sku"])
        cur = conn.execute(
            "UPDATE raw_inventory SET product_name=?, product_cat=?, product_subcat=?, mrp=?, "
            "cost_price=?, vendor_phn=?, gst_rate=?, hsn_code=?, reorder_level=?, supplier_id=?, "
            "sku=?, brand=?, pack_size=? WHERE product_id=?",
            (p["product_name"], p["product_cat"], p["product_subcat"], p["mrp"], p["cost_price"],
             p["vendor_phn"], p["gst_rate"], p["hsn_code"], p["reorder_level"],
             p["supplier_id"], p["sku"], p["brand"], p["pack_size"], product_id))
        if cur.rowcount != 1:
            raise ValidationError("Product %s not found." % product_id)


def delete_products(conn, product_ids):
    """Original behaviour (hard delete). Invoices and stock history keep the
    product name, so past records are unaffected."""
    with db.transaction(conn):
        for pid in product_ids:
            conn.execute("DELETE FROM raw_inventory WHERE product_id = ?", (pid,))


def adjust_stock(conn, product_id, change, movement_type, note="", user=""):
    if movement_type not in ADJUST_TYPES:
        raise ValidationError("Choose an adjustment type.")
    try:
        change = int(str(change).strip())
    except ValueError:
        raise ValidationError("Quantity change must be a whole number (use - to reduce).") from None
    if change == 0:
        raise ValidationError("Quantity change cannot be zero.")
    if movement_type in ("PURCHASE", "RETURN") and change < 0:
        raise ValidationError("%s must increase stock." % movement_type.title())
    if movement_type == "DAMAGE" and change > 0:
        raise ValidationError("Damage must reduce stock.")
    if not (note or "").strip() and movement_type == "CORRECTION":
        raise ValidationError("Please give a reason for the correction.")
    with db.transaction(conn):
        row = conn.execute("SELECT product_name, stock FROM raw_inventory WHERE product_id=?",
                           (product_id,)).fetchone()
        if row is None:
            raise ValidationError("Product not found.")
        new = row["stock"] + change
        if new < 0:
            raise StockError("Stock cannot go below zero (current stock %d)." % row["stock"])
        conn.execute("UPDATE raw_inventory SET stock=? WHERE product_id=?", (new, product_id))
        _record(conn, product_id, row["product_name"], change, new, movement_type,
                note=(note or "").strip(), user=user)
    return new


def deduct_for_sale(conn, quantities, bill_no, user=""):
    """Must be called inside the invoice transaction."""
    for pid, qty in quantities.items():
        cur = conn.execute("UPDATE raw_inventory SET stock = stock - ? "
                           "WHERE product_id = ? AND stock >= ?", (qty, pid, qty))
        row = conn.execute("SELECT product_name, stock FROM raw_inventory WHERE product_id=?",
                           (pid,)).fetchone()
        if cur.rowcount != 1:
            if row is None:
                raise StockError("A product in the cart no longer exists.")
            raise StockError("Not enough stock for '%s' (available %d, needed %d)."
                             % (row["product_name"], row["stock"], qty))
        _record(conn, pid, row["product_name"], -qty, row["stock"], "SALE", bill_no, user=user)


def restore_for_cancel(conn, bill_no, user=""):
    """Put back stock for a cancelled invoice (inside its transaction)."""
    for it in conn.execute("SELECT product_id, product_name, qty FROM invoice_items "
                           "WHERE bill_no = ?", (bill_no,)).fetchall():
        if it["product_id"] is None:
            continue  # product was deleted since; nothing to restore
        cur = conn.execute("UPDATE raw_inventory SET stock = stock + ? WHERE product_id = ?",
                           (it["qty"], it["product_id"]))
        if cur.rowcount:
            bal = conn.execute("SELECT stock FROM raw_inventory WHERE product_id=?",
                               (it["product_id"],)).fetchone()[0]
            _record(conn, it["product_id"], it["product_name"], it["qty"], bal, "CANCEL",
                    bill_no, user=user)


def movements(conn, product_id=None, limit=1000):
    if product_id:
        rows = conn.execute("SELECT * FROM stock_movement WHERE product_id=? "
                            "ORDER BY movement_id DESC LIMIT ?", (product_id, limit))
    else:
        rows = conn.execute("SELECT * FROM stock_movement ORDER BY movement_id DESC LIMIT ?",
                            (limit,))
    return [dict(r) for r in rows]
