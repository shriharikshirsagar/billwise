"""Shared Billwise widgets built on theme.py (sidebar, top bar, cards, tables,
dialogs and the invoice preview). Colours and fonts always come from theme."""
import logging
import os
import sys
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import ttkbootstrap as ttk

import db
import theme
from billing import fmt

C = theme.COLORS
log = logging.getLogger("billwise.ui")


def tk_plain(cls, *args, **kw):
    """Plain Tk widget with our own colours (ttkbootstrap would restyle it)."""
    return cls(*args, autostyle=False, **kw)


# ------------------------------------------------------------ app setup
def setup_logging():
    os.makedirs(db.app_path("logs"), exist_ok=True)
    logging.basicConfig(filename=db.app_path("logs", "billwise.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Third-party DEBUG chatter (PIL chunks, matplotlib fonts) filled the old logs.
    for noisy in ("PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def create_root(title, size=(1366, 768), maximize=False):
    root = ttk.Window(themename="litera", title=title)
    theme.init_fonts(root)
    theme.register_theme(root.style)
    root.configure(background=C["ice"])
    w, h = size
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(w, sw - 40), min(h, sh - 80)
    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
    root.minsize(min(1100, w), min(660, h))
    try:
        root.iconphoto(True, theme.logo_image(32))
    except tk.TclError:
        pass
    root.report_callback_exception = _report_exception
    if maximize:
        try:
            root.state("zoomed")  # Windows: use the whole screen, keep the title bar
        except tk.TclError:
            pass
    return root


def _report_exception(exc, val, tb):
    log.error("Unhandled UI error", exc_info=(exc, val, tb))
    messagebox.showerror("Unexpected error",
                         "Something went wrong:\n%s\n\nDetails were written to logs/billwise.log" % val)


def init_database(parent=None):
    """Create/upgrade the database; returns False (after telling the user) on failure."""
    try:
        backup = db.init_db()
        if backup:
            log.info("Database upgraded; backup at %s", backup)
        return True
    except Exception as e:  # noqa: BLE001 - shown to the user
        log.exception("Database initialisation failed")
        messagebox.showerror("Database error", "Could not open the database:\n%s" % e, parent=parent)
        return False


# ------------------------------------------------------------ messages
def info(parent, title, text):
    messagebox.showinfo(title, text, parent=parent)


def error(parent, title, text):
    messagebox.showerror(title, text, parent=parent)


def warn(parent, title, text):
    messagebox.showwarning(title, text, parent=parent)


def confirm(parent, title, text):
    return messagebox.askyesno(title, text, parent=parent)


def open_file(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 - opens a file we generated
        else:
            import subprocess
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", path])
    except OSError as e:
        log.warning("Could not open %s: %s", path, e)
        messagebox.showinfo("Saved", "File saved to:\n%s" % path)


# ------------------------------------------------------------ layout
class Sidebar(tk.Frame):
    """Deep-navy navigation rail: brand, grouped sections, signed-in user."""
    WIDTH = 240

    def __init__(self, parent, items, bottom_items=(), subtitle="", user=None):
        super().__init__(parent, bg=C["navy"], width=self.WIDTH, autostyle=False)
        self.pack_propagate(False)
        self.buttons = {}
        self.active = None
        brand = tk_plain(tk.Frame, self, bg=C["navy"])
        brand.pack(fill="x", padx=20, pady=(22, 0))
        tk_plain(tk.Label, brand, image=theme.logo_image(38), bg=C["navy"]).pack(side="left")
        txt = tk_plain(tk.Frame, brand, bg=C["navy"])
        txt.pack(side="left", padx=10)
        tk_plain(tk.Label, txt, text=theme.APP_NAME, bg=C["navy"], fg=C["white"],
                 font=theme.font("brand")).pack(anchor="w")
        tk_plain(tk.Label, txt, text=(subtitle or "").upper(), bg=C["navy"], fg=C["mint"],
                 font=theme.font("caps")).pack(anchor="w")
        tk_plain(tk.Frame, self, bg=C["navy_line"], height=1).pack(fill="x", padx=20, pady=(14, 2))
        for item in items:
            if item[0] is None:          # section header
                tk_plain(tk.Label, self, text=item[1].upper(), bg=C["navy"], fg=C["muted_on_navy"],
                         font=theme.font("caps"), anchor="w").pack(fill="x", padx=24, pady=(8, 2))
            else:
                self._add(*item)
        tk_plain(tk.Frame, self, bg=C["navy"]).pack(fill="both", expand=True)
        if user:
            self._user_block(*user)
        foot = tk_plain(tk.Frame, self, bg=C["navy"])
        foot.pack(fill="x", pady=(0, 12))
        for key, label, icon, cmd in bottom_items:
            self._add(key, label, icon, cmd, active_style=False, parent=foot, compact=True)

    def _user_block(self, name, role):
        tk_plain(tk.Frame, self, bg=C["navy_line"], height=1).pack(fill="x", padx=20, pady=(0, 10))
        box = tk_plain(tk.Frame, self, bg=C["navy"])
        box.pack(fill="x", padx=20, pady=(0, 8))
        av = tk_plain(tk.Canvas, box, width=36, height=36, bg=C["navy"], highlightthickness=0)
        av.pack(side="left")
        av.create_oval(1, 1, 35, 35, fill=C["green"], outline="")
        initials = "".join(p[0] for p in (name or "?").split()[:2]).upper()
        av.create_text(18, 18, text=initials, fill=C["white"], font=theme.font("body_bold"))
        t = tk_plain(tk.Frame, box, bg=C["navy"])
        t.pack(side="left", padx=10)
        tk_plain(tk.Label, t, text=name, bg=C["navy"], fg=C["white"], font=theme.font("body_bold"),
                 anchor="w").pack(anchor="w")
        tk_plain(tk.Label, t, text=role, bg=C["navy"], fg=C["muted_on_navy"], font=theme.font("small"),
                 anchor="w").pack(anchor="w")

    def _add(self, key, label, icon, cmd, active_style=True, parent=None, compact=False):
        row = tk_plain(tk.Frame, parent or self, bg=C["navy"], cursor="hand2")
        row.pack(fill="x", padx=(0, 12))
        bar = tk_plain(tk.Frame, row, bg=C["navy"], width=4)
        bar.pack(side="left", fill="y")
        fam = theme.FONTS.get("icon_family")
        ic = tk_plain(tk.Label, row, text=theme.icon(icon), bg=C["navy"], fg=C["mint"], width=3,
                      font=(fam, 11) if fam else theme.font("nav"))
        ic.pack(side="left", padx=(14, 2), pady=4 if compact else 6)
        lb = tk_plain(tk.Label, row, text=label, bg=C["navy"],
                      fg=C["muted_on_navy"] if compact else C["ice"],
                      font=theme.font("body") if compact else theme.font("nav"), anchor="w")
        lb.pack(side="left", fill="x", expand=True)
        for w in (row, ic, lb):
            w.bind("<Button-1>", lambda e, c=cmd: c())
            w.bind("<Enter>", lambda e, k=key: self._hover(k, True))
            w.bind("<Leave>", lambda e, k=key: self._hover(k, False))
        self.buttons[key] = (row, bar, ic, lb, active_style)

    def _paint(self, key, bg, bar, fg=None):
        row, b, ic, lb, _ = self.buttons[key]
        for w in (row, ic, lb):
            w.configure(bg=bg)
        b.configure(bg=bar)
        if fg:
            lb.configure(fg=fg)

    def _hover(self, key, inside):
        if key == self.active:
            return
        self._paint(key, C["navy_hover"] if inside else C["navy"], C["navy"])

    def set_active(self, key):
        if self.active in self.buttons:
            self._paint(self.active, C["navy"], C["navy"], C["ice"])
        self.active = key
        if key in self.buttons:
            self._paint(key, C["navy_hover"], C["green"], C["white"])  # green active indicator


class TopBar(tk.Canvas):
    """Broadcast-blue header: breadcrumb + page title, live date / time box."""
    HEIGHT = 72

    def __init__(self, parent, user_text="", section=""):
        super().__init__(parent, height=self.HEIGHT, highlightthickness=0, bg=C["blue"],
                         autostyle=False)
        self.user_text = user_text
        self.section = section
        self._img = None
        self._job = None
        self.title = ""
        self.bind("<Configure>", lambda e: self._draw())
        self._tick()

    def set_title(self, title):
        self.title = title
        self._draw()

    def _draw(self):
        w = max(self.winfo_width(), 400)
        h = self.HEIGHT
        self.delete("all")
        # very subtle left-to-right deepening, plus a fine green rule
        self._img = theme.gradient(w, h, C["blue"], C["blue_deep"], persist=False)
        self.create_image(0, 0, image=self._img, anchor="nw")
        self.create_rectangle(0, h - 2, w, h, fill=C["green"], outline="")
        if self.section:
            self.create_text(28, 22, text="%s   ›" % self.section.upper(), anchor="w",
                             fill=C["mint"], font=theme.font("caps"))
        self.create_text(28, 46 if self.section else h // 2, text=self.title, anchor="w",
                         fill=C["white"], font=theme.font("h1"))
        bx, by0, by1 = w - 236, 13, h - 15
        self.create_rectangle(bx, by0, w - 22, by1, fill=C["white"], outline="")
        self.create_rectangle(bx, by0, bx + 4, by1, fill=C["green"], outline="")
        self.date_id = self.create_text(bx + 18, by0 + 13, text="", anchor="w", fill=C["muted"],
                                        font=theme.font("caps"))
        self.clock_id = self.create_text(bx + 18, by1 - 13, text="", anchor="w", fill=C["navy"],
                                         font=theme.font("h3"))
        if self.user_text:
            self.create_text(bx - 20, h // 2, text=self.user_text, anchor="e", fill=C["ice"],
                             font=theme.font("body"))
        self._update_clock()

    def _update_clock(self):
        try:
            now = datetime.now()
            self.itemconfigure(self.date_id, text=now.strftime("%a, %d %b %Y").upper())
            self.itemconfigure(self.clock_id, text=now.strftime("%I:%M:%S %p"))
        except (tk.TclError, AttributeError):
            pass

    def _tick(self):
        self._update_clock()
        self._job = self.after(1000, self._tick)

    def destroy(self):
        if self._job:
            self.after_cancel(self._job)
        super().destroy()


class Shell(ttk.Frame):
    """Sidebar + top bar + content area. ``pages``: {key: (title, factory)}."""

    def __init__(self, root, pages, nav, bottom, user_text="", subtitle="", user=None):
        super().__init__(root)
        self.pages = pages
        self.sidebar = Sidebar(self, nav, bottom, subtitle, user)
        self.sidebar.pack(side="left", fill="y")
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)
        self.topbar = TopBar(right, "" if user else user_text, subtitle)
        self.topbar.pack(fill="x")
        self.content = ttk.Frame(right, padding=(22, 18))
        self.content.pack(fill="both", expand=True)
        self.page = None
        self.current = None

    def show(self, key):
        title, factory = self.pages[key]
        if self.page is not None:
            self.page.destroy()
        self.page = factory(self.content)
        self.page.pack(fill="both", expand=True)
        self.current = key
        self.sidebar.set_active(key)
        self.topbar.set_title(title)
        return self.page


def card(parent, title=None, subtitle=None, padding=14):
    """White panel; the title sits on a hairline like a ledger heading."""
    outer = ttk.Frame(parent, style="Card.TFrame", padding=padding)
    if title:
        head = ttk.Frame(outer, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=title, style="CardTitle.TLabel").pack(side="left")
        if subtitle:
            ttk.Label(head, text=subtitle, style="CardMuted.TLabel").pack(side="left", padx=10, pady=(3, 0))
        tk_plain(tk.Frame, outer, bg=C["line"], height=1).pack(fill="x", pady=(6, 10))
        outer.head = head
    return outer


METRIC_ACCENT = {"Metric.TLabel": "blue", "MetricGreen.TLabel": "green", "MetricAmber.TLabel": "amber"}


def metric_card(parent, label, value, style="Metric.TLabel", caption=""):
    """Ledger tile: coloured edge, small-caps label, large figure, quiet caption."""
    c = ttk.Frame(parent, style="Card.TFrame")
    tk_plain(tk.Frame, c, bg=C[METRIC_ACCENT.get(style, "blue")], width=4).pack(side="left", fill="y")
    body = ttk.Frame(c, style="Card.TFrame", padding=(16, 12, 14, 12))
    body.pack(side="left", fill="both", expand=True)
    ttk.Label(body, text=label.upper(), style="CardCaps.TLabel").pack(anchor="w")
    var = tk.StringVar(value=value)
    ttk.Label(body, textvariable=var, style=style).pack(anchor="w", pady=(2, 0))
    if caption:
        ttk.Label(body, text=caption, style="CardMuted.TLabel").pack(anchor="w")
    c.var = var
    return c


def page_header(parent, title, subtitle=""):
    f = ttk.Frame(parent)
    f.pack(fill="x", pady=(0, 12))
    ttk.Label(f, text=title, style="PageTitle.TLabel").pack(side="left")
    if subtitle:
        ttk.Label(f, text=subtitle, style="PageSub.TLabel").pack(side="left", padx=12, pady=(6, 0))
    return f


class FormGrid:
    """Label-over-input form inside a card."""

    def __init__(self, parent, columns=2):
        self.parent = parent
        self.columns = columns
        self.i = 0
        for c in range(columns):
            parent.columnconfigure(c, weight=1, uniform="form")

    def add(self, label, widget_cls=ttk.Entry, span=1, **kw):
        r, c = divmod(self.i, self.columns)
        cell = ttk.Frame(self.parent, style="Card.TFrame")
        cell.grid(row=r, column=c, columnspan=span, sticky="ew", padx=5, pady=3)
        ttk.Label(cell, text=label, style="CardField.TLabel").pack(anchor="w")
        if widget_cls in (ttk.Entry, ttk.Combobox) and "width" not in kw:
            kw["width"] = 8  # let the grid decide the width
        w = widget_cls(cell, **kw)
        w.pack(fill="x", pady=(2, 0))
        self.i += span
        return w


class DataTable(ttk.Frame):
    """Treeview with scrollbars. columns: [(key, heading, width, anchor)]."""

    def __init__(self, parent, columns, height=12, selectmode="browse"):
        super().__init__(parent, style="Card.TFrame")
        self.keys = [c[0] for c in columns]
        self.tree = ttk.Treeview(self, columns=self.keys, show="headings", height=height,
                                 selectmode=selectmode)
        for key, heading, width, anchor in columns:
            self.tree.heading(key, text=heading, anchor=anchor)
            self.tree.column(key, width=width, minwidth=40, anchor=anchor, stretch=True)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, bootstyle="round")
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview, bootstyle="round")
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        theme.style_tree(self.tree)
        self.rows = {}

    def set_rows(self, rows, iid_key=None, tag_fn=None):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for i, r in enumerate(rows):
            tags = ["even" if i % 2 else "odd"]
            if tag_fn:
                tags += [t for t in (tag_fn(r) or []) if t]
            iid = str(r[iid_key]) if iid_key else str(i)
            self.tree.insert("", "end", iid=iid, values=[self._fmt(r.get(k)) for k in self.keys],
                             tags=tags)
            self.rows[iid] = r

    @staticmethod
    def _fmt(v):
        from decimal import Decimal
        if isinstance(v, Decimal):
            return fmt(v)
        return "" if v is None else v

    def selected(self):
        return [self.rows[i] for i in self.tree.selection() if i in self.rows]

    def on_double_click(self, fn):
        def handler(event):
            iid = self.tree.identify_row(event.y)
            if iid and iid in self.rows:  # ignore headings / empty space
                fn(self.rows[iid])
        self.tree.bind("<Double-1>", handler)


class Dialog(tk.Toplevel):
    def __init__(self, parent, title, width=640, height=None):
        super().__init__(parent)
        self.withdraw()
        self.title("%s - %s" % (title, theme.APP_NAME))
        self.configure(background=C["ice"])
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        head = tk_plain(tk.Frame, self, bg=C["navy"], height=52)
        head.pack(fill="x")
        tk_plain(tk.Frame, head, bg=C["green"], width=6).pack(side="left", fill="y")
        tk_plain(tk.Label, head, text=title, bg=C["navy"], fg=C["white"], font=theme.font("h2")).pack(
            side="left", padx=14, pady=12)
        self.body = card(self, padding=18)
        self.body.pack(fill="both", expand=True, padx=16, pady=16)
        self.buttons = ttk.Frame(self, padding=(16, 0, 16, 16))
        self.buttons.pack(fill="x")
        self._size = (width, height)
        self.bind("<Escape>", lambda e: self.destroy())

    def present(self):
        self.update_idletasks()
        w = self._size[0]
        h = self._size[1] or self.winfo_reqheight()
        p = self.master.winfo_toplevel()
        x = p.winfo_rootx() + max(0, (p.winfo_width() - w) // 2)
        y = p.winfo_rooty() + max(0, (p.winfo_height() - h) // 3)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.deiconify()
        self.grab_set()
        self.focus_set()


def on_card(widget):
    """Give a ttk widget's style a white background so it sits cleanly on a card."""
    style = widget.cget("style") or widget.winfo_class()
    ttk.Style().configure(style, background=C["white"])
    return widget


def set_entry(entry, value):
    state = str(entry.cget("state"))
    entry.configure(state="normal")
    entry.delete(0, "end")
    entry.insert(0, "" if value is None else str(value))
    entry.configure(state=state)


# ------------------------------------------------------------ invoice preview
class InvoicePreview(Dialog):
    """Read-only view of a stored invoice (values exactly as saved)."""

    def __init__(self, parent, bill_no, on_pdf=None):
        import invoices
        with db.connect() as conn:
            inv = invoices.get_invoice(conn, bill_no)
        super().__init__(parent, "Invoice %s" % bill_no, width=900)
        self.inv = inv
        if inv is None:
            ttk.Label(self.body, text="Invoice not found.", style="Error.TLabel").pack()
            ttk.Button(self.buttons, text="Close", command=self.destroy).pack(side="right")
            self.present()
            return
        top = ttk.Frame(self.body, style="Card.TFrame")
        top.pack(fill="x")
        left = [("Invoice", inv["bill_no"]), ("Date", inv["date"]), ("Customer", inv["customer_name"]),
                ("Phone", inv["customer_no"])]
        right = [("Status", inv["status"]), ("Payment", inv.get("payment_mode") or "-"),
                 ("Supply", {"INTRA": "Intra-state", "INTER": "Inter-state"}.get(
                     inv.get("supply_type"), "Original app bill")),
                 ("Cashier", inv.get("created_by") or "-")]
        for col, pairs in enumerate((left, right)):
            box = ttk.Frame(top, style="Card.TFrame")
            box.grid(row=0, column=col, sticky="nw", padx=(0, 40))
            for r, (k, v) in enumerate(pairs):
                ttk.Label(box, text=k, style="CardMuted.TLabel").grid(row=r, column=0, sticky="w")
                ttk.Label(box, text=v or "", style="CardField.TLabel" if k != "Status" else
                          ("Error.TLabel" if v == "CANCELLED" else "Green.TLabel")).grid(
                    row=r, column=1, sticky="w", padx=10)
        if inv["legacy"]:
            txt = tk_plain(tk.Text, self.body, height=14, font=theme.font("mono"), relief="flat",
                          bg=C["ice"], fg=C["text"])
            txt.insert("1.0", inv.get("bill_details") or "")
            txt.configure(state="disabled")
            txt.pack(fill="both", expand=True, pady=10)
        else:
            cols = [("line_no", "#", 40, "center"), ("product_name", "Product", 220, "w"),
                    ("qty", "Qty", 50, "e"), ("unit_price", "Rate", 80, "e"),
                    ("discount_amount", "Discount", 80, "e"), ("taxable_amount", "Taxable", 90, "e"),
                    ("gst_rate", "GST %", 60, "e"), ("tax", "GST", 80, "e"),
                    ("line_total", "Amount", 90, "e")]
            table = DataTable(self.body, cols, height=8)
            table.pack(fill="both", expand=True, pady=10)
            rows = [dict(it, tax=it["cgst_amount"] + it["sgst_amount"] + it["igst_amount"],
                         gst_rate="%s%%" % it["gst_rate"]) for it in inv["items"]]
            table.set_rows(rows)
            tot = ttk.Frame(self.body, style="Card.TFrame")
            tot.pack(anchor="e")
            pairs = [("Subtotal", inv["subtotal"]), ("Discount", inv["discount_total"]),
                     ("Taxable", inv["taxable_total"])]
            pairs += ([("CGST", inv["cgst_total"]), ("SGST", inv["sgst_total"])]
                      if inv["supply_type"] == "INTRA" else [("IGST", inv["igst_total"])])
            pairs += [("Round off", inv["round_off"]), ("Total payable", inv["grand_total"])]
            for r, (k, v) in enumerate(pairs):
                last = r == len(pairs) - 1
                ttk.Label(tot, text=k, style="CardField.TLabel").grid(row=r, column=0, sticky="e")
                ttk.Label(tot, text="Rs. " + fmt(v), style="Total.TLabel" if last else "Card.TLabel"
                          ).grid(row=r, column=1, sticky="e", padx=(16, 0))
        if inv["status"] == "CANCELLED":
            ttk.Label(self.body, text="Cancelled %s by %s - %s" % (
                inv.get("cancelled_at"), inv.get("cancelled_by"), inv.get("cancel_reason")),
                style="Error.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Button(self.buttons, text="Close", bootstyle="secondary-outline",
                   command=self.destroy).pack(side="right")
        ttk.Button(self.buttons, text="Open / Reprint PDF", bootstyle="primary",
                   command=lambda: print_invoice(self, bill_no)).pack(side="right", padx=8)
        self.present()


def print_invoice(parent, bill_no, open_after=True):
    """(Re)generate the PDF from stored values and open it."""
    import invoice_pdf
    import invoices
    try:
        with db.connect() as conn:
            inv = invoices.get_invoice(conn, bill_no)
            if inv is None:
                error(parent, "Not found", "Invoice %s not found." % bill_no)
                return None
            path = invoice_pdf.generate_invoice_pdf(inv, invoice_pdf.store_details(conn))
    except Exception as e:  # noqa: BLE001 - reported to the user
        log.exception("PDF generation failed for %s", bill_no)
        error(parent, "PDF error", "Could not create the PDF:\n%s" % e)
        return None
    if open_after:
        open_file(path)
    return path


# ------------------------------------------------------------ login
class LoginView(ttk.Frame):
    """Shared themed sign-in screen. on_submit(emp_id, password) -> error text or None."""

    def __init__(self, root, heading, subheading, on_submit, extra_button=None):
        super().__init__(root)
        self.on_submit = on_submit
        self.brand = tk_plain(tk.Canvas, self, width=440, highlightthickness=0, bg=C["navy"])
        self.brand.pack(side="left", fill="y")
        self.brand.bind("<Configure>", self._draw)
        self.logo = theme.logo_image(72)
        self.heading = heading
        right = ttk.Frame(self, padding=40)
        right.pack(side="left", fill="both", expand=True)
        box = card(right, padding=36)
        box.place(relx=0.5, rely=0.5, anchor="center", width=440)
        ttk.Label(box, text=heading, style="CardTitle.TLabel", font=theme.font("h1")).pack(anchor="w")
        ttk.Label(box, text=subheading, style="CardMuted.TLabel").pack(anchor="w", pady=(4, 22))
        ttk.Label(box, text="Employee ID", style="CardField.TLabel").pack(anchor="w")
        self.user = tk.StringVar()
        self.passwd = tk.StringVar()
        self.entry1 = ttk.Entry(box, textvariable=self.user, font=theme.font("body"))
        self.entry1.pack(fill="x", pady=(4, 14), ipady=3)
        ttk.Label(box, text="Password", style="CardField.TLabel").pack(anchor="w")
        self.entry2 = ttk.Entry(box, textvariable=self.passwd, show="\u2022", font=theme.font("body"))
        self.entry2.pack(fill="x", pady=(4, 6), ipady=3)
        self.msg = tk.StringVar()
        ttk.Label(box, textvariable=self.msg, style="Error.TLabel").pack(anchor="w", pady=(2, 10))
        self.button1 = ttk.Button(box, text="LOGIN", bootstyle="primary", command=self.submit)
        self.button1.pack(fill="x", ipady=6)
        if extra_button:
            text, cmd = extra_button
            ttk.Button(box, text=text, bootstyle="secondary-link", command=cmd).pack(pady=(10, 0))
        self.entry1.bind("<Return>", lambda e: self.entry2.focus_set())
        self.entry2.bind("<Return>", self.submit)
        self.after(50, self.entry1.focus_set)

    def _draw(self, event=None):
        h = max(self.brand.winfo_height(), 600)
        b = self.brand
        b.delete("all")
        b.img = theme.gradient(440, h, C["navy"], C["blue"], horizontal=False, persist=False)
        b.create_image(0, 0, image=b.img, anchor="nw")
        b.create_rectangle(0, 0, 8, h, fill=C["green"], outline="")
        b.create_image(56, h * 0.38, image=self.logo, anchor="w")
        b.create_text(56, h * 0.38 + 64, text=theme.APP_NAME, anchor="w", fill=C["white"],
                      font=(theme.FONTS["families"]["heading"], 36, "bold"))
        b.create_text(58, h * 0.38 + 110, text=theme.TAGLINE, anchor="w", fill=C["ice"],
                      font=theme.font("h3"))

    def submit(self, event=None):
        uid, pw = self.user.get().strip(), self.passwd.get()
        if not uid or not pw:
            self.msg.set("Enter your employee ID and password.")
            return
        err = self.on_submit(uid, pw)
        self.passwd.set("")
        if err:
            self.msg.set(err)
            self.entry2.focus_set()
        else:
            self.msg.set("")
            self.user.set("")
