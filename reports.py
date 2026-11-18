"""Sales, profit, GST and inventory reports (pandas) plus PDF / Excel export.

Money stays ``Decimal`` (object columns); openpyxl writes Decimals as numbers.
Cancelled invoices are excluded from every sales figure. Bills created by the
original application (free-text details, no GST data) are counted in sales
totals only where they carry a value; their quantities feed "best sellers".
No passwords, Aadhaar numbers or full customer phone numbers are exported.
"""
import logging
import os
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

import db
import inventory
from billing import money

log = logging.getLogger("billwise.reports")
ZERO = Decimal("0.00")
ACTIVE_SQL = "COALESCE(b.status, 'ACTIVE') = 'ACTIVE'"


def _d(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else ZERO
    except InvalidOperation:
        return ZERO


def month_range(d=None):
    d = d or date.today()
    start = d.replace(day=1)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1))
    return start.isoformat(), (end.fromordinal(end.toordinal() - 1)).isoformat()


def mask_phone(phone):
    p = str(phone or "")
    return p[:2] + "X" * (len(p) - 4) + p[-2:] if len(p) >= 6 else p


# ------------------------------------------------------------ legacy bills
def parse_legacy_details(text):
    """Quantity lines of an original-app bill: 'name<TAB...>qty<TAB...>amount'.

    Lines that do not parse are skipped individually (the original parser
    dropped the whole bill on the first bad line)."""
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 3 or parts[0].lower().startswith("total"):
            continue
        try:
            qty = int(parts[-2])
            amount = Decimal(parts[-1].replace("Rs.", "").strip())
        except (ValueError, InvalidOperation):
            continue
        out.append((parts[0], qty, amount))
    return out


# ------------------------------------------------------------ sales
def _bills(conn, start, end):
    return conn.execute(
        "SELECT b.* FROM bill b WHERE b.date BETWEEN ? AND ? AND " + ACTIVE_SQL +
        " ORDER BY b.date", (start, end)).fetchall()


def sales_by_day(conn, start, end):
    agg = defaultdict(lambda: [0, ZERO, ZERO, ZERO])
    for b in _bills(conn, start, end):
        a = agg[b["date"]]
        a[0] += 1
        if b["calc_version"] is None:
            total = sum((amt for _, _, amt in parse_legacy_details(b["bill_details"])), ZERO)
            a[3] += total
        else:
            a[1] += _d(b["taxable_total"])
            a[2] += _d(b["tax_total"])
            a[3] += _d(b["grand_total"])
    rows = [{"Date": k, "Invoices": v[0], "Taxable": v[1], "GST": v[2], "Sales": v[3]}
            for k, v in sorted(agg.items())]
    return pd.DataFrame(rows, columns=["Date", "Invoices", "Taxable", "GST", "Sales"])


def sales_by_month(conn, year):
    df = sales_by_day(conn, "%04d-01-01" % year, "%04d-12-31" % year)
    months = pd.DataFrame({"Month": ["%04d-%02d" % (year, m) for m in range(1, 13)]})
    if df.empty:
        for c in ("Invoices", "Taxable", "GST", "Sales"):
            months[c] = [0 if c == "Invoices" else ZERO] * 12
        return months
    df["Month"] = df["Date"].str[:7]
    g = {}
    for _, r in df.iterrows():
        x = g.setdefault(r["Month"], [0, ZERO, ZERO, ZERO])
        x[0] += r["Invoices"]
        x[1] += r["Taxable"]
        x[2] += r["GST"]
        x[3] += r["Sales"]
    for i, c in enumerate(("Invoices", "Taxable", "GST", "Sales")):
        months[c] = [g.get(m, [0, ZERO, ZERO, ZERO])[i] for m in months["Month"]]
    return months


def summary(conn, start, end):
    """Headline figures for dashboard cards."""
    df = sales_by_day(conn, start, end)
    prof = profit_summary(conn, start, end)
    return {"invoices": int(df["Invoices"].sum()) if not df.empty else 0,
            "sales": sum(df["Sales"], ZERO) if not df.empty else ZERO,
            "gst": sum(df["GST"], ZERO) if not df.empty else ZERO,
            "gross_profit": prof["gross_profit"]}


def _items(conn, start, end):
    return conn.execute(
        "SELECT i.*, b.date, b.supply_type FROM invoice_items i JOIN bill b ON b.bill_no = i.bill_no "
        "WHERE b.date BETWEEN ? AND ? AND " + ACTIVE_SQL, (start, end)).fetchall()


def profit_summary(conn, start, end):
    """Revenue = taxable value (excl. GST). Cost = stored cost price x qty.
    Cost price is treated as excluding GST (input tax is recoverable)."""
    revenue = cost = ZERO
    missing = 0
    for it in _items(conn, start, end):
        revenue += _d(it["taxable_amount"])
        if it["cost_price"] in (None, ""):
            missing += 1
        else:
            cost += money(_d(it["cost_price"]) * it["qty"])
    return {"revenue": revenue, "cost": cost, "gross_profit": revenue - cost,
            "lines_without_cost": missing}


def profit_by_product(conn, start, end):
    g = {}
    for it in _items(conn, start, end):
        x = g.setdefault(it["product_name"], [0, ZERO, ZERO])
        x[0] += it["qty"]
        x[1] += _d(it["taxable_amount"])
        x[2] += money(_d(it["cost_price"]) * it["qty"])
    rows = [{"Product": k, "Qty": v[0], "Revenue (ex GST)": v[1], "Cost": v[2],
             "Gross profit": v[1] - v[2]} for k, v in g.items()]
    df = pd.DataFrame(rows, columns=["Product", "Qty", "Revenue (ex GST)", "Cost", "Gross profit"])
    return df.sort_values("Gross profit", ascending=False, key=lambda s: s.map(float)) \
        .reset_index(drop=True)


def best_sellers(conn, start, end, top=10):
    qty = defaultdict(int)
    value = defaultdict(lambda: ZERO)
    for it in _items(conn, start, end):
        qty[it["product_name"]] += it["qty"]
        value[it["product_name"]] += _d(it["line_total"])
    for b in _bills(conn, start, end):
        if b["calc_version"] is None:
            for name, q, amt in parse_legacy_details(b["bill_details"]):
                qty[name] += q
                value[name] += amt
    rows = sorted(({"Product": k, "Qty sold": v, "Sales": value[k]} for k, v in qty.items()),
                  key=lambda r: (-r["Qty sold"], r["Product"]))[:top]
    return pd.DataFrame(rows, columns=["Product", "Qty sold", "Sales"])


def gst_summary(conn, start, end):
    g = {}
    for it in _items(conn, start, end):
        key = (_d(it["gst_rate"]).normalize(), it["supply_type"])
        x = g.setdefault(key, [ZERO, ZERO, ZERO, ZERO])
        x[0] += _d(it["taxable_amount"])
        x[1] += _d(it["cgst_amount"])
        x[2] += _d(it["sgst_amount"])
        x[3] += _d(it["igst_amount"])
    rows = [{"GST %": str(k[0]), "Supply": "Intra-state" if k[1] == "INTRA" else "Inter-state",
             "Taxable": v[0], "CGST": v[1], "SGST": v[2], "IGST": v[3],
             "Total GST": v[1] + v[2] + v[3]} for k, v in sorted(g.items())]
    return pd.DataFrame(rows, columns=["GST %", "Supply", "Taxable", "CGST", "SGST", "IGST",
                                       "Total GST"])


def inventory_valuation(conn):
    rows = []
    for p in inventory.list_products(conn):
        cost, mrp = _d(p["cost_price"]), _d(p["mrp"])
        rows.append({"ID": p["product_id"], "Product": p["product_name"],
                     "Category": p["product_cat"], "Stock": p["stock"],
                     "Cost price": money(cost), "MRP": money(mrp),
                     "Stock value (cost)": money(cost * p["stock"]),
                     "Stock value (MRP)": money(mrp * p["stock"]),
                     "Low stock": "YES" if p["is_low"] else ""})
    return pd.DataFrame(rows, columns=["ID", "Product", "Category", "Stock", "Cost price", "MRP",
                                       "Stock value (cost)", "Stock value (MRP)", "Low stock"])


def low_stock_report(conn):
    return pd.DataFrame([{"ID": p["product_id"], "Product": p["product_name"],
                          "Stock": p["stock"], "Reorder level": p["effective_reorder_level"],
                          "Supplier": p.get("supplier_name") or "", "Vendor phone": p["vendor_phn"]}
                         for p in inventory.low_stock(conn)],
                        columns=["ID", "Product", "Stock", "Reorder level", "Supplier",
                                 "Vendor phone"])


def invoice_register(conn, start, end):
    rows = conn.execute("SELECT * FROM bill WHERE date BETWEEN ? AND ? ORDER BY date, bill_no",
                        (start, end)).fetchall()
    return pd.DataFrame([{
        "Invoice": r["bill_no"], "Date": r["date"], "Customer": r["customer_name"],
        "Phone": mask_phone(r["customer_no"]), "Taxable": _d(r["taxable_total"]),
        "GST": _d(r["tax_total"]), "Total": _d(r["grand_total"]),
        "Payment": r["payment_mode"] or "", "Status": r["status"] or "ACTIVE"} for r in rows],
        columns=["Invoice", "Date", "Customer", "Phone", "Taxable", "GST", "Total", "Payment",
                 "Status"])


REPORTS = {
    "Daily sales": lambda c, s, e: sales_by_day(c, s, e),
    "Monthly sales": lambda c, s, e: sales_by_month(c, int(s[:4])),
    "Profit by product": profit_by_product,
    "Best-selling products": lambda c, s, e: best_sellers(c, s, e, top=50),
    "GST summary": gst_summary,
    "Invoice register": invoice_register,
    "Inventory valuation": lambda c, s, e: inventory_valuation(c),
    "Low stock": lambda c, s, e: low_stock_report(c),
}


# ------------------------------------------------------------ exports
def export_dir():
    return db.app_path("Reports")


def _cell(v):
    if isinstance(v, Decimal):
        return "{:,.2f}".format(v)
    return "" if v is None else str(v)


def export_excel(sheets, path):
    """sheets: {name: DataFrame}. Returns path."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col) + 2
                ws.column_dimensions[col[0].column_letter].width = min(width, 45)
    return path


def export_pdf(title, df, path, subtitle=""):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from theme import APP_NAME, COLORS, TAGLINE
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ss = getSampleStyleSheet()
    wide = len(df.columns) > 6
    doc = SimpleDocTemplate(path, pagesize=landscape(A4) if wide else A4,
                            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=title, author=APP_NAME)
    head = ss["Title"].clone("h", textColor=colors.HexColor(COLORS["navy"]), alignment=0)
    story = [Paragraph("%s &nbsp;|&nbsp; %s" % (APP_NAME, title), head),
             Paragraph("%s %s" % (TAGLINE, subtitle), ss["Normal"]), Spacer(1, 5 * mm)]
    data = [list(df.columns)] + [[_cell(v) for v in row] for row in df.itertuples(index=False)]
    if len(data) == 1:
        data.append(["No data for this period"] + [""] * (len(df.columns) - 1))
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLORS["navy"])),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(COLORS["ice"])]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(COLORS["muted"])),
    ]))
    story.append(t)
    doc.build(story)
    return path
