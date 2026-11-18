from datetime import datetime
from decimal import Decimal as D
from unittest import mock

import db
import inventory
import invoices
import people
import security
from billing import BillingError, Cart
from tests import fixtures as fx
from tests.helpers import TempDBTestCase


def cart_with(conn, *items):
    """items: (product_id, qty[, discount])"""
    c = Cart()
    for item in items:
        pid, qty = item[0], item[1]
        p = inventory.get_product(conn, pid)
        c.add(pid, p["product_name"], p["mrp"], p["gst_rate"], qty, p["stock"],
              item[2] if len(item) > 2 else 0, p["hsn_code"], p["cost_price"])
    return c


class InvoiceTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.conn_cm = db.connect()
        self.conn = self.conn_cm.__enter__()
        fx.setup_store(self.conn)
        self.soap = fx.add_product(self.conn, "soap", "118", "18", 10, cost="80")
        self.rice = fx.add_product(self.conn, "rice", "105", "5", 3, cost="90")

    def tearDown(self):
        self.conn_cm.__exit__(None, None, None)
        super().tearDown()

    def make(self, cart, state=fx.TEST_STORE_STATE, mode="Cash", tendered=None, ref="", when=None):
        return invoices.create_invoice(self.conn, cart.lines, dict(fx.TEST_CUSTOMER), state, mode,
                                       tendered, ref, user="TESTER", when=when)

    def test_create_intra_invoice_and_stock_deduction(self):
        bill = self.make(cart_with(self.conn, (self.soap, 2), (self.rice, 1)), tendered="400")
        inv = invoices.get_invoice(self.conn, bill)
        self.assertEqual(inv["supply_type"], "INTRA")
        self.assertEqual(inv["taxable_total"], D("300.00"))
        self.assertEqual((inv["cgst_total"], inv["sgst_total"], inv["igst_total"]),
                         (D("20.50"), D("20.50"), D("0.00")))
        self.assertEqual(inv["grand_total"], D("341.00"))
        self.assertEqual(inv["change_due"], D("59.00"))
        self.assertEqual(len(inv["items"]), 2)
        self.assertEqual(inventory.get_product(self.conn, self.soap)["stock"], 8)
        self.assertEqual(inventory.get_product(self.conn, self.rice)["stock"], 2)
        sales = [m for m in inventory.movements(self.conn) if m["movement_type"] == "SALE"]
        self.assertEqual(sorted(m["change_qty"] for m in sales), [-2, -1])

    def test_interstate_uses_igst(self):
        bill = self.make(cart_with(self.conn, (self.soap, 1)), state=fx.OTHER_STATE,
                         mode="UPI", ref="TESTUPI")
        inv = invoices.get_invoice(self.conn, bill)
        self.assertEqual(inv["supply_type"], "INTER")
        self.assertEqual((inv["igst_total"], inv["cgst_total"]), (D("18.00"), D("0.00")))
        self.assertEqual(inv["items"][0]["igst_amount"], D("18.00"))

    def test_numbers_are_unique_and_sequential(self):
        when = datetime(2026, 11, 18, 10, 0)
        nos = [self.make(cart_with(self.conn, (self.soap, 1)), when=when) for _ in range(3)]
        self.assertEqual(nos, ["BW2627-000001", "BW2627-000002", "BW2627-000003"])
        self.assertEqual(invoices.financial_year(datetime(2027, 3, 31)), "2627")
        self.assertEqual(invoices.financial_year(datetime(2027, 4, 1)), "2728")

    def test_number_skips_existing_legacy_bill_no(self):
        with db.transaction(self.conn):
            self.conn.execute("INSERT INTO bill(bill_no, date) VALUES ('BW2627-000001', '2026-11-01')")
        no = self.make(cart_with(self.conn, (self.soap, 1)), when=datetime(2026, 11, 18))
        self.assertEqual(no, "BW2627-000002")

    def test_rollback_when_stock_deduction_fails(self):
        cart = cart_with(self.conn, (self.soap, 2), (self.rice, 3))
        # Someone else sells the rice after it went into this cart.
        inventory.adjust_stock(self.conn, self.rice, -2, "CORRECTION", "TEST concurrent sale")
        with self.assertRaises(inventory.StockError):
            self.make(cart)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bill").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM invoice_items").fetchone()[0], 0)
        self.assertEqual(inventory.get_product(self.conn, self.soap)["stock"], 10)
        self.assertEqual(self.conn.execute("SELECT last_no FROM invoice_counter").fetchone(), None)

    def test_rollback_on_unexpected_error_mid_transaction(self):
        cart = cart_with(self.conn, (self.soap, 1))
        with mock.patch.object(inventory, "deduct_for_sale", side_effect=RuntimeError("TEST crash")):
            with self.assertRaises(RuntimeError):
                self.make(cart)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bill").fetchone()[0], 0)
        self.assertEqual(inventory.get_product(self.conn, self.soap)["stock"], 10)

    def test_validation_errors_write_nothing(self):
        cart = cart_with(self.conn, (self.soap, 1))
        bad = [dict(name="", phone="9876543210"), dict(name="TEST", phone="12345")]
        for cust in bad:
            with self.assertRaises(BillingError):
                invoices.create_invoice(self.conn, cart.lines, cust, "27", "Cash")
        with self.assertRaises(BillingError):
            self.make(cart, mode="Cash", tendered="1")
        with self.assertRaises(BillingError):
            invoices.create_invoice(self.conn, [], dict(fx.TEST_CUSTOMER), "27", "Cash")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bill").fetchone()[0], 0)

    def test_historical_invoice_keeps_original_values(self):
        bill = self.make(cart_with(self.conn, (self.soap, 1)))
        before = invoices.get_invoice(self.conn, bill)
        p = inventory.get_product(self.conn, self.soap)
        inventory.update_product(self.conn, self.soap, dict(p, mrp="200", gst_rate="40"))
        after = invoices.get_invoice(self.conn, bill)
        self.assertEqual(before["grand_total"], after["grand_total"])
        self.assertEqual(after["items"][0]["gst_rate"], D("18"))
        self.assertEqual(after["items"][0]["unit_price"], D("118.00"))

    def test_cancel_restores_stock_and_keeps_record(self):
        bill = self.make(cart_with(self.conn, (self.soap, 4)))
        invoices.cancel_invoice(self.conn, bill, "TESTER", "TEST wrong item")
        inv = invoices.get_invoice(self.conn, bill)
        self.assertEqual(inv["status"], "CANCELLED")
        self.assertEqual(inventory.get_product(self.conn, self.soap)["stock"], 10)
        with self.assertRaises(BillingError):
            invoices.cancel_invoice(self.conn, bill, "TESTER", "again")

    def test_search(self):
        bill = self.make(cart_with(self.conn, (self.soap, 1)))
        self.assertEqual([r["bill_no"] for r in invoices.search_invoices(self.conn, bill)], [bill])
        self.assertEqual(len(invoices.search_invoices(self.conn, "9876543210")), 1)
        self.assertEqual(invoices.search_invoices(self.conn, "nomatch"), [])
        self.assertIsNone(invoices.get_invoice(self.conn, "NOPE"))

    def test_customer_registration_and_history(self):
        cart = cart_with(self.conn, (self.soap, 1))
        invoices.create_invoice(self.conn, cart.lines, dict(fx.TEST_CUSTOMER, save=True), "27",
                                "Card", None, "4321", "TESTER")
        c = people.find_customer_by_phone(self.conn, fx.TEST_CUSTOMER["phone"])
        self.assertIsNotNone(c)
        hist = people.customer_history(self.conn, c["customer_id"])
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["payment_mode"], "Card")


class InventoryTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.cm = db.connect()
        self.conn = self.cm.__enter__()
        fx.setup_store(self.conn)

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        super().tearDown()

    def test_product_validation(self):
        base = {"product_name": "TEST x", "product_cat": "c", "product_subcat": "s", "stock": "1",
                "mrp": "10", "cost_price": "5", "gst_rate": "5", "vendor_phn": "9000000000"}
        for k, v in [("mrp", "abc"), ("mrp", "0"), ("gst_rate", ""), ("gst_rate", "120"),
                     ("stock", "-3"), ("vendor_phn", "123"), ("product_name", " ")]:
            with self.assertRaises(people.ValidationError, msg=(k, v)):
                inventory.add_product(self.conn, dict(base, **{k: v}))

    def test_adjustments_and_movement_history(self):
        pid = fx.add_product(self.conn, "pen", "10", "12", 3)
        inventory.adjust_stock(self.conn, pid, 7, "PURCHASE", "TEST delivery", "TESTER")
        inventory.adjust_stock(self.conn, pid, -1, "DAMAGE", "", "TESTER")
        with self.assertRaises(inventory.StockError):
            inventory.adjust_stock(self.conn, pid, -100, "CORRECTION", "TEST")
        with self.assertRaises(people.ValidationError):
            inventory.adjust_stock(self.conn, pid, 5, "DAMAGE", "")
        self.assertEqual(inventory.get_product(self.conn, pid)["stock"], 9)
        types = [m["movement_type"] for m in inventory.movements(self.conn, pid)]
        self.assertEqual(types, ["DAMAGE", "PURCHASE", "OPENING"])

    def test_low_stock(self):
        a = fx.add_product(self.conn, "low", "10", "5", 2)
        fx.add_product(self.conn, "ok", "10", "5", 50)
        c = fx.add_product(self.conn, "custom", "10", "5", 15, reorder="20")
        self.assertEqual({p["product_id"] for p in inventory.low_stock(self.conn)}, {a, c})

    def test_delete_keeps_invoice_history(self):
        pid = fx.add_product(self.conn, "gone", "50", "5", 5)
        bill = invoices.create_invoice(self.conn, cart_with(self.conn, (pid, 1)).lines,
                                       dict(fx.TEST_CUSTOMER), "27", "Cash")
        inventory.delete_products(self.conn, [pid])
        inv = invoices.get_invoice(self.conn, bill)
        self.assertEqual(inv["items"][0]["product_name"], "TEST gone")
        self.assertIsNone(inv["items"][0]["product_id"])
        invoices.cancel_invoice(self.conn, bill, "TESTER", "TEST")  # must not crash


class PeopleTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.cm = db.connect()
        self.conn = self.cm.__enter__()

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        super().tearDown()

    def test_first_admin_only_once_and_hashed(self):
        fx.add_admin(self.conn)
        row = self.conn.execute("SELECT password FROM employee WHERE emp_id='EMP0000'").fetchone()
        self.assertTrue(security.is_hashed(row[0]))
        self.assertNotIn("testpass1", row[0])
        with self.assertRaises(people.ValidationError):
            people.create_first_admin(self.conn, "TEST other", "anotherpass")

    def test_login_and_wrong_password(self):
        fx.add_admin(self.conn)
        self.assertEqual(people.authenticate(self.conn, "EMP0000", "testpass1")["designation"], "Admin")
        self.assertIsNone(people.authenticate(self.conn, "EMP0000", "wrong"))
        self.assertIsNone(people.authenticate(self.conn, "EMP9999", "testpass1"))

    def test_legacy_plaintext_password_is_rehashed_on_login(self):
        with db.transaction(self.conn):
            self.conn.execute("INSERT INTO employee VALUES ('EMP1234','TEST legacy','9000000000',"
                              "'TEST addr','234567890123','oldplain','Cashier')")
        self.assertIsNone(people.authenticate(self.conn, "EMP1234", "bad"))
        self.assertEqual(self.conn.execute("SELECT password FROM employee WHERE emp_id='EMP1234'")
                         .fetchone()[0], "oldplain")  # unchanged after a failed login
        self.assertIsNotNone(people.authenticate(self.conn, "EMP1234", "oldplain"))
        stored = self.conn.execute("SELECT password FROM employee WHERE emp_id='EMP1234'").fetchone()[0]
        self.assertTrue(security.is_hashed(stored))
        self.assertIsNotNone(people.authenticate(self.conn, "EMP1234", "oldplain"))

    def test_employee_crud_masks_private_data(self):
        fx.add_admin(self.conn)
        emp = people.add_employee(self.conn, dict(name="TEST cashier", contact_num="6123456789",
                                                  aadhar_num="234567890123", designation="cashier",
                                                  address="TEST", password="secret12"))
        self.assertRegex(emp, r"^EMP\d{4}$")
        listed = people.get_employee(self.conn, emp)
        self.assertNotIn("password", listed)
        self.assertEqual(listed["aadhar_num"], "XXXX-XXXX-0123")
        people.update_employee(self.conn, emp, dict(name="TEST cashier 2", contact_num="6123456789",
                                                    aadhar_num="", designation="Cashier",
                                                    address="TEST", password=""))
        self.assertIsNotNone(people.authenticate(self.conn, emp, "secret12"))  # password kept
        raw = self.conn.execute("SELECT aadhar_num FROM employee WHERE emp_id=?", (emp,)).fetchone()[0]
        self.assertEqual(raw, "234567890123")  # Aadhaar kept

    def test_delete_protects_master_admin_before_deleting_anything(self):
        fx.add_admin(self.conn)
        emp = people.add_employee(self.conn, dict(name="TEST a", contact_num="6123456789",
                                                  aadhar_num="234567890123", designation="Cashier",
                                                  address="TEST", password="secret12"))
        with self.assertRaises(people.ValidationError):
            people.delete_employees(self.conn, [emp, "EMP0000"])
        self.assertIsNotNone(people.get_employee(self.conn, emp))

    def test_roles(self):
        self.assertTrue(security.can("Admin", "employees"))
        self.assertFalse(security.can("Manager", "employees"))
        self.assertTrue(security.can("Manager", "inventory"))
        self.assertEqual(security.permissions_for("Cashier"), {"billing"})
        self.assertFalse(security.can("cashier", "admin_panel"))

    def test_validators(self):
        self.assertTrue(security.valid_phone("6000000000"))
        self.assertFalse(security.valid_phone("5000000000"))
        self.assertEqual(security.mask_aadhaar("234567890123"), "XXXX-XXXX-0123")
        self.assertTrue(security.valid_gstin("27AAPFU0939F1ZV"))
        self.assertFalse(security.valid_gstin("27AAPFU0939F1Z"))
