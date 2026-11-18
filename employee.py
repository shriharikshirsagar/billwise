"""Billwise billing counter (employee app).

Keeps the original structure - login_page -> bill_window with Add to cart,
Remove, Clear, Generate, Search and Logout/Exit - rebuilt on the Billwise theme
and on the tested billing services (Decimal GST maths, one transaction per
invoice, sequential invoice numbers, stock validation).
"""
import logging
import tkinter as tk
from tkinter import simpledialog

import ttkbootstrap as ttk

import billing
import db
import gst_states
import inventory
import invoices
import people
import theme
import ui
from billing import BillingError, Cart, fmt

C = theme.COLORS
log = logging.getLogger("billwise.employee")

root = None
page1 = None
shell = None
username = None   # dict for the signed-in employee


def valid_phone(phn):
    from security import valid_phone as _vp
    return _vp(phn)


# ---------------------------------------------------------------- login / logout
def login(emp_id, password):
    global username
    with db.connect() as conn:
        user = people.authenticate(conn, emp_id, password)
    if not user:
        return "Incorrect employee ID or password."
    username = user
    log.info("Employee %s signed in", user["emp_id"])
    page1.pack_forget()
    open_billing()
    return None


def open_billing():
    global shell
    who = "%s  (%s)" % (username["name"], username["emp_id"])
    pages = {"billing": ("New invoice", lambda p: bill_window(p, username)),
             "find": ("Find invoice", lambda p: find_invoice_page(p))}
    nav = [(None, "Invoicing"),
           ("billing", "New invoice", "billing", lambda: navigate("billing")),
           ("find", "Find invoice", "search", lambda: navigate("find"))]
    bottom = [("logout", "Sign out", "logout", logout), ("exit", "Exit Billwise", "exit", exitt)]
    shell = ui.Shell(root, pages, nav, bottom, user_text=who, subtitle="Invoicing desk",
                     user=(username["name"], "%s  ·  %s" % (username["designation"], username["emp_id"])))
    shell.pack(fill="both", expand=True)
    shell.show("billing")


def navigate(key):
    page = shell.page
    if isinstance(page, bill_window) and page.has_unsaved_cart() and key != "billing":
        if not ui.confirm(root, "Leave invoice", "The current invoice has not been issued. Discard it?"):
            return
    shell.show(key)


def logout():
    global shell, username
    page = shell.page if shell else None
    msg = "Are you sure you want to logout?"
    if isinstance(page, bill_window) and page.has_unsaved_cart():
        msg = "The current cart has not been billed and will be discarded.\n" + msg
    if ui.confirm(root, "Logout", msg):
        shell.destroy()
        shell = None
        username = None
        page1.pack(fill="both", expand=True)
        page1.entry1.focus_set()


def exitt():
    if ui.confirm(root, "Exit", "Are you sure you want to exit?"):
        root.destroy()


class login_page(ui.LoginView):
    def __init__(self, top):
        super().__init__(top, "Invoicing desk", "Sign in with your employee ID to raise invoices.", login)


# ---------------------------------------------------------------- billing page
class bill_window(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.cart = Cart()
        self.state = 1            # 1 = editing, 0 = invoice generated (locked)
        self.last_bill = None
        self.product_rows = []
        with db.connect() as conn:
            self.store_state = db.get_setting(conn, "store_state_code")
            cats = inventory.categories(conn)

        self.columnconfigure(0, weight=0, minsize=360)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")

        # --- product picker
        pc = ui.card(left, "Add item")
        pc.pack(fill="x")
        form = ttk.Frame(pc, style="Card.TFrame")
        form.pack(fill="x")
        g = ui.FormGrid(form, 2)
        # quick search sits in the card header: type a name, brand or SKU and press Enter
        self.find_var = tk.StringVar()
        self.entry_find = ttk.Entry(pc.head, textvariable=self.find_var, width=22)
        self.entry_find.pack(side="right", ipady=1)
        ttk.Label(pc.head, text=theme.icon("search"), style="CardMuted.TLabel",
                  font=(theme.FONTS.get("icon_family") or "Segoe UI", 10)).pack(side="right", padx=(0, 6))
        self.entry_find.bind("<Return>", self.quick_search)
        self.combo1 = g.add("Category", ttk.Combobox, values=cats, state="readonly")
        self.combo2 = g.add("Sub-category", ttk.Combobox, state="disabled")
        self.combo3 = g.add("Product", ttk.Combobox, span=2, state="disabled")
        self.entry4 = g.add("Quantity", ttk.Entry)
        self.entry_disc = g.add("Discount %", ttk.Entry)
        self.entry4.insert(0, "1")
        self.entry_disc.insert(0, "0")
        self.qty_label = ttk.Label(pc, text="Search above (name, brand or SKU + Enter) or browse.",
                                   style="CardMuted.TLabel", wraplength=340)
        self.qty_label.pack(anchor="w", pady=(6, 6))
        row = ttk.Frame(pc, style="Card.TFrame")
        row.pack(fill="x")
        self.button7 = ttk.Button(row, text="Add line", bootstyle="primary", command=self.add_to_cart)
        self.button7.pack(side="left", fill="x", expand=True)
        self.button8 = ttk.Button(row, text="Clear", bootstyle="secondary-outline",
                                  command=self.clear_selection)
        self.button8.pack(side="left", padx=(8, 0))
        self.combo1.bind("<<ComboboxSelected>>", self.get_category)
        self.combo2.bind("<<ComboboxSelected>>", self.get_subcat)
        self.combo3.bind("<<ComboboxSelected>>", self.show_qty)
        self.entry4.bind("<Return>", lambda e: self.add_to_cart())
        if not cats:
            self.qty_label.configure(text="No products yet. Ask the administrator to add stock.",
                                     style="Amber.TLabel")

        # --- customer
        cc = ui.card(left, "Customer")
        cc.pack(fill="x", pady=(12, 0))
        cf = ttk.Frame(cc, style="Card.TFrame")
        cf.pack(fill="x")
        g2 = ui.FormGrid(cf, 2)
        self.cust_name = tk.StringVar()
        self.cust_num = tk.StringVar()
        self.cust_gstin = tk.StringVar()
        self.entry1 = g2.add("Name", ttk.Entry, textvariable=self.cust_name)
        self.entry2 = g2.add("Phone", ttk.Entry, textvariable=self.cust_num)
        self.entry_gstin = g2.add("GSTIN (optional)", ttk.Entry, textvariable=self.cust_gstin)
        self.pos = g2.add("Place of supply", ttk.Combobox, values=gst_states.labels(),
                          state="readonly")
        if self.store_state:
            self.pos.set(gst_states.label(self.store_state))
        self.save_cust = tk.BooleanVar(value=False)
        self.save_check = ui.on_card(ttk.Checkbutton(cc, text="Register / update this customer",
                                                     variable=self.save_cust,
                                                     bootstyle="success-round-toggle"))
        self.save_check.pack(anchor="w", pady=(6, 0))
        self.cust_msg = ttk.Label(cc.head, text="", style="Green.TLabel")
        self.cust_msg.pack(side="right")
        self.entry2.bind("<FocusOut>", self.lookup_customer)
        self.pos.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        # --- cart
        btns = ttk.Frame(right)
        btns.pack(side="bottom", fill="x", pady=(10, 0))
        bottom = ttk.Frame(right)
        bottom.pack(side="bottom", fill="x", pady=(12, 0))
        cart_card = ui.card(right, "Line items")
        cart_card.pack(fill="both", expand=True)
        cols = [("n", "#", 32, "center"), ("name", "Product", 170, "w"), ("qty", "Qty", 44, "e"),
                ("rate", "MRP", 70, "e"), ("disc", "Disc%", 50, "e"),
                ("taxable", "Taxable", 78, "e"), ("gst", "GST%", 50, "e"),
                ("tax", "GST", 68, "e"), ("amount", "Amount", 84, "e")]
        actions = ttk.Frame(cart_card, style="Card.TFrame")
        actions.pack(side="bottom", fill="x", pady=(8, 0))
        self.table = ui.DataTable(cart_card, cols, height=4)
        self.table.pack(fill="both", expand=True)
        self.button9 = ttk.Button(actions, text="Remove line", bootstyle="danger-outline",
                                  command=self.remove_product)
        self.button9.pack(side="left")
        self.button_qty = ttk.Button(actions, text="Change quantity", bootstyle="primary-outline",
                                     command=self.change_qty)
        self.button_qty.pack(side="left", padx=8)
        self.supply_label = ttk.Label(actions, text="", style="CardMuted.TLabel")
        self.supply_label.pack(side="right")
        self.table.on_double_click(lambda r: self.change_qty())

        # --- payment + totals
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        pay = ui.card(bottom, "Payment")
        pay.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.pay_mode = tk.StringVar(value="Cash")
        modes = ttk.Frame(pay, style="Card.TFrame")
        modes.pack(fill="x")
        self.mode_buttons = []
        for m in billing.PAYMENT_MODES:
            b = ttk.Radiobutton(modes, text=m, value=m, variable=self.pay_mode,
                                bootstyle="primary-toolbutton", command=self.on_mode)
            b.pack(side="left", padx=(0, 6), ipadx=12)
            self.mode_buttons.append(b)
        pf = ttk.Frame(pay, style="Card.TFrame")
        pf.pack(fill="x", pady=(10, 0))
        g3 = ui.FormGrid(pf, 2)
        self.tendered = tk.StringVar()
        self.reference = tk.StringVar()
        self.entry_cash = g3.add("Cash received", ttk.Entry, textvariable=self.tendered)
        self.entry_ref = g3.add("Reference", ttk.Entry, textvariable=self.reference, state="disabled")
        self.ref_label = self.entry_ref.master.winfo_children()[0]
        self.change_label = ttk.Label(pay, text="", style="Green.TLabel")
        self.change_label.pack(anchor="w", pady=(6, 0))
        self.tendered.trace_add("write", lambda *a: self.update_change())

        # navy "receipt" panel: the one dark surface on the counter, so the eye lands here
        tot = ttk.Frame(bottom, style="Receipt.TFrame", padding=(18, 14))
        tot.grid(row=0, column=1, sticky="nsew")
        ttk.Label(tot, text="INVOICE SUMMARY", style="ReceiptCaps.TLabel").pack(anchor="w")
        ui.tk_plain(tk.Frame, tot, bg=C["navy_line"], height=1).pack(fill="x", pady=(6, 8))
        grid = ttk.Frame(tot, style="Receipt.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.totals_vars = {}
        labels = [("subtotal", "Subtotal (MRP)"), ("discount", "Discount"),
                  ("taxable", "Taxable amount"), ("cgst", "CGST"), ("sgst", "SGST"),
                  ("igst", "IGST"), ("round_off", "Round off")]
        for r, (k, text) in enumerate(labels):
            ttk.Label(grid, text=text, style="Receipt.TLabel").grid(row=r, column=0, sticky="w")
            v = tk.StringVar(value="0.00")
            ttk.Label(grid, textvariable=v, style="ReceiptValue.TLabel").grid(row=r, column=1, sticky="e")
            self.totals_vars[k] = v
        ui.tk_plain(tk.Frame, tot, bg=C["green"], height=2).pack(fill="x", pady=(8, 6))
        trow = ttk.Frame(tot, style="Receipt.TFrame")
        trow.pack(fill="x")
        ttk.Label(trow, text="TOTAL PAYABLE", style="ReceiptCaps.TLabel").pack(side="left", anchor="s", pady=(0, 6))
        self.totals_vars["grand_total"] = tk.StringVar(value="Rs. 0.00")
        ttk.Label(trow, textvariable=self.totals_vars["grand_total"], style="ReceiptTotal.TLabel").pack(side="right")

        self.button4 = ttk.Button(btns, text="Issue invoice", bootstyle="success",
                                  command=self.gen_bill)
        self.button4.pack(side="right", ipadx=18, ipady=4)
        self.button_pdf = ttk.Button(btns, text="Open / Print PDF", bootstyle="primary-outline",
                                     command=self.open_pdf, state="disabled")
        self.button_pdf.pack(side="right", padx=8)
        self.button5 = ttk.Button(btns, text="New invoice", bootstyle="secondary-outline",
                                  command=self.clear_bill)
        self.button5.pack(side="right")
        self.status = ttk.Label(btns, text="", style="PageSub.TLabel")
        self.status.pack(side="left")
        if not self.store_state:
            self.status.configure(text="Store state not set - ask the administrator (Settings).",
                                  foreground=C["amber"])
        self.refresh()

    # ---- product selection (original method names kept)
    def get_category(self, event=None):
        with db.connect() as conn:
            subs = inventory.subcategories(conn, self.combo1.get())
        self.combo2.configure(values=subs, state="readonly")
        self.combo2.set("")
        self.combo3.set("")
        self.combo3.configure(state="disabled", values=[])
        self.qty_label.configure(text="Choose a sub-category.", style="CardMuted.TLabel")

    def get_subcat(self, event=None):
        with db.connect() as conn:
            self.product_rows = inventory.products_in(conn, self.combo1.get(), self.combo2.get())
        names = [p["product_name"] for p in self.product_rows]
        dup = {n for n in names if names.count(n) > 1}
        self.combo3.configure(values=["%s  (#%d)" % (p["product_name"], p["product_id"])
                                      if p["product_name"] in dup else p["product_name"]
                                      for p in self.product_rows], state="readonly")
        self.combo3.set("")
        self.qty_label.configure(text="Choose a product.", style="CardMuted.TLabel")

    def quick_search(self, event=None):
        """Fill the product list straight from a name / brand / SKU search."""
        with db.connect() as conn:
            self.product_rows = inventory.search_products(conn, self.find_var.get())
        if not self.product_rows:
            self.combo3.configure(values=[], state="disabled")
            self.combo3.set("")
            self.qty_label.configure(text="No product matches '%s'." % self.find_var.get().strip(),
                                     style="Error.TLabel")
            return
        self.combo1.set("")
        self.combo2.set("")
        self.combo2.configure(state="disabled")
        self.combo3.configure(values=[p["product_name"] for p in self.product_rows], state="readonly")
        self.combo3.current(0)
        self.show_qty()
        self.entry4.focus_set()
        self.entry4.select_range(0, "end")

    def selected_product(self):
        i = self.combo3.current()
        if i < 0 or i >= len(self.product_rows):
            return None
        with db.connect() as conn:  # always fresh stock / price
            return inventory.get_product(conn, self.product_rows[i]["product_id"])

    def show_qty(self, event=None):
        p = self.selected_product()
        if p is None:
            return
        in_cart = self.cart.find(p["product_id"])
        avail = p["stock"] - (in_cart.qty if in_cart else 0)
        rate = "%s%%" % p["gst_rate"] if p["gst_rate"] not in (None, "") else "NOT SET"
        text = "MRP Rs. %s   |   GST %s   |   In stock: %d" % (fmt(p["mrp"]), rate, p["stock"])
        if in_cart:
            text += "  (%d on this invoice)" % in_cart.qty
        style = "CardMuted.TLabel"
        if avail <= 0:
            text += "   -  OUT OF STOCK"
            style = "Error.TLabel"
        elif p["is_low"]:
            text += "   -  LOW STOCK"
            style = "Amber.TLabel"
        self.qty_label.configure(text=text, style=style)

    def clear_selection(self):
        self.find_var.set("")
        self.combo1.set("")
        self.combo2.set("")
        self.combo3.set("")
        self.combo2.configure(state="disabled", values=[])
        self.combo3.configure(state="disabled", values=[])
        ui.set_entry(self.entry4, "1")
        ui.set_entry(self.entry_disc, "0")
        self.qty_label.configure(text="Choose a product.", style="CardMuted.TLabel")

    # ---- cart
    def _locked(self):
        if self.state == 0:
            ui.info(self, "Bill generated", "Invoice %s is saved. Click 'New bill' to start "
                    "another bill." % self.last_bill)
            return True
        return False

    def add_to_cart(self):
        if self._locked():
            return
        p = self.selected_product()
        if p is None:
            ui.error(self, "Oops!", "Choose a product.")
            return
        try:
            self.cart.add(p["product_id"], p["product_name"], p["mrp"], p["gst_rate"],
                          self.entry4.get(), p["stock"], self.entry_disc.get(), p["hsn_code"],
                          p["cost_price"])
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
            return
        ui.set_entry(self.entry4, "1")
        self.refresh()
        self.show_qty()

    def remove_product(self):
        if self._locked():
            return
        if self.cart.is_empty():
            ui.error(self, "Oops!", "Add at least one line item.")
            return
        sel = self.table.selected()
        pid = sel[0]["product_id"] if sel else self.cart.lines[-1].product_id  # original: last item
        self.cart.remove(pid)
        self.refresh()
        self.show_qty()

    def change_qty(self):
        if self._locked():
            return
        sel = self.table.selected()
        if not sel:
            ui.error(self, "Oops!", "Select a line item first.")
            return
        line = self.cart.find(sel[0]["product_id"])
        qty = simpledialog.askinteger("Change quantity", "New quantity for %s:" % line.name,
                                      parent=self, initialvalue=line.qty, minvalue=1)
        if qty is None:
            return
        with db.connect() as conn:
            p = inventory.get_product(conn, line.product_id)
        try:
            self.cart.set_qty(line.product_id, qty, p["stock"] if p else 0)
        except BillingError as e:
            ui.error(self, "Oops!", str(e))
        self.refresh()

    def supply_type(self):
        pos = gst_states.code_from_label(self.pos.get())
        if not self.store_state or not pos:
            return billing.INTRA, False
        return billing.supply_type_for(self.store_state, pos), True

    def refresh(self):
        """Redraw the cart and the live totals (same engine as the saved invoice)."""
        supply, known = self.supply_type()
        if self.cart.is_empty():
            self.table.set_rows([])
            for k in self.totals_vars:
                self.totals_vars[k].set("0.00")
            self.totals_vars["grand_total"].set("Rs. 0.00")
            self.supply_label.configure(text="")
            self.update_change()
            return
        t = self.cart.totals(supply)
        rows = [{"product_id": ln.product_id, "n": ln.line_no, "name": ln.name, "qty": ln.qty,
                 "rate": ln.unit_price, "disc": str(ln.discount_pct), "taxable": ln.taxable,
                 "gst": "%s%%" % ln.gst_rate, "tax": ln.tax, "amount": ln.line_total}
                for ln in t.lines]
        self.table.set_rows(rows, iid_key="product_id")
        self.show_totals(t.subtotal, t.discount, t.taxable, t.cgst, t.sgst, t.igst, t.round_off,
                         t.grand_total)
        self.supply_label.configure(
            text=("Intra-state: CGST + SGST" if supply == billing.INTRA else "Inter-state: IGST")
            + ("" if known else "  (choose place of supply)"))
        self.update_change()

    def show_totals(self, subtotal, discount, taxable, cgst, sgst, igst, round_off, grand):
        v = self.totals_vars
        v["subtotal"].set(fmt(subtotal))
        v["discount"].set(("-" + fmt(discount)) if discount else fmt(discount))
        v["taxable"].set(fmt(taxable))
        v["cgst"].set(fmt(cgst))
        v["sgst"].set(fmt(sgst))
        v["igst"].set(fmt(igst))
        v["round_off"].set(fmt(round_off))
        v["grand_total"].set("Rs. " + fmt(grand))

    total_bill = refresh  # original "Total" action: totals are now always live

    # ---- payment
    def on_mode(self):
        mode = self.pay_mode.get()
        if mode == "Cash":
            self.entry_cash.configure(state="normal")
            self.reference.set("")
            self.entry_ref.configure(state="disabled")
            self.ref_label.configure(text="Reference")
        else:
            self.tendered.set("")
            self.entry_cash.configure(state="disabled")
            self.entry_ref.configure(state="normal")
            self.ref_label.configure(text="UPI reference (optional)" if mode == "UPI"
                                     else "Card last 4 digits (optional)")
        self.update_change()

    def update_change(self):
        if self.pay_mode.get() != "Cash" or not self.tendered.get().strip() or self.cart.is_empty():
            self.change_label.configure(text="")
            return
        try:
            grand = self.cart.totals(self.supply_type()[0]).grand_total
            paid = billing.money(self.tendered.get())
        except BillingError:
            self.change_label.configure(text="Enter a valid amount.", style="Error.TLabel")
            return
        if paid < grand:
            self.change_label.configure(text="Short by Rs. %s" % fmt(grand - paid), style="Error.TLabel")
        else:
            self.change_label.configure(text="Change to return: Rs. %s" % fmt(paid - grand),
                                        style="Green.TLabel")

    # ---- customer
    def lookup_customer(self, event=None):
        phone = self.cust_num.get().strip()
        if self.state == 0 or not valid_phone(phone):
            self.cust_msg.configure(text="")
            return
        with db.connect() as conn:
            c = people.find_customer_by_phone(conn, phone)
        if c:
            if not self.cust_name.get().strip():
                self.cust_name.set(c["name"])
            if not self.cust_gstin.get().strip() and c.get("gstin"):
                self.cust_gstin.set(c["gstin"])
            if c.get("state_code"):
                self.pos.set(gst_states.label(c["state_code"]))
                self.refresh()
            self.cust_msg.configure(text="Returning customer")
        else:
            self.cust_msg.configure(text="")

    # ---- generate / clear
    def gen_bill(self):
        if self._locked():
            return
        if not self.cust_name.get().strip():
            ui.error(self, "Oops!", "Please enter a name.")
            return
        if not self.cust_num.get().strip():
            ui.error(self, "Oops!", "Please enter a number.")
            return
        if not valid_phone(self.cust_num.get()):
            ui.error(self, "Oops!", "Please enter a valid 10-digit mobile number.")
            return
        if self.cart.is_empty():
            ui.error(self, "Oops!", "Add at least one line item.")
            return
        self.button4.configure(state="disabled")  # no double submission
        customer = {"name": self.cust_name.get(), "phone": self.cust_num.get(),
                    "gstin": self.cust_gstin.get(), "save": self.save_cust.get()}
        try:
            with db.connect() as conn:
                bill_no = invoices.create_invoice(
                    conn, self.cart.lines, customer, gst_states.code_from_label(self.pos.get()),
                    self.pay_mode.get(), self.tendered.get() or None, self.reference.get(),
                    user=self.user["emp_id"])
                inv = invoices.get_invoice(conn, bill_no)
                low = [p["product_name"] for p in inventory.low_stock(conn)
                       if p["product_id"] in self.cart.quantities()]
        except BillingError as e:
            self.button4.configure(state="normal")
            ui.error(self, "Cannot generate bill", str(e))
            return
        except Exception as e:  # noqa: BLE001 - nothing was saved (transaction rolled back)
            log.exception("Invoice creation failed")
            self.button4.configure(state="normal")
            ui.error(self, "Error", "The bill was NOT saved:\n%s" % e)
            return
        self.state = 0
        self.last_bill = bill_no
        # show exactly what was stored
        self.show_totals(inv["subtotal"], inv["discount_total"], inv["taxable_total"],
                         inv["cgst_total"], inv["sgst_total"], inv["igst_total"],
                         inv["round_off"], inv["grand_total"])
        for w in (self.entry1, self.entry2, self.entry_gstin, self.entry_cash, self.entry_ref):
            w.configure(state="disabled")
        self.pos.configure(state="disabled")
        for b in self.mode_buttons + [self.button7, self.button9, self.button_qty]:
            b.configure(state="disabled")
        self.button_pdf.configure(state="normal")
        self.status.configure(text="Invoice %s saved." % bill_no, foreground=C["green"])
        msg = "Invoice %s generated.\nTotal payable: Rs. %s" % (bill_no, fmt(inv["grand_total"]))
        if inv["payment_mode"] == "Cash":
            msg += "\nChange to return: Rs. %s" % fmt(inv["change_due"])
        if low:
            msg += "\n\nLow stock: " + ", ".join(low)
        ui.info(self, "Success!!", msg)
        self.open_pdf()

    def open_pdf(self):
        if self.last_bill:
            ui.print_invoice(self, self.last_bill)

    def has_unsaved_cart(self):
        return self.state == 1 and not self.cart.is_empty()

    def clear_bill(self):
        if self.has_unsaved_cart() and not ui.confirm(self, "New invoice", "Discard the current line items?"):
            return
        self.cart.clear()
        self.state = 1
        self.last_bill = None
        for w in (self.entry1, self.entry2, self.entry_gstin):
            w.configure(state="normal")
        for var in (self.cust_name, self.cust_num, self.cust_gstin, self.tendered, self.reference):
            var.set("")
        self.pos.configure(state="readonly")
        self.pos.set(gst_states.label(self.store_state) if self.store_state else "")
        self.save_cust.set(False)
        self.cust_msg.configure(text="")
        for b in self.mode_buttons + [self.button7, self.button9, self.button_qty, self.button4]:
            b.configure(state="normal")
        self.pay_mode.set("Cash")
        self.on_mode()
        self.button_pdf.configure(state="disabled")
        self.status.configure(text="")
        self.clear_selection()
        self.refresh()


# ---------------------------------------------------------------- find invoice
class find_invoice_page(ttk.Frame):
    """Original 'Search bill' feature: look up, preview and reprint invoices."""

    def __init__(self, parent):
        super().__init__(parent)
        c = ui.card(self, "Find invoice", "Search by invoice number, customer name or phone")
        c.pack(fill="both", expand=True)
        row = ttk.Frame(c, style="Card.TFrame")
        row.pack(fill="x", pady=(0, 10))
        self.cust_search_bill = tk.StringVar()
        self.entry3 = ttk.Entry(row, textvariable=self.cust_search_bill, width=40)
        self.entry3.pack(side="left", ipady=2)
        self.entry3.bind("<Return>", lambda e: self.search_bill())
        self.button2 = ttk.Button(row, text="Search", bootstyle="primary", command=self.search_bill)
        self.button2.pack(side="left", padx=8)
        ttk.Button(row, text="Reprint PDF", bootstyle="primary-outline",
                   command=self.reprint).pack(side="right")
        ttk.Button(row, text="View", bootstyle="secondary-outline",
                   command=self.view).pack(side="right", padx=8)
        cols = [("bill_no", "Invoice", 140, "w"), ("date", "Date", 100, "w"),
                ("customer_name", "Customer", 200, "w"), ("customer_no", "Phone", 120, "w"),
                ("grand_total", "Total", 100, "e"), ("payment_mode", "Payment", 90, "w"),
                ("status", "Status", 100, "w")]
        self.table = ui.DataTable(c, cols, height=14)
        self.table.pack(fill="both", expand=True)
        self.table.on_double_click(lambda r: ui.InvoicePreview(self, r["bill_no"]))
        self.search_bill(initial=True)
        self.entry3.focus_set()

    def search_bill(self, initial=False):
        text = self.cust_search_bill.get().strip()
        with db.connect() as conn:
            rows = invoices.search_invoices(conn, text)[:500]
        for r in rows:
            r["grand_total"] = billing.money(r["grand_total"]) if r["grand_total"] else ""
        self.table.set_rows(rows, iid_key="bill_no",
                            tag_fn=lambda r: ["cancelled"] if r["status"] == "CANCELLED" else [])
        if not rows and not initial:
            ui.error(self, "Error!!", "Bill not found.")

    def _one(self):
        sel = self.table.selected()
        if not sel:
            ui.error(self, "Oops!", "Select an invoice first.")
            return None
        return sel[0]["bill_no"]

    def view(self):
        b = self._one()
        if b:
            ui.InvoicePreview(self, b)

    def reprint(self):
        b = self._one()
        if b:
            ui.print_invoice(self, b)


def main():
    global root, page1
    ui.setup_logging()
    root = ui.create_root("Billwise - Invoicing desk", maximize=True)
    if not ui.init_database(root):
        root.destroy()
        return
    root.protocol("WM_DELETE_WINDOW", exitt)
    page1 = login_page(root)
    page1.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
