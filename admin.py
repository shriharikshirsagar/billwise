"""Billwise administration panel.

Keeps the original screens and class names - login_page, Admin_Page
(dashboard), Inventory (+ add_product / Update_Product), Employee
(+ add_employee / Update_Employee), Invoice (+ open_bill) and Analytics - and
adds Customers, Suppliers, Reports and Settings. Every action goes through the
tested service modules; screens never build SQL themselves.
"""
import logging
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import simpledialog

import ttkbootstrap as ttk

import billing
import db
import demo_catalogue
import gst_states
import inventory
import invoices
import people
import reports
import security
import theme
import ui
from billing import BillingError, fmt

C = theme.COLORS
log = logging.getLogger("billwise.admin")

root = None
page1 = None
shell = None
current_user = None
GST_RATES = ["0", "0.25", "3", "5", "12", "18", "28", "40"]


def can(permission):
    return bool(current_user) and security.can(current_user["designation"], permission)


# ---------------------------------------------------------------- login / navigation
def login(emp_id, password):
    global current_user
    with db.connect() as conn:
        user = people.authenticate(conn, emp_id, password)
    if not user:
        return "Incorrect username or password."
    if not security.can(user["designation"], "admin_panel"):
        return "You are not an admin. Use the billing counter instead."
    current_user = user
    log.info("Admin panel sign-in: %s", user["emp_id"])
    page1.pack_forget()
    open_admin()
    return None


PAGES = [  # key, title, icon, permission, factory
    ("dashboard", "Dashboard", "dashboard", "admin_panel", lambda p: Admin_Page(p)),
    ("inventory", "Inventory", "inventory", "inventory", lambda p: Inventory(p)),
    ("employees", "Employees", "employees", "employees", lambda p: Employee(p)),
    ("invoices", "Invoices", "invoices", "invoices", lambda p: Invoice(p)),
    ("customers", "Customers", "customers", "customers", lambda p: Customers(p)),
    ("suppliers", "Suppliers", "suppliers", "suppliers", lambda p: Suppliers(p)),
    ("analytics", "Analytics", "analytics", "analytics", lambda p: Analytics(p)),
    ("reports", "Reports", "reports", "reports", lambda p: Reports(p)),
    ("settings", "Settings", "settings", "settings", lambda p: Settings(p)),
]


SECTIONS = [("Overview", ("dashboard",)),
            ("Operations", ("inventory", "invoices", "customers", "suppliers")),
            ("Insights", ("analytics", "reports")),
            ("Administration", ("employees", "settings"))]


def open_admin():
    global shell
    allowed = [p for p in PAGES if can(p[3])]
    pages = {k: (title, factory) for k, title, _, _, factory in allowed}
    nav = []
    for section, keys in SECTIONS:
        entries = [p for p in allowed if p[0] in keys]
        if entries:
            nav.append((None, section))
            nav += [(k, title, icon, (lambda key=k: shell.show(key))) for k, title, icon, _, _ in entries]
    bottom = [("logout", "Sign out", "logout", Logout), ("exit", "Exit Billwise", "exit", exitt)]
    who = "%s  (%s, %s)" % (current_user["name"], current_user["emp_id"], current_user["designation"])
    shell = ui.Shell(root, pages, nav, bottom, user_text=who, subtitle="Administration",
                     user=(current_user["name"], "%s  ·  %s" % (current_user["designation"],
                                                                 current_user["emp_id"])))
    shell.pack(fill="both", expand=True)
    shell.show("dashboard")


def navigate(key):
    if shell and key in shell.pages:
        shell.show(key)


def Logout():
    global shell, current_user
    if ui.confirm(root, "Logout", "Are you sure you want to logout?"):
        shell.destroy()
        shell = None
        current_user = None
        page1.pack(fill="both", expand=True)
        page1.entry1.focus_set()


def exitt():
    if ui.confirm(root, "Exit", "Are you sure you want to exit?"):
        root.destroy()


class login_page(ui.LoginView):
    def __init__(self, top):
        super().__init__(top, "Administration", "Admins and managers sign in here.", login)


class FirstRunSetup(ui.Dialog):
    """Shown once, when the database has no employees: creates EMP0000."""

    def __init__(self, parent, on_done):
        super().__init__(parent, "Welcome to billwise - first-time setup", width=620)
        self.on_done = on_done
        ttk.Label(self.body, text="Create the administrator account (Employee ID EMP0000) and "
                  "enter your store details. No default password exists.",
                  style="CardMuted.TLabel", wraplength=560).pack(anchor="w", pady=(0, 8))
        f = ttk.Frame(self.body, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        self.name = g.add("Administrator name", ttk.Entry, span=2)
        self.pw1 = g.add("Password (min. %d chars)" % security.MIN_PASSWORD_LENGTH, ttk.Entry, show="•")
        self.pw2 = g.add("Confirm password", ttk.Entry, show="•")
        self.store = g.add("Store name", ttk.Entry, span=2)
        self.state_box = g.add("Store state", ttk.Combobox,
                           values=gst_states.labels(), state="readonly")
        self.gstin = g.add("Store GSTIN (optional)", ttk.Entry)
        ttk.Button(self.buttons, text="Create administrator", bootstyle="success",
                   command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="Exit", bootstyle="secondary-outline",
                   command=lambda: root.destroy()).pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", lambda: root.destroy())
        self.present()

    def save(self):
        if self.pw1.get() != self.pw2.get():
            ui.error(self, "Oops!", "Passwords do not match.")
            return
        state = gst_states.code_from_label(self.state_box.get())
        gstin = self.gstin.get().strip().upper()
        if not state:
            ui.error(self, "Oops!", "Choose the store's state.")
            return
        if gstin and not security.valid_gstin(gstin):
            ui.error(self, "Oops!", "Invalid GSTIN.")
            return
        try:
            with db.connect() as conn:
                people.create_first_admin(conn, self.name.get(), self.pw1.get(), {
                    "store_name": self.store.get().strip(), "store_state_code": state,
                    "store_gstin": gstin})
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        ui.info(self, "Ready", "Administrator created.\nSign in with Employee ID EMP0000.")
        self.destroy()
        self.on_done()


# ---------------------------------------------------------------- shared helpers
def toolbar(parent):
    bar = ttk.Frame(parent, style="Card.TFrame")
    bar.pack(fill="x", pady=(0, 10))
    return bar


def search_box(bar, command, width=30):
    var = tk.StringVar()
    e = ttk.Entry(bar, textvariable=var, width=width)
    e.pack(side="left", ipady=2)
    e.bind("<Return>", lambda ev: command())
    ttk.Button(bar, text="Search", bootstyle="primary", command=command).pack(side="left", padx=(8, 0))
    return var, e


def parse_date(text, label):
    text = (text or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise BillingError("%s must be a date like 2026-11-18." % label) from None


# ---------------------------------------------------------------- dashboard
class Admin_Page(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        today = date.today().isoformat()
        m_start, m_end = reports.month_range()
        with db.connect() as conn:
            t = reports.summary(conn, today, today)
            m = reports.summary(conn, m_start, m_end)
            low = inventory.low_stock(conn)
            recent = invoices.search_invoices(conn)[:12]
        cards = ttk.Frame(self)
        cards.pack(fill="x")
        avg = (t["sales"] / t["invoices"]) if t["invoices"] else 0
        items = [("Today's sales", "Rs. " + fmt(t["sales"]), "Metric.TLabel",
                  "GST collected Rs. %s" % fmt(t["gst"])),
                 ("Invoices today", str(t["invoices"]), "Metric.TLabel",
                  "Average bill Rs. %s" % fmt(avg)),
                 ("Sales this month", "Rs. " + fmt(m["sales"]), "Metric.TLabel",
                  "%d invoices" % m["invoices"]),
                 ("Gross profit (month)", "Rs. " + fmt(m["gross_profit"]), "MetricGreen.TLabel",
                  "Excl. GST, after cost"),
                 ("Low-stock items", str(len(low)), "MetricAmber.TLabel" if low else "Metric.TLabel",
                  "At or below reorder level")]
        for i, (label, value, style, caption) in enumerate(items):
            cards.columnconfigure(i, weight=1, uniform="m")
            ui.metric_card(cards, label, value, style, caption).grid(row=0, column=i, sticky="nsew",
                                                                    padx=(0 if i == 0 else 12, 0))
        lower = ttk.Frame(self)
        lower.pack(fill="both", expand=True, pady=(14, 0))
        lower.columnconfigure(0, weight=3, uniform="dash")
        lower.columnconfigure(1, weight=2, uniform="dash")
        lower.rowconfigure(0, weight=1)
        lower.rowconfigure(1, weight=1)
        cc = ui.card(lower, "Sales - last 7 days", "Rs., active invoices")
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        self._week_chart(cc)
        lc = ui.card(lower, "Low-stock alerts")
        lc.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
        if can("inventory"):
            ttk.Button(lc.head, text="View all \u203a", bootstyle="warning-link",
                       command=lambda: navigate("inventory")).pack(side="right")
        lt = ui.DataTable(lc, [("product_name", "Product", 230, "w"), ("stock", "Stock", 58, "e"),
                               ("effective_reorder_level", "Min", 48, "e")], height=4)
        lt.pack(fill="both", expand=True)
        lt.set_rows(low, iid_key="product_id", tag_fn=lambda r: ["low"])
        rc = ui.card(lower, "Recent invoices", "double-click to view")
        rc.grid(row=1, column=0, columnspan=2, sticky="nsew")
        rt = ui.DataTable(rc, [("bill_no", "Invoice", 140, "w"), ("date", "Date", 100, "w"),
                               ("customer_name", "Customer", 220, "w"), ("payment_mode", "Payment", 90, "w"),
                               ("grand_total", "Total", 100, "e"), ("status", "Status", 100, "w")],
                          height=4)
        rt.pack(fill="both", expand=True)
        for r in recent:
            r["grand_total"] = billing.money(r["grand_total"]) if r["grand_total"] else ""
        rt.set_rows(recent, iid_key="bill_no",
                    tag_fn=lambda r: ["cancelled"] if r["status"] == "CANCELLED" else [])
        rt.on_double_click(lambda r: open_bill(self, r["bill_no"]))

    def _week_chart(self, parent):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        end = date.today()
        days = [end - timedelta(days=i) for i in range(6, -1, -1)]
        with db.connect() as conn:
            df = reports.sales_by_day(conn, days[0].isoformat(), end.isoformat())
        by_day = dict(zip(df["Date"], df["Sales"])) if not df.empty else {}
        vals = [float(by_day.get(d.isoformat(), 0)) for d in days]
        fig = Figure(figsize=(5, 1.9), dpi=100, facecolor=C["white"])
        ax = fig.add_subplot(111)
        ax.set_facecolor(C["white"])
        bars = ax.bar([d.strftime("%a %d") for d in days], vals, color=C["blue"], width=0.6)
        bars[-1].set_color(C["green"])  # today
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color(C["muted"])
        ax.tick_params(colors=C["muted"], labelsize=8, left=False)
        ax.set_yticks([])
        for b, v in zip(bars, vals):
            if v:
                ax.text(b.get_x() + b.get_width() / 2, v, "{:,.0f}".format(v), ha="center",
                        va="bottom", fontsize=8, color=C["text"])
        if not any(vals):
            ax.text(0.5, 0.5, "No sales in the last 7 days", ha="center", va="center",
                    color=C["muted"], transform=ax.transAxes)
        fig.tight_layout(pad=0.4)
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)


# ---------------------------------------------------------------- inventory
class Inventory(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        self.query, self.entry1 = search_box(bar, self.search_product)
        self.low_only = tk.BooleanVar(value=False)
        ui.on_card(ttk.Checkbutton(bar, text="Low stock only", variable=self.low_only,
                                   bootstyle="warning-round-toggle", command=self.DisplayData)
                   ).pack(side="left", padx=16)
        acts = toolbar(c)
        ttk.Button(acts, text="ADD PRODUCT", bootstyle="success", command=self.add_product).pack(side="left")
        ttk.Button(acts, text="UPDATE PRODUCT", bootstyle="primary-outline",
                   command=self.update_product).pack(side="left", padx=6)
        ttk.Button(acts, text="Adjust stock", bootstyle="primary-outline", command=self.adjust).pack(side="left")
        ttk.Button(acts, text="Stock history", bootstyle="secondary-outline",
                   command=self.history).pack(side="left", padx=6)
        ttk.Button(acts, text="DELETE PRODUCT", bootstyle="danger", command=self.delete_product).pack(side="right")
        cols = [("product_id", "ID", 44, "e"), ("sku", "SKU", 100, "w"), ("product_name", "Name", 250, "w"),
                ("product_cat", "Category", 110, "w"), ("product_subcat", "Sub-category", 110, "w"),
                ("stock", "In stock", 70, "e"), ("mrp", "MRP", 80, "e"), ("cost_price", "Cost", 80, "e"),
                ("gst_rate", "GST %", 60, "e"), ("hsn_code", "HSN", 70, "w"),
                ("supplier", "Supplier / vendor", 130, "w"), ("kind", "Data", 60, "w")]
        self.tree = ui.DataTable(c, cols, height=16, selectmode="extended")
        self.tree.pack(fill="both", expand=True)
        self.tree.on_double_click(lambda r: self.update_product())
        self.hint = ttk.Label(c, text="", style="CardMuted.TLabel")
        self.hint.pack(anchor="w", pady=(8, 0))
        self.DisplayData()

    def DisplayData(self):
        with db.connect() as conn:
            rows = inventory.list_products(conn, self.query.get(), self.low_only.get())
        for r in rows:
            r["mrp"] = billing.money(r["mrp"])
            r["cost_price"] = billing.money(r["cost_price"] or 0)
            r["gst_rate"] = r["gst_rate"] if r["gst_rate"] not in (None, "") else "NOT SET"
            r["supplier"] = r.get("supplier_name") or r.get("vendor_phn") or ""
            r["kind"] = "DEMO" if r.get("is_demo") else ""
        self.tree.set_rows(rows, iid_key="product_id", tag_fn=lambda r: ["low"] if r["is_low"] else [])
        low = sum(1 for r in rows if r["is_low"])
        demo = sum(1 for r in rows if r.get("is_demo"))
        self.hint.configure(text="%d products shown.  %s%s" % (
            len(rows), ("%d at or below their reorder level (amber).  " % low) if low else "",
            ("%d DEMO products (placeholder prices) - remove in Settings before real use." % demo) if demo else ""))

    def search_product(self):
        self.DisplayData()
        if self.query.get().strip() and not self.tree.rows:
            ui.error(self, "Oops!!", "No product matches '%s'." % self.query.get().strip())

    def _one(self, action):
        sel = self.tree.selected()
        if not sel:
            ui.error(self, "Error", "Please choose a product to %s." % action)
            return None
        if len(sel) > 1:
            ui.error(self, "Error", "Can only %s one product at a time." % action)
            return None
        return sel[0]

    def add_product(self):
        add_product(self, self.DisplayData)

    def update_product(self):
        p = self._one("update")
        if p:
            Update_Product(self, p["product_id"], self.DisplayData)

    def adjust(self):
        p = self._one("adjust")
        if p:
            StockAdjust(self, p["product_id"], self.DisplayData)

    def history(self):
        sel = self.tree.selected()
        StockHistory(self, sel[0]["product_id"] if len(sel) == 1 else None)

    def delete_product(self):
        sel = self.tree.selected()
        if not sel:
            ui.error(self, "Error!!", "Please select a product.")
            return
        names = ", ".join(p["product_name"] for p in sel[:5]) + (" ..." if len(sel) > 5 else "")
        if ui.confirm(self, "Confirm", "Delete %d product(s)?\n%s\n\nPast invoices keep the product "
                      "name and amounts." % (len(sel), names)):
            with db.connect() as conn:
                inventory.delete_products(conn, [p["product_id"] for p in sel])
            ui.info(self, "Success!!", "Products deleted from database.")
            self.DisplayData()


class ProductDialog(ui.Dialog):
    def __init__(self, parent, product_id, on_saved):
        self.product_id = product_id
        self.on_saved = on_saved
        super().__init__(parent, "Update product" if product_id else "Add product", width=680)
        with db.connect() as conn:
            cats = inventory.categories(conn)
            self.suppliers = people.list_suppliers(conn)
            p = inventory.get_product(conn, product_id) if product_id else None
            threshold = inventory.low_stock_threshold(conn)
        f = ttk.Frame(self.body, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        self.entry1 = g.add("Product name (as printed on the invoice)", ttk.Entry, span=2)
        self.entry_brand = g.add("Brand", ttk.Entry)
        self.entry_pack = g.add("Pack size (e.g. 1 kg, 500 ml)", ttk.Entry)
        self.entry_sku = g.add("SKU (optional, unique)", ttk.Entry)
        self.entry2 = g.add("Category", ttk.Combobox, values=cats)
        self.entry6 = g.add("Sub-category", ttk.Combobox)
        self.entry2.bind("<<ComboboxSelected>>", self._subcats)
        self.entry2.bind("<FocusOut>", self._subcats)
        if product_id:
            self.entry3 = g.add("Current stock (change via Adjust stock)", ttk.Entry)
        else:
            self.entry3 = g.add("Opening stock", ttk.Entry)
        self.entry_level = g.add("Low-stock level (blank = %d)" % threshold, ttk.Entry)
        self.entry4 = g.add("MRP (incl. GST)", ttk.Entry)
        self.entry7 = g.add("Cost price (excl. GST)", ttk.Entry)
        self.entry_gst = g.add("GST rate %", ttk.Combobox, values=GST_RATES)
        self.entry_hsn = g.add("HSN code (optional)", ttk.Entry)
        self.entry_sup = g.add("Supplier", ttk.Combobox, state="readonly",
                               values=["(none)"] + [s["name"] for s in self.suppliers])
        self.entry8 = g.add("Vendor phone (optional)", ttk.Entry)
        self.entry_sup.set("(none)")
        if p:
            for w, v in [(self.entry1, p["product_name"]), (self.entry2, p["product_cat"]),
                         (self.entry6, p["product_subcat"]), (self.entry3, p["stock"]),
                         (self.entry4, billing.money(p["mrp"])),
                         (self.entry7, billing.money(p["cost_price"] or 0)),
                         (self.entry_gst, p["gst_rate"] or ""), (self.entry_hsn, p["hsn_code"] or ""),
                         (self.entry8, p["vendor_phn"] or ""),
                         (self.entry_brand, p.get("brand") or ""), (self.entry_pack, p.get("pack_size") or ""),
                         (self.entry_sku, p.get("sku") or ""),
                         (self.entry_level, "" if p["reorder_level"] is None else p["reorder_level"])]:
                ui.set_entry(w, v)
            self.entry3.configure(state="readonly")
            for s in self.suppliers:
                if s["supplier_id"] == p["supplier_id"]:
                    self.entry_sup.set(s["name"])
        ttk.Button(self.buttons, text="UPDATE" if product_id else "ADD", bootstyle="success",
                   command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="CLEAR", bootstyle="secondary-outline",
                   command=self.clearr).pack(side="right", padx=8)
        self.present()

    def _subcats(self, event=None):
        with db.connect() as conn:
            self.entry6.configure(values=inventory.subcategories(conn, self.entry2.get()))

    def clearr(self):
        for w in (self.entry1, self.entry2, self.entry6, self.entry4, self.entry7, self.entry_gst,
                  self.entry_hsn, self.entry8, self.entry_level, self.entry_brand, self.entry_pack,
                  self.entry_sku):
            ui.set_entry(w, "")
        if not self.product_id:
            ui.set_entry(self.entry3, "")
        self.entry_sup.set("(none)")

    def data(self):
        sup = next((s["supplier_id"] for s in self.suppliers if s["name"] == self.entry_sup.get()), None)
        return {"product_name": self.entry1.get(), "product_cat": self.entry2.get(),
                "product_subcat": self.entry6.get(), "stock": self.entry3.get(),
                "mrp": self.entry4.get(), "cost_price": self.entry7.get(),
                "gst_rate": self.entry_gst.get(), "hsn_code": self.entry_hsn.get(),
                "reorder_level": self.entry_level.get(), "vendor_phn": self.entry8.get(),
                "supplier_id": sup, "brand": self.entry_brand.get(), "pack_size": self.entry_pack.get(),
                "sku": self.entry_sku.get()}

    def save(self):
        try:
            with db.connect() as conn:
                if self.product_id:
                    inventory.update_product(conn, self.product_id, self.data())
                    msg = "Product successfully updated in inventory."
                else:
                    inventory.add_product(conn, self.data(), current_user["emp_id"])
                    msg = "Product successfully added in inventory."
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        ui.info(self, "Success!!", msg)
        self.destroy()
        self.on_saved()


class add_product(ProductDialog):
    def __init__(self, parent, on_saved):
        super().__init__(parent, None, on_saved)


class Update_Product(ProductDialog):
    pass


class StockAdjust(ui.Dialog):
    def __init__(self, parent, product_id, on_saved):
        super().__init__(parent, "Adjust stock", width=520)
        self.product_id, self.on_saved = product_id, on_saved
        with db.connect() as conn:
            p = inventory.get_product(conn, product_id)
        ttk.Label(self.body, text="%s  -  current stock %d" % (p["product_name"], p["stock"]),
                  style="CardField.TLabel").pack(anchor="w", pady=(0, 6))
        f = ttk.Frame(self.body, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        self.kind = g.add("Type", ttk.Combobox, values=inventory.ADJUST_TYPES, state="readonly")
        self.kind.set("PURCHASE")
        self.change = g.add("Quantity change (+ add / - remove)", ttk.Entry)
        self.note = g.add("Note / reason", ttk.Entry, span=2)
        ttk.Label(self.body, text="PURCHASE / RETURN add stock, DAMAGE removes it, CORRECTION "
                  "can do either (reason required).", style="CardMuted.TLabel",
                  wraplength=460).pack(anchor="w", pady=(6, 0))
        ttk.Button(self.buttons, text="Save adjustment", bootstyle="success",
                   command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="right", padx=8)
        self.present()

    def save(self):
        try:
            with db.connect() as conn:
                new = inventory.adjust_stock(conn, self.product_id, self.change.get(), self.kind.get(),
                                             self.note.get(), current_user["emp_id"])
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        ui.info(self, "Saved", "Stock is now %d." % new)
        self.destroy()
        self.on_saved()


class StockHistory(ui.Dialog):
    def __init__(self, parent, product_id=None):
        super().__init__(parent, "Stock movement history", width=900, height=560)
        with db.connect() as conn:
            rows = inventory.movements(conn, product_id)
        ttk.Label(self.body, text="Latest movements first%s." % ("" if product_id else " (all products)"),
                  style="CardMuted.TLabel").pack(anchor="w")
        t = ui.DataTable(self.body, [("created_at", "When", 150, "w"), ("product_name", "Product", 180, "w"),
                                     ("movement_type", "Type", 100, "w"), ("change_qty", "Change", 70, "e"),
                                     ("balance_after", "Balance", 70, "e"), ("reference", "Reference", 120, "w"),
                                     ("note", "Note", 150, "w"), ("created_by", "By", 80, "w")], height=12)
        t.pack(fill="both", expand=True, pady=(6, 0))
        t.set_rows(rows, iid_key="movement_id")
        ttk.Button(self.buttons, text="Close", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="right")
        self.present()


# ---------------------------------------------------------------- employees
class Employee(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        self.query, self.entry1 = search_box(bar, self.search_emp)
        ttk.Button(bar, text="DELETE EMPLOYEE", bootstyle="danger", command=self.delete_emp).pack(side="right")
        ttk.Button(bar, text="UPDATE EMPLOYEE", bootstyle="primary-outline",
                   command=self.update_emp).pack(side="right", padx=6)
        ttk.Button(bar, text="ADD EMPLOYEE", bootstyle="success", command=self.add_emp).pack(side="right")
        cols = [("emp_id", "Employee ID", 100, "w"), ("name", "Employee Name", 200, "w"),
                ("contact_num", "Contact No.", 110, "w"), ("address", "Address", 240, "w"),
                ("aadhar_num", "Aadhaar No.", 130, "w"), ("designation", "Designation", 110, "w")]
        self.tree = ui.DataTable(c, cols, height=16, selectmode="extended")
        self.tree.pack(fill="both", expand=True)
        self.tree.on_double_click(lambda r: self.update_emp())
        ttk.Label(c, text="Passwords are stored as salted hashes and are never displayed. "
                  "Aadhaar numbers are masked.", style="CardMuted.TLabel").pack(anchor="w", pady=(8, 0))
        self.DisplayData()

    def DisplayData(self):
        with db.connect() as conn:
            self.tree.set_rows(people.list_employees(conn, self.query.get()), iid_key="emp_id")

    def search_emp(self):
        self.DisplayData()
        if self.query.get().strip() and not self.tree.rows:
            ui.error(self, "Oops!!", "Employee ID: %s not found." % self.query.get().strip())

    def add_emp(self):
        add_employee(self, self.DisplayData)

    def update_emp(self):
        sel = self.tree.selected()
        if len(sel) != 1:
            ui.error(self, "Error", "Please select one employee to update.")
            return
        Update_Employee(self, sel[0]["emp_id"], self.DisplayData)

    def delete_emp(self):
        sel = self.tree.selected()
        if not sel:
            ui.error(self, "Error!!", "Please select an employee.")
            return
        if not ui.confirm(self, "Confirm", "Are you sure you want to delete %d employee(s)?" % len(sel)):
            return
        try:
            with db.connect() as conn:
                people.delete_employees(conn, [e["emp_id"] for e in sel], current_user["emp_id"])
        except BillingError as e:
            ui.error(self, "Error!!", str(e))
            return
        ui.info(self, "Success!!", "Employee(s) deleted from database.")
        self.DisplayData()


class EmployeeDialog(ui.Dialog):
    def __init__(self, parent, emp_id, on_saved):
        self.emp_id, self.on_saved = emp_id, on_saved
        super().__init__(parent, "Update employee %s" % emp_id if emp_id else "Add employee", width=640)
        f = ttk.Frame(self.body, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        self.entry1 = g.add("Employee name", ttk.Entry)
        self.entry2 = g.add("Contact number", ttk.Entry)
        self.entry4 = g.add("Designation", ttk.Combobox, values=security.ROLES)
        self.entry3 = g.add("Aadhaar number" + (" (blank = keep)" if emp_id else ""), ttk.Entry)
        self.entry5 = g.add("Address", ttk.Entry, span=2)
        self.entry6 = g.add("Password" + (" (blank = keep)" if emp_id else ""), ttk.Entry, show="•")
        self.entry7 = g.add("Confirm password", ttk.Entry, show="•")
        ttk.Label(self.body, text="Admin: full access.  Manager: admin panel without Employees and "
                  "Settings.  Any other designation: billing counter only.",
                  style="CardMuted.TLabel", wraplength=580).pack(anchor="w", pady=(8, 0))
        if emp_id:
            with db.connect() as conn:
                e = people.get_employee(conn, emp_id)
            for w, v in [(self.entry1, e["name"]), (self.entry2, e["contact_num"]),
                         (self.entry4, e["designation"]), (self.entry5, e["address"])]:
                ui.set_entry(w, v)
            ttk.Label(self.body, text="Current Aadhaar: %s" % (e["aadhar_num"] or "not recorded"),
                      style="CardMuted.TLabel").pack(anchor="w")
        ttk.Button(self.buttons, text="UPDATE" if emp_id else "ADD", bootstyle="success",
                   command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="CLEAR", bootstyle="secondary-outline",
                   command=self.clearr).pack(side="right", padx=8)
        self.present()

    def clearr(self):
        for w in (self.entry1, self.entry2, self.entry3, self.entry4, self.entry5, self.entry6, self.entry7):
            ui.set_entry(w, "")

    def save(self):
        if self.entry6.get() != self.entry7.get():
            ui.error(self, "Oops!", "Passwords do not match.")
            return
        data = {"name": self.entry1.get(), "contact_num": self.entry2.get(),
                "aadhar_num": self.entry3.get(), "designation": self.entry4.get(),
                "address": self.entry5.get(), "password": self.entry6.get()}
        try:
            with db.connect() as conn:
                if self.emp_id:
                    people.update_employee(conn, self.emp_id, data)
                    msg = "Employee ID: %s successfully updated in database." % self.emp_id
                else:
                    msg = "Employee ID: %s successfully added in database." % people.add_employee(conn, data)
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        ui.info(self, "Success!!", msg)
        self.destroy()
        self.on_saved()


class add_employee(EmployeeDialog):
    def __init__(self, parent, on_saved):
        super().__init__(parent, None, on_saved)


class Update_Employee(EmployeeDialog):
    pass


# ---------------------------------------------------------------- invoices
class Invoice(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        self.query, self.entry1 = search_box(bar, self.search_inv, width=24)
        ttk.Label(bar, text="From", style="Card.TLabel").pack(side="left", padx=(16, 4))
        self.d_from = ttk.Entry(bar, width=11)
        self.d_from.pack(side="left")
        ttk.Label(bar, text="To", style="Card.TLabel").pack(side="left", padx=(8, 4))
        self.d_to = ttk.Entry(bar, width=11)
        self.d_to.pack(side="left")
        self.status = ttk.Combobox(bar, values=["All", "ACTIVE", "CANCELLED"], state="readonly", width=11)
        self.status.set("All")
        self.status.pack(side="left", padx=8)
        self.status.bind("<<ComboboxSelected>>", lambda e: self.DisplayData())
        acts = toolbar(c)
        ttk.Button(acts, text="View", bootstyle="primary", command=self.view).pack(side="left")
        ttk.Button(acts, text="Reprint PDF", bootstyle="primary-outline", command=self.reprint).pack(side="left", padx=6)
        ttk.Button(acts, text="Export register (Excel)", bootstyle="secondary-outline",
                   command=self.export).pack(side="left")
        if can("cancel_invoice"):
            ttk.Button(acts, text="CANCEL INVOICE", bootstyle="danger",
                       command=self.delete_invoice).pack(side="right")
        cols = [("bill_no", "Bill Number", 140, "w"), ("date", "Date", 100, "w"),
                ("customer_name", "Customer Name", 200, "w"), ("customer_no", "Customer Phone No.", 140, "w"),
                ("grand_total", "Total", 100, "e"), ("payment_mode", "Payment", 90, "w"),
                ("status", "Status", 100, "w"), ("created_by", "Cashier", 90, "w")]
        self.tree = ui.DataTable(c, cols, height=16)
        self.tree.pack(fill="both", expand=True)
        self.tree.on_double_click(self.double_tap)
        self.hint = ttk.Label(c, text="Dates as YYYY-MM-DD (optional). Cancelled invoices are kept "
                              "for the record and shown in grey.", style="CardMuted.TLabel")
        self.hint.pack(anchor="w", pady=(8, 0))
        self.DisplayData()

    def filters(self):
        st = self.status.get()
        return (self.query.get(), parse_date(self.d_from.get(), "From"), parse_date(self.d_to.get(), "To"),
                "" if st == "All" else st)

    def DisplayData(self):
        try:
            f = self.filters()
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        with db.connect() as conn:
            rows = invoices.search_invoices(conn, *f)
        for r in rows:
            r["grand_total"] = billing.money(r["grand_total"]) if r["grand_total"] else ""
            r["payment_mode"] = r["payment_mode"] or ("(original app)" if r["calc_version"] is None else "")
        self.tree.set_rows(rows, iid_key="bill_no",
                           tag_fn=lambda r: ["cancelled"] if r["status"] == "CANCELLED" else [])

    def search_inv(self):
        self.DisplayData()
        if self.query.get().strip() and not self.tree.rows:
            ui.error(self, "Oops!!", "Bill Number: %s not found." % self.query.get().strip())

    def _one(self):
        sel = self.tree.selected()
        if not sel:
            ui.error(self, "Error!!", "Please select an invoice")
            return None
        return sel[0]

    def double_tap(self, row):
        open_bill(self, row["bill_no"])

    def view(self):
        r = self._one()
        if r:
            open_bill(self, r["bill_no"])

    def reprint(self):
        r = self._one()
        if r:
            ui.print_invoice(self, r["bill_no"])

    def delete_invoice(self):
        """Approved change: invoices are cancelled (voided), never deleted."""
        r = self._one()
        if not r:
            return
        if r["status"] == "CANCELLED":
            ui.error(self, "Oops!", "Invoice %s is already cancelled." % r["bill_no"])
            return
        reason = simpledialog.askstring("Cancel invoice", "Reason for cancelling %s:" % r["bill_no"], parent=self)
        if not reason:
            return
        if not ui.confirm(self, "Confirm", "Cancel invoice %s?\nThe record is kept, marked CANCELLED, "
                          "and its stock is returned to inventory." % r["bill_no"]):
            return
        try:
            with db.connect() as conn:
                invoices.cancel_invoice(conn, r["bill_no"], current_user["emp_id"], reason)
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        ui.info(self, "Success!!", "Invoice %s cancelled." % r["bill_no"])
        self.DisplayData()

    def export(self):
        try:
            _, start, end, _ = self.filters()
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        start, end = start or "0000-01-01", end or "9999-12-31"
        import os
        path = os.path.join(reports.export_dir(), "invoice_register_%s.xlsx" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        with db.connect() as conn:
            reports.export_excel({"Invoice register": reports.invoice_register(conn, start, end)}, path)
        ui.info(self, "Exported", "Saved to:\n%s" % path)


def open_bill(parent, bill_no):
    return ui.InvoicePreview(parent, bill_no)


# ---------------------------------------------------------------- customers
class Customers(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        self.query, _ = search_box(bar, self.DisplayData)
        ttk.Button(bar, text="Purchase history", bootstyle="primary", command=self.history).pack(side="right")
        ttk.Button(bar, text="Edit customer", bootstyle="primary-outline", command=self.edit).pack(side="right", padx=6)
        ttk.Button(bar, text="Register customer", bootstyle="success",
                   command=lambda: CustomerDialog(self, None, self.DisplayData)).pack(side="right")
        cols = [("name", "Name", 200, "w"), ("phone", "Phone", 110, "w"), ("email", "Email", 180, "w"),
                ("state", "State", 150, "w"), ("gstin", "GSTIN", 140, "w"),
                ("invoices", "Invoices", 70, "e"), ("spent", "Total spent", 110, "e")]
        self.tree = ui.DataTable(c, cols, height=16)
        self.tree.pack(fill="both", expand=True)
        self.tree.on_double_click(lambda r: self.history())
        self.DisplayData()

    def DisplayData(self):
        with db.connect() as conn:
            rows = people.list_customers(conn, self.query.get())
        for r in rows:
            r["state"] = gst_states.NAME_BY_CODE.get(r["state_code"] or "", "")
            r["spent"] = billing.money(r["spent"])
        self.tree.set_rows(rows, iid_key="customer_id")

    def _one(self):
        sel = self.tree.selected()
        if not sel:
            ui.error(self, "Oops!", "Select a customer first.")
        return sel[0] if sel else None

    def edit(self):
        r = self._one()
        if r:
            CustomerDialog(self, r, self.DisplayData)

    def history(self):
        r = self._one()
        if r:
            CustomerHistory(self, r)


class CustomerDialog(ui.Dialog):
    def __init__(self, parent, customer, on_saved):
        super().__init__(parent, "Edit customer" if customer else "Register customer", width=600)
        self.on_saved = on_saved
        f = ttk.Frame(self.body, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        self.name = g.add("Name", ttk.Entry)
        self.phone = g.add("Phone", ttk.Entry)
        self.email = g.add("Email (optional)", ttk.Entry)
        self.gstin = g.add("GSTIN (optional)", ttk.Entry)
        self.state_box = g.add("State", ttk.Combobox, values=gst_states.labels(), state="readonly")
        self.address = g.add("Address (optional)", ttk.Entry)
        if customer:
            for w, k in [(self.name, "name"), (self.phone, "phone"), (self.email, "email"),
                         (self.gstin, "gstin"), (self.address, "address")]:
                ui.set_entry(w, customer.get(k) or "")
            self.phone.configure(state="readonly")  # phone identifies the customer
            self.state_box.set(gst_states.label(customer.get("state_code") or ""))
        ttk.Button(self.buttons, text="Save", bootstyle="success", command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="right", padx=8)
        self.present()

    def save(self):
        try:
            with db.connect() as conn:
                people.save_customer(conn, {"name": self.name.get(), "phone": self.phone.get(),
                                            "email": self.email.get(), "gstin": self.gstin.get(),
                                            "address": self.address.get(),
                                            "state_code": gst_states.code_from_label(self.state_box.get())})
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        self.destroy()
        self.on_saved()


class CustomerHistory(ui.Dialog):
    def __init__(self, parent, customer):
        super().__init__(parent, "Purchase history - %s" % customer["name"], width=760, height=520)
        with db.connect() as conn:
            rows = people.customer_history(conn, customer["customer_id"])
        for r in rows:
            r["grand_total"] = billing.money(r["grand_total"]) if r["grand_total"] else ""
            r["status"] = r["status"] or "ACTIVE"
        t = ui.DataTable(self.body, [("bill_no", "Invoice", 150, "w"), ("date", "Date", 110, "w"),
                                     ("grand_total", "Total", 110, "e"), ("payment_mode", "Payment", 100, "w"),
                                     ("status", "Status", 100, "w")], height=10)
        t.pack(fill="both", expand=True)
        t.set_rows(rows, iid_key="bill_no", tag_fn=lambda r: ["cancelled"] if r["status"] == "CANCELLED" else [])
        t.on_double_click(lambda r: open_bill(self, r["bill_no"]))
        ttk.Label(self.body, text="%d invoice(s). Double-click to view." % len(rows),
                  style="CardMuted.TLabel").pack(anchor="w", pady=(6, 0))
        ttk.Button(self.buttons, text="Close", bootstyle="secondary-outline", command=self.destroy).pack(side="right")
        self.present()


# ---------------------------------------------------------------- suppliers
class Suppliers(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        self.query, _ = search_box(bar, self.DisplayData)
        ttk.Button(bar, text="Delete supplier", bootstyle="danger", command=self.delete).pack(side="right")
        ttk.Button(bar, text="Edit supplier", bootstyle="primary-outline", command=self.edit).pack(side="right", padx=6)
        ttk.Button(bar, text="Add supplier", bootstyle="success",
                   command=lambda: SupplierDialog(self, None, self.DisplayData)).pack(side="right")
        cols = [("name", "Supplier", 220, "w"), ("phone", "Phone", 120, "w"), ("email", "Email", 200, "w"),
                ("gstin", "GSTIN", 150, "w"), ("address", "Address", 220, "w"), ("products", "Products", 80, "e")]
        self.tree = ui.DataTable(c, cols, height=16)
        self.tree.pack(fill="both", expand=True)
        self.tree.on_double_click(lambda r: self.edit())
        self.DisplayData()

    def DisplayData(self):
        with db.connect() as conn:
            self.tree.set_rows(people.list_suppliers(conn, self.query.get()), iid_key="supplier_id")

    def _one(self):
        sel = self.tree.selected()
        if not sel:
            ui.error(self, "Oops!", "Select a supplier first.")
        return sel[0] if sel else None

    def edit(self):
        r = self._one()
        if r:
            SupplierDialog(self, r, self.DisplayData)

    def delete(self):
        r = self._one()
        if r and ui.confirm(self, "Confirm", "Delete supplier %s?\n%d product(s) will be unlinked "
                            "(products are not deleted)." % (r["name"], r["products"])):
            with db.connect() as conn:
                people.delete_supplier(conn, r["supplier_id"])
            self.DisplayData()


class SupplierDialog(ui.Dialog):
    def __init__(self, parent, supplier, on_saved):
        super().__init__(parent, "Edit supplier" if supplier else "Add supplier", width=600)
        self.supplier, self.on_saved = supplier, on_saved
        f = ttk.Frame(self.body, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        self.fields = {k: g.add(label, ttk.Entry, span=2 if k == "address" else 1)
                       for k, label in [("name", "Supplier name"), ("phone", "Phone"), ("email", "Email"),
                                        ("gstin", "GSTIN"), ("address", "Address")]}
        if supplier:
            for k, w in self.fields.items():
                ui.set_entry(w, supplier.get(k) or "")
        ttk.Button(self.buttons, text="Save", bootstyle="success", command=self.save).pack(side="right")
        ttk.Button(self.buttons, text="Cancel", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="right", padx=8)
        self.present()

    def save(self):
        try:
            with db.connect() as conn:
                people.save_supplier(conn, {k: w.get() for k, w in self.fields.items()},
                                     self.supplier["supplier_id"] if self.supplier else None)
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        self.destroy()
        self.on_saved()


# ---------------------------------------------------------------- analytics
class Analytics(ttk.Frame):
    """Original 'Best seller of Day / Month / Year' charts, now drawn inside
    the window (2-D, theme colours) plus sales trends."""

    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        self.button1 = ttk.Button(bar, text="Best seller of Day", bootstyle="primary",
                                  command=self.plot_best_seller_of_day)
        self.button2 = ttk.Button(bar, text="Best seller of Month", bootstyle="primary",
                                  command=self.plot_best_seller_of_month)
        self.button3 = ttk.Button(bar, text="Best seller of Year", bootstyle="primary",
                                  command=self.plot_best_seller_of_year)
        self.button4 = ttk.Button(bar, text="Sales - last 30 days", bootstyle="success",
                                  command=self.plot_daily_sales)
        self.button5 = ttk.Button(bar, text="Monthly sales", bootstyle="success",
                                  command=self.plot_monthly_sales)
        for b in (self.button1, self.button2, self.button3, self.button4, self.button5):
            b.pack(side="left", padx=(0, 8))
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=(9, 4.6), dpi=100, facecolor=C["white"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=c)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.plot_best_seller_of_month()

    def _axes(self, title):
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(C["white"])
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(C["muted"])
        ax.tick_params(colors=C["text"], labelsize=9)
        ax.set_title(title, color=C["navy"], fontsize=13, loc="left", fontweight="bold")
        return ax

    def _empty(self, ax, text):
        ax.text(0.5, 0.5, text, ha="center", va="center", color=C["muted"], transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])

    def _best(self, start, title):
        with db.connect() as conn:
            df = reports.best_sellers(conn, start, date.today().isoformat(), top=5)
        ax = self._axes(title)
        if df.empty:
            self._empty(ax, "No sales in this period yet.")
        else:
            names = [n if len(n) <= 22 else n[:21] + "…" for n in df["Product"]][::-1]
            bars = ax.barh(names, list(df["Qty sold"])[::-1], color=C["blue"])
            bars[-1].set_color(C["green"])
            ax.set_xlabel("Quantity sold", color=C["muted"])
            from matplotlib.ticker import MaxNLocator
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            for b in bars:
                ax.text(b.get_width(), b.get_y() + b.get_height() / 2, " %d" % b.get_width(),
                        va="center", color=C["text"], fontsize=9)
        self.fig.tight_layout()
        self.canvas.draw()

    def plot_best_seller_of_day(self):
        self._best(date.today().isoformat(), "Top 5 best-selling items - today")

    def plot_best_seller_of_month(self):
        self._best(date.today().replace(day=1).isoformat(), "Top 5 best-selling items - this month")

    def plot_best_seller_of_year(self):
        self._best(date.today().replace(month=1, day=1).isoformat(), "Top 5 best-selling items - this year")

    def plot_daily_sales(self):
        end = date.today()
        start = end - timedelta(days=29)
        with db.connect() as conn:
            df = reports.sales_by_day(conn, start.isoformat(), end.isoformat())
        by_day = dict(zip(df["Date"], df["Sales"])) if not df.empty else {}
        days = [(start + timedelta(days=i)).isoformat() for i in range(30)]
        vals = [float(by_day.get(d, 0)) for d in days]
        ax = self._axes("Sales - last 30 days (Rs.)")
        if not any(vals):
            self._empty(ax, "No sales in the last 30 days.")
        else:
            ax.bar(range(30), vals, color=C["blue"])
            ax.set_xticks(range(0, 30, 5))
            ax.set_xticklabels([days[i][5:] for i in range(0, 30, 5)])
        self.fig.tight_layout()
        self.canvas.draw()

    def plot_monthly_sales(self):
        year = date.today().year
        with db.connect() as conn:
            df = reports.sales_by_month(conn, year)
        vals = [float(v) for v in df["Sales"]]
        ax = self._axes("Monthly sales %d (Rs.)" % year)
        if not any(vals):
            self._empty(ax, "No sales this year yet.")
        else:
            ax.bar([m[5:] for m in df["Month"]], vals, color=C["green"])
        self.fig.tight_layout()
        self.canvas.draw()


# ---------------------------------------------------------------- reports
class Reports(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self)
        c.pack(fill="both", expand=True)
        bar = toolbar(c)
        ttk.Label(bar, text="Report", style="Card.TLabel").pack(side="left")
        self.kind = ttk.Combobox(bar, values=list(reports.REPORTS), state="readonly", width=22)
        self.kind.set("Daily sales")
        self.kind.pack(side="left", padx=(6, 14))
        m_start, m_end = reports.month_range()
        ttk.Label(bar, text="From", style="Card.TLabel").pack(side="left")
        self.d_from = ttk.Entry(bar, width=11)
        self.d_from.insert(0, m_start)
        self.d_from.pack(side="left", padx=(4, 8))
        ttk.Label(bar, text="To", style="Card.TLabel").pack(side="left")
        self.d_to = ttk.Entry(bar, width=11)
        self.d_to.insert(0, date.today().isoformat())
        self.d_to.pack(side="left", padx=(4, 8))
        ttk.Button(bar, text="Show", bootstyle="primary", command=self.show).pack(side="left")
        ttk.Button(bar, text="Export all (Excel)", bootstyle="success-outline",
                   command=self.export_all).pack(side="right")
        ttk.Button(bar, text="Export PDF", bootstyle="primary-outline", command=self.export_pdf).pack(side="right", padx=6)
        ttk.Button(bar, text="Export Excel", bootstyle="primary-outline", command=self.export_xlsx).pack(side="right")
        self.kind.bind("<<ComboboxSelected>>", lambda e: self.show())
        self.summary = ttk.Label(c, text="", style="CardField.TLabel")
        self.summary.pack(anchor="w", pady=(0, 6))
        self.holder = ttk.Frame(c, style="Card.TFrame")
        self.holder.pack(fill="both", expand=True)
        self.df = None
        self.show()

    def _range(self):
        start = parse_date(self.d_from.get(), "From") or "0000-01-01"
        end = parse_date(self.d_to.get(), "To") or date.today().isoformat()
        if start > end:
            raise BillingError("'From' date is after 'To' date.")
        return start, end

    def show(self):
        try:
            start, end = self._range()
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        name = self.kind.get()
        with db.connect() as conn:
            self.df = reports.REPORTS[name](conn, start, end)
            prof = reports.profit_summary(conn, start, end)
        for w in self.holder.winfo_children():
            w.destroy()
        cols = [(str(i), col, 150 if i == 1 else 110, "w" if self.df[col].dtype == object and i < 2 else "e")
                for i, col in enumerate(self.df.columns)]
        t = ui.DataTable(self.holder, cols, height=16)
        t.pack(fill="both", expand=True)
        t.set_rows([{str(i): v for i, v in enumerate(row)} for row in self.df.itertuples(index=False)])
        text = "%s: %d row(s)." % (name, len(self.df))
        if name in ("Daily sales", "Profit by product", "GST summary"):
            text += "   Revenue (ex GST) Rs. %s   |   Cost Rs. %s   |   Gross profit Rs. %s" % (
                fmt(prof["revenue"]), fmt(prof["cost"]), fmt(prof["gross_profit"]))
        self.summary.configure(text=text)

    def _path(self, ext):
        import os
        safe = self.kind.get().lower().replace(" ", "_").replace("-", "_")
        return os.path.join(reports.export_dir(), "%s_%s.%s" % (safe, datetime.now().strftime("%Y%m%d_%H%M%S"), ext))

    def export_xlsx(self):
        if self.df is None:
            return
        path = reports.export_excel({self.kind.get(): self.df}, self._path("xlsx"))
        ui.info(self, "Exported", "Saved to:\n%s" % path)

    def export_pdf(self):
        if self.df is None:
            return
        start, end = self._range()
        path = reports.export_pdf(self.kind.get(), self.df, self._path("pdf"), "(%s to %s)" % (start, end))
        ui.open_file(path)

    def export_all(self):
        try:
            start, end = self._range()
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        import os
        path = os.path.join(reports.export_dir(), "billwise_reports_%s_to_%s.xlsx" % (start, end))
        with db.connect() as conn:
            sheets = {n: fn(conn, start, end) for n, fn in reports.REPORTS.items()}
        reports.export_excel(sheets, path)
        ui.info(self, "Exported", "All reports saved to:\n%s" % path)


# ---------------------------------------------------------------- settings
class Settings(ttk.Frame):
    KEYS = [("store_name", "Store name"), ("store_phone", "Store phone"), ("store_gstin", "Store GSTIN"),
            ("low_stock_threshold", "Default low-stock level"), ("store_address", "Store address")]

    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        sc = ui.card(self, "Store details", "printed on every invoice")
        sc.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        f = ttk.Frame(sc, style="Card.TFrame")
        f.pack(fill="x")
        g = ui.FormGrid(f, 2)
        with db.connect() as conn:
            vals = {k: db.get_setting(conn, k) for k, _ in self.KEYS + [("store_state_code", "")]}
        self.fields = {}
        for k, label in self.KEYS:
            self.fields[k] = g.add(label, ttk.Entry, span=2 if k == "store_address" else 1)
            ui.set_entry(self.fields[k], vals[k])
        self.state_box = g.add("Store state (decides CGST+SGST or IGST)", ttk.Combobox,
                           values=gst_states.labels(), state="readonly", span=2)
        self.state_box.set(gst_states.label(vals["store_state_code"]))
        ttk.Button(sc, text="Save settings", bootstyle="success", command=self.save).pack(anchor="e", pady=(10, 0))

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        pc = ui.card(right, "Change my password")
        pc.pack(fill="x")
        pf = ttk.Frame(pc, style="Card.TFrame")
        pf.pack(fill="x")
        g2 = ui.FormGrid(pf, 1)
        self.old = g2.add("Current password", ttk.Entry, show="•")
        self.new1 = g2.add("New password", ttk.Entry, show="•")
        self.new2 = g2.add("Confirm new password", ttk.Entry, show="•")
        ttk.Button(pc, text="Change password", bootstyle="primary", command=self.change_password).pack(anchor="e", pady=(8, 0))
        bc = ui.card(right, "Backup")
        bc.pack(fill="x", pady=(12, 0))
        ttk.Label(bc, text="Copies the database to the backups folder (a backup is also taken "
                  "automatically before any schema upgrade).", style="CardMuted.TLabel",
                  wraplength=360).pack(anchor="w")
        ttk.Button(bc, text="Back up database now", bootstyle="primary-outline",
                   command=self.backup).pack(anchor="e", pady=(8, 0))
        dc = ui.card(right, "Demo catalogue")
        dc.pack(fill="x", pady=(12, 0))
        ttk.Label(dc, text="%d everyday products (staples, dairy, snacks, beverages, personal and "
                  "home care...) marked DEMO, with DEMO- SKUs. Prices are placeholders, not market "
                  "prices; GST rates must be verified. No barcodes." % len(demo_catalogue.CATALOGUE),
                  style="CardMuted.TLabel", wraplength=360).pack(anchor="w")
        self.demo_status = ttk.Label(dc, text="", style="Amber.TLabel")
        self.demo_status.pack(anchor="w", pady=(6, 0))
        row = ttk.Frame(dc, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Remove demo products", bootstyle="danger-outline",
                   command=self.remove_demo).pack(side="right")
        ttk.Button(row, text="Load demo catalogue", bootstyle="success-outline",
                   command=self.load_demo).pack(side="right", padx=8)
        self.refresh_demo()

    def refresh_demo(self):
        with db.connect() as conn:
            n = demo_catalogue.demo_count(conn)
        self.demo_status.configure(text="%d demo products currently loaded." % n if n else
                                   "No demo products loaded.")

    def load_demo(self):
        if not ui.confirm(self, "Load demo catalogue", "Add %d DEMO products with placeholder prices "
                          "and %d units of opening stock each?" % (len(demo_catalogue.CATALOGUE),
                                                                   demo_catalogue.DEMO_STOCK)):
            return
        with db.connect() as conn:
            n = demo_catalogue.load(conn, current_user["emp_id"])
        self.refresh_demo()
        ui.info(self, "Demo catalogue", "%d demo products added." % n)

    def remove_demo(self):
        if not ui.confirm(self, "Remove demo products", "Delete all products marked DEMO?\n"
                          "Invoices are not changed: any bill that sold a demo product keeps its lines."):
            return
        with db.connect() as conn:
            n = demo_catalogue.remove(conn)
        self.refresh_demo()
        ui.info(self, "Demo catalogue", "%d demo products removed." % n)

    def save(self):
        vals = {k: w.get().strip() for k, w in self.fields.items()}
        vals["store_state_code"] = gst_states.code_from_label(self.state_box.get())
        vals["store_gstin"] = vals["store_gstin"].upper()
        if not vals["store_state_code"]:
            ui.error(self, "Oops!", "Choose the store's state.")
            return
        if vals["store_gstin"] and not security.valid_gstin(vals["store_gstin"]):
            ui.error(self, "Oops!", "Invalid GSTIN.")
            return
        if not vals["low_stock_threshold"].isdigit():
            ui.error(self, "Oops!", "Default low-stock level must be a whole number.")
            return
        if vals["store_phone"] and not security.valid_phone(vals["store_phone"]):
            ui.error(self, "Oops!", "Invalid store phone number.")
            return
        with db.connect() as conn:
            db.set_settings(conn, vals)
        ui.info(self, "Saved", "Settings saved. New bills use them immediately; existing invoices are unchanged.")

    def change_password(self):
        if self.new1.get() != self.new2.get():
            ui.error(self, "Oops!", "New passwords do not match.")
            return
        err = security.validate_new_password(self.new1.get())
        if err:
            ui.error(self, "Oops!", err)
            return
        try:
            with db.connect() as conn:
                people.change_password(conn, current_user["emp_id"], self.old.get(), self.new1.get())
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        for w in (self.old, self.new1, self.new2):
            ui.set_entry(w, "")
        ui.info(self, "Saved", "Password changed.")

    def backup(self):
        path = db.backup_database(reason="manual")
        ui.info(self, "Backup", "Backup saved to:\n%s" % path if path else "No database file found.")


# ---------------------------------------------------------------- start
def main():
    global root, page1
    ui.setup_logging()
    root = ui.create_root("Billwise - Administration", maximize=True)
    if not ui.init_database(root):
        root.destroy()
        return
    root.protocol("WM_DELETE_WINDOW", exitt)
    page1 = login_page(root)
    page1.pack(fill="both", expand=True)
    with db.connect() as conn:
        first_run = people.employee_count(conn) == 0
    if first_run:
        root.after(200, lambda: FirstRunSetup(root, lambda: page1.entry1.focus_set()))
    root.mainloop()


if __name__ == "__main__":
    main()
