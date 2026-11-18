"""GUI tests (real Tk windows, temporary database, dialogs mocked).

Covers login/navigation, cart operations, quantity validation, invoice
generation, duplicate-generation protection and the PDF = DB = GUI check.
"""
import os
import tkinter as tk
from unittest import mock

import ttkbootstrap as ttk

import db
import invoice_pdf
import invoices
import people
import ui
from billing import fmt
from tests import fixtures as fx
from tests.helpers import TempDBTestCase
from tests.test_pdf import pdf_text


_ROOT = None


def shared_root():
    """ttkbootstrap supports one Tk root per process: reuse it, clearing its children."""
    global _ROOT
    if _ROOT is None:
        _ROOT = ui.create_root("TEST")
        _ROOT.withdraw()
    for w in list(_ROOT.winfo_children()):
        w.destroy()
    return _ROOT


def tearDownModule():
    if _ROOT is not None:
        _ROOT.destroy()


def all_buttons(widget):
    out = []
    for w in widget.winfo_children():
        if isinstance(w, (ttk.Button, tk.Button)):
            out.append(w)
        out += all_buttons(w)
    return out


class GuiTestCase(TempDBTestCase):
    def setUp(self):
        super().setUp()
        with db.connect() as c:
            fx.setup_store(c)
            fx.add_admin(c)
            self.soap = fx.add_product(c, "gui soap", "45.50", "18", 10, cost="30")
            self.rice = fx.add_product(c, "gui rice", "105", "5", 4, cost="80")
            people.add_employee(c, dict(name="TEST cashier", contact_num="6123456789",
                                        aadhar_num="234567890123", designation="Cashier",
                                        address="TEST", password="cashier1"))
            people.add_employee(c, dict(name="TEST manager", contact_num="6123456780",
                                        aadhar_num="234567890124", designation="Manager",
                                        address="TEST", password="manager1"))
            self.cashier = c.execute("SELECT emp_id FROM employee WHERE designation='Cashier'").fetchone()[0]
            self.manager = c.execute("SELECT emp_id FROM employee WHERE designation='Manager'").fetchone()[0]
        self.patches = [mock.patch("ui.messagebox"), mock.patch("ui.open_file"),
                        mock.patch("invoice_pdf.invoice_dir", return_value=self.tmp)]
        self.mb = self.patches[0].start()
        for p in self.patches[1:]:
            p.start()
        self.mb.askyesno.return_value = True
        self.root = shared_root()

    def tearDown(self):
        for w in list(self.root.winfo_children()):
            w.destroy()
        for p in self.patches:
            p.stop()
        super().tearDown()

    def errors(self):
        return [c.args for c in self.mb.showerror.call_args_list]


class EmployeeGuiTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        import employee
        self.emp = employee
        employee.shell = None
        employee.username = None
        employee.root = self.root
        employee.page1 = employee.login_page(self.root)
        employee.page1.pack(fill="both", expand=True)

    def login(self, user="EMP0000", pw="testpass1"):
        return self.emp.login(user, pw)

    def pick(self, page, index, qty, disc="0"):
        page.combo1.set("TEST cat")
        page.get_category()
        page.combo2.set("TEST sub")
        page.get_subcat()
        page.combo3.current(index)  # sorted: 0 = rice, 1 = soap
        page.show_qty()
        ui.set_entry(page.entry4, qty)
        ui.set_entry(page.entry_disc, disc)
        page.add_to_cart()

    def test_login_wrong_and_right(self):
        self.assertIsNotNone(self.login(pw="wrong"))
        self.assertIsNone(self.emp.shell)
        self.assertIsNone(self.login(self.cashier, "cashier1"))
        self.assertIsInstance(self.emp.shell.page, self.emp.bill_window)
        self.emp.navigate("find")
        self.assertIsInstance(self.emp.shell.page, self.emp.find_invoice_page)
        self.emp.logout()
        self.assertIsNone(self.emp.shell)

    def test_cart_operations_and_validation(self):
        self.login()
        p = self.emp.shell.page
        self.pick(p, 1, "2")
        self.pick(p, 1, "3")          # same product aggregates
        self.assertEqual(p.cart.quantities(), {self.soap: 5})
        self.pick(p, 0, "5")          # rice stock is 4
        self.assertTrue(any("in stock" in str(e) for e in self.errors()))
        self.pick(p, 0, "0")
        self.pick(p, 0, "abc")
        self.assertEqual(p.cart.quantities(), {self.soap: 5})
        self.pick(p, 0, "2")
        p.table.tree.selection_set(str(self.soap))
        p.remove_product()
        self.assertEqual(p.cart.quantities(), {self.rice: 2})
        p.remove_product()            # nothing selected -> removes last item
        self.assertTrue(p.cart.is_empty())
        self.assertEqual(p.totals_vars["grand_total"].get(), "Rs. 0.00")

    def _bill(self, state_code):
        import gst_states
        self.login()
        p = self.emp.shell.page
        self.pick(p, 1, "3", "10")
        self.pick(p, 0, "2")
        p.pos.set(gst_states.label(state_code))
        p.refresh()
        p.cust_name.set("TEST Customer")
        p.cust_num.set("9876543210")
        p.tendered.set("1000")
        before = {k: v.get() for k, v in p.totals_vars.items()}
        p.gen_bill()
        self.assertEqual(self.errors(), [])
        return p, before

    def _assert_gui_db_pdf_match(self, p, before):
        with db.connect() as conn:
            inv = invoices.get_invoice(conn, p.last_bill)
            path = invoice_pdf.generate_invoice_pdf(inv, invoice_pdf.store_details(conn),
                                                    os.path.join(self.tmp, "gui.pdf"))
        gui = {k: v.get() for k, v in p.totals_vars.items()}
        self.assertEqual(gui, before)  # what the cashier saw == what was saved
        expected = {"subtotal": fmt(inv["subtotal"]), "discount": ("-" if inv["discount_total"] else "") + fmt(inv["discount_total"]),
                    "taxable": fmt(inv["taxable_total"]), "cgst": fmt(inv["cgst_total"]),
                    "sgst": fmt(inv["sgst_total"]), "igst": fmt(inv["igst_total"]),
                    "round_off": fmt(inv["round_off"]), "grand_total": "Rs. " + fmt(inv["grand_total"])}
        self.assertEqual(gui, expected)  # GUI == DB
        lines = [ln.strip() for ln in pdf_text(path).splitlines()]
        value_after = {lines[i]: lines[i + 1] for i in range(len(lines) - 1)}
        self.assertEqual(value_after["TOTAL PAYABLE (Rs.)"], fmt(inv["grand_total"]))  # PDF == DB
        self.assertEqual(value_after["Taxable amount"], fmt(inv["taxable_total"]))
        self.assertEqual(value_after["Round off"], fmt(inv["round_off"]))
        return inv

    def test_intra_state_pdf_db_gui_match(self):
        p, before = self._bill(fx.TEST_STORE_STATE)
        inv = self._assert_gui_db_pdf_match(p, before)
        self.assertEqual(inv["supply_type"], "INTRA")
        self.assertNotEqual(inv["cgst_total"], 0)
        with db.connect() as conn:
            stock = dict(conn.execute("SELECT product_id, stock FROM raw_inventory").fetchall())
        self.assertEqual(stock, {self.soap: 7, self.rice: 2})

    def test_inter_state_pdf_db_gui_match(self):
        p, before = self._bill(fx.OTHER_STATE)
        inv = self._assert_gui_db_pdf_match(p, before)
        self.assertEqual(inv["supply_type"], "INTER")
        self.assertEqual(inv["cgst_total"], 0)
        self.assertNotEqual(inv["igst_total"], 0)

    def test_no_duplicate_invoice_on_second_click(self):
        p, _ = self._bill(fx.TEST_STORE_STATE)
        p.gen_bill()
        p.add_to_cart()
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bill").fetchone()[0], 1)
        p.clear_bill()
        self.assertTrue(p.cart.is_empty())
        self.assertEqual(p.state, 1)
        self.assertEqual(p.cust_name.get(), "")

    def test_generate_validation(self):
        self.login()
        p = self.emp.shell.page
        p.gen_bill()                                   # no name
        p.cust_name.set("TEST")
        p.cust_num.set("123")
        p.gen_bill()                                   # bad phone
        p.cust_num.set("9876543210")
        p.gen_bill()                                   # empty cart
        self.assertEqual(len(self.errors()), 3)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bill").fetchone()[0], 0)

    def test_buttons_have_commands(self):
        self.login()
        for key in ("billing", "find"):
            self.emp.shell.show(key)
            for b in all_buttons(self.emp.shell.page):
                self.assertTrue(str(b.cget("command")), "button without command: %s" % b.cget("text"))


class AdminGuiTests(GuiTestCase):
    def setUp(self):
        super().setUp()
        import admin
        self.adm = admin
        admin.shell = None
        admin.current_user = None
        admin.root = self.root
        admin.page1 = admin.login_page(self.root)
        admin.page1.pack(fill="both", expand=True)

    def test_cashier_refused_manager_limited_admin_full(self):
        self.assertIn("not an admin", self.adm.login(self.cashier, "cashier1"))
        self.assertIsNone(self.adm.login(self.manager, "manager1"))
        self.assertNotIn("employees", self.adm.shell.pages)
        self.assertNotIn("settings", self.adm.shell.pages)
        self.assertIn("inventory", self.adm.shell.pages)
        self.adm.Logout()
        self.assertIsNone(self.adm.login("EMP0000", "testpass1"))
        self.assertEqual(len(self.adm.shell.pages), len(self.adm.PAGES))

    def test_every_page_opens_and_every_button_has_a_command(self):
        self.adm.login("EMP0000", "testpass1")
        for key in self.adm.shell.pages:
            page = self.adm.shell.show(key)
            self.root.update_idletasks()
            for b in all_buttons(page):
                self.assertTrue(str(b.cget("command")), "%s: button '%s' has no command"
                                % (key, b.cget("text")))
        self.assertEqual(self.errors(), [])

    def test_employee_list_hides_secrets(self):
        self.adm.login("EMP0000", "testpass1")
        page = self.adm.shell.show("employees")
        shown = " ".join(str(v) for r in page.tree.rows.values() for v in r.values())
        self.assertNotIn("234567890123", shown)
        self.assertIn("XXXX-XXXX-0123", shown)
        self.assertNotIn("pbkdf2", shown)

    def test_cancel_invoice_from_invoices_page(self):
        from tests.test_services import cart_with
        with db.connect() as conn:
            bill = invoices.create_invoice(conn, cart_with(conn, (self.soap, 2)).lines,
                                           dict(fx.TEST_CUSTOMER), "27", "Cash")
        self.adm.login("EMP0000", "testpass1")
        page = self.adm.shell.show("invoices")
        page.tree.tree.selection_set(bill)
        with mock.patch("admin.simpledialog.askstring", return_value="TEST reason"):
            page.delete_invoice()
        with db.connect() as conn:
            inv = invoices.get_invoice(conn, bill)
            stock = conn.execute("SELECT stock FROM raw_inventory WHERE product_id=?",
                                 (self.soap,)).fetchone()[0]
        self.assertEqual((inv["status"], stock), ("CANCELLED", 10))
        page.tree.tree.selection_set(bill)
        prev = self.adm.open_bill(page, bill)
        prev.destroy()


class FirstRunTests(TempDBTestCase):
    def test_first_run_creates_hashed_master_admin(self):
        with mock.patch("ui.messagebox"):
            root = shared_root()
            import admin
            admin.root = root
            done = []
            dlg = admin.FirstRunSetup(root, lambda: done.append(True))
            ui.set_entry(dlg.name, "TEST owner")
            ui.set_entry(dlg.pw1, "firstpass1")
            ui.set_entry(dlg.pw2, "firstpass1")
            ui.set_entry(dlg.store, "TEST store")
            dlg.state_box.set("27 - Maharashtra")
            dlg.save()
            for w in list(root.winfo_children()):
                w.destroy()
        self.assertEqual(done, [True])
        with db.connect() as conn:
            self.assertIsNotNone(people.authenticate(conn, "EMP0000", "firstpass1"))
            self.assertEqual(db.get_setting(conn, "store_state_code"), "27")


class QuickSearchGuiTests(EmployeeGuiTests):
    def test_quick_search_adds_by_sku_and_name(self):
        import demo_catalogue
        with db.connect() as conn:
            demo_catalogue.load(conn, "TESTER")
        self.login()
        p = self.emp.shell.page
        p.find_var.set("DEMO-DRY-001")
        p.quick_search()
        ui.set_entry(p.entry4, "2")
        p.add_to_cart()
        p.find_var.set("no such product")
        p.quick_search()
        self.assertEqual(self.errors(), [])
        self.assertEqual(sum(p.cart.quantities().values()), 2)
        self.assertIn("Amul", p.cart.lines[0].name)
