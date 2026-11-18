"""Invoice creation (one SQLite transaction), lookup, search and cancellation.

Stored invoices are never recalculated: every line keeps its own rate, tax and
amounts, and screens/PDFs read those stored values back.
"""
from datetime import datetime
from decimal import Decimal

import billing
import db
import gst_states
import inventory
import people
import security
from billing import BillingError

ACTIVE = "ACTIVE"
CANCELLED = "CANCELLED"
PREFIX = "BW"


def financial_year(when):
    start = when.year if when.month >= 4 else when.year - 1
    return "%02d%02d" % (start % 100, (start + 1) % 100)


def _next_number(conn, when):
    """Sequential per financial year, e.g. BW2627-000001. Call inside a transaction."""
    fy = financial_year(when)
    conn.execute("INSERT OR IGNORE INTO invoice_counter(fy, last_no) VALUES (?, 0)", (fy,))
    while True:
        conn.execute("UPDATE invoice_counter SET last_no = last_no + 1 WHERE fy = ?", (fy,))
        n = conn.execute("SELECT last_no FROM invoice_counter WHERE fy = ?", (fy,)).fetchone()[0]
        bill_no = "%s%s-%06d" % (PREFIX, fy, n)
        if not conn.execute("SELECT 1 FROM bill WHERE bill_no = ?", (bill_no,)).fetchone():
            return bill_no


def _details_text(totals):
    """Plain-text copy kept in the legacy bill_details column."""
    rows = ["%s\t%d\t%s" % (ln.name, ln.qty, ln.line_total) for ln in totals.lines]
    rows.append("Total\tRs. %s" % totals.grand_total)
    return "\n".join(rows)


def create_invoice(conn, cart_lines, customer, place_of_supply, payment_mode,
                   tendered=None, payment_ref="", user="", when=None):
    """Validate, then write bill + items + stock deduction atomically.

    ``customer``: dict with name, phone and optional email/address/gstin and
    ``save`` (register/update the customer record). Returns the bill number.
    """
    name = (customer.get("name") or "").strip()
    phone = (customer.get("phone") or "").strip()
    gstin = (customer.get("gstin") or "").strip().upper()
    if not name:
        raise BillingError("Please enter the customer's name.")
    if not security.valid_phone(phone):
        raise BillingError("Please enter a valid 10-digit customer phone number.")
    if gstin and not security.valid_gstin(gstin):
        raise BillingError("Invalid customer GSTIN.")
    if not cart_lines:
        raise BillingError("Cart is empty.")

    store_state = db.get_setting(conn, "store_state_code")
    supply = billing.supply_type_for(store_state, place_of_supply)
    totals = billing.calculate_invoice(cart_lines, supply)
    paid, change, ref = billing.validate_payment(payment_mode, totals.grand_total,
                                                 tendered, payment_ref)
    when = when or datetime.now()
    qty = {}
    for ln in totals.lines:
        qty[ln.product_id] = qty.get(ln.product_id, 0) + ln.qty

    with db.transaction(conn):
        bill_no = _next_number(conn, when)
        customer_id = None
        if customer.get("save"):
            customer_id = people.save_customer(conn, dict(customer, gstin=gstin,
                                                          state_code=place_of_supply))
        else:
            existing = people.find_customer_by_phone(conn, phone)
            customer_id = existing["customer_id"] if existing else None
        s = str
        conn.execute(
            "INSERT INTO bill(bill_no, date, customer_name, customer_no, bill_details, subtotal, "
            "discount_total, taxable_total, cgst_total, sgst_total, igst_total, tax_total, "
            "round_off, grand_total, supply_type, place_of_supply, customer_id, customer_gstin, "
            "payment_mode, payment_ref, amount_tendered, change_due, status, created_by, "
            "created_at, calc_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bill_no, when.strftime("%Y-%m-%d"), name, phone, _details_text(totals),
             s(totals.subtotal), s(totals.discount), s(totals.taxable), s(totals.cgst),
             s(totals.sgst), s(totals.igst), s(totals.tax), s(totals.round_off),
             s(totals.grand_total), supply, place_of_supply, customer_id, gstin, payment_mode,
             ref, s(paid), s(change), ACTIVE, user, when.isoformat(timespec="seconds"),
             billing.CALC_VERSION))
        for ln in totals.lines:
            conn.execute(
                "INSERT INTO invoice_items(bill_no, line_no, product_id, product_name, hsn_code, "
                "qty, unit_price, discount_pct, gross_amount, discount_amount, taxable_amount, "
                "gst_rate, cgst_amount, sgst_amount, igst_amount, line_total, cost_price) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bill_no, ln.line_no, ln.product_id, ln.name, ln.hsn_code, ln.qty,
                 s(ln.unit_price), s(ln.discount_pct), s(ln.gross), s(ln.discount),
                 s(ln.taxable), s(ln.gst_rate), s(ln.cgst), s(ln.sgst), s(ln.igst),
                 s(ln.line_total), None if ln.cost_price is None else s(ln.cost_price)))
        inventory.deduct_for_sale(conn, qty, bill_no, user)
    return bill_no


def _dec(v):
    return Decimal(v) if v not in (None, "") else None


MONEY_FIELDS = ("subtotal", "discount_total", "taxable_total", "cgst_total", "sgst_total",
                "igst_total", "tax_total", "round_off", "grand_total", "amount_tendered",
                "change_due")
ITEM_MONEY = ("unit_price", "discount_pct", "gross_amount", "discount_amount", "taxable_amount",
              "gst_rate", "cgst_amount", "sgst_amount", "igst_amount", "line_total", "cost_price")


def get_invoice(conn, bill_no):
    """Stored invoice as a dict (Decimals for money). None if not found.

    ``legacy`` is True for bills created by the original app: those only have
    the free-text ``bill_details`` and are displayed as-is.
    """
    row = conn.execute("SELECT * FROM bill WHERE bill_no = ?", ((bill_no or "").strip(),)).fetchone()
    if row is None:
        return None
    inv = dict(row)
    inv["legacy"] = inv.get("calc_version") is None
    inv["status"] = inv.get("status") or ACTIVE
    for f in MONEY_FIELDS:
        inv[f] = _dec(inv.get(f))
    inv["place_of_supply_label"] = gst_states.label(inv.get("place_of_supply") or "")
    items = []
    for r in conn.execute("SELECT * FROM invoice_items WHERE bill_no=? ORDER BY line_no",
                          (inv["bill_no"],)):
        it = dict(r)
        for f in ITEM_MONEY:
            it[f] = _dec(it.get(f))
        items.append(it)
    inv["items"] = items
    return inv


def search_invoices(conn, text="", date_from="", date_to="", status=""):
    sql = ("SELECT bill_no, date, customer_name, customer_no, grand_total, payment_mode, "
           "COALESCE(status, 'ACTIVE') AS status, created_by, calc_version FROM bill WHERE 1=1")
    args = []
    text = (text or "").strip()
    if text:
        sql += " AND (bill_no LIKE ? OR customer_name LIKE ? OR customer_no LIKE ?)"
        args += ["%%%s%%" % text] * 3
    if date_from:
        sql += " AND date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND date <= ?"
        args.append(date_to)
    if status:
        sql += " AND COALESCE(status, 'ACTIVE') = ?"
        args.append(status)
    sql += " ORDER BY date DESC, COALESCE(created_at, '') DESC, bill_no DESC"
    return [dict(r) for r in conn.execute(sql, args)]


def cancel_invoice(conn, bill_no, user, reason):
    """Void an invoice: keeps the record, marks it CANCELLED, restores stock."""
    if not (reason or "").strip():
        raise BillingError("Please give a reason for cancelling.")
    with db.transaction(conn):
        row = conn.execute("SELECT status FROM bill WHERE bill_no = ?", (bill_no,)).fetchone()
        if row is None:
            raise BillingError("Invoice %s not found." % bill_no)
        if (row["status"] or ACTIVE) == CANCELLED:
            raise BillingError("Invoice %s is already cancelled." % bill_no)
        conn.execute("UPDATE bill SET status=?, cancelled_at=?, cancelled_by=?, cancel_reason=? "
                     "WHERE bill_no=?", (CANCELLED, db.now_iso(), user, reason.strip(), bill_no))
        inventory.restore_for_cancel(conn, bill_no, user)
