import random
import unittest
from decimal import Decimal as D

from tests import helpers  # noqa: F401  (sets sys.path)
import billing
from billing import BillingError, Cart, CartLine, INTER, INTRA, calculate_invoice


class LineMathTests(unittest.TestCase):
    def test_inclusive_gst_intra(self):
        r = billing.calculate_line(CartLine(1, "TEST", D("118.00"), D("18"), 1), INTRA)
        self.assertEqual((r.taxable, r.cgst, r.sgst, r.igst, r.line_total),
                         (D("100.00"), D("9.00"), D("9.00"), D("0.00"), D("118.00")))

    def test_inclusive_gst_inter(self):
        r = billing.calculate_line(CartLine(1, "TEST", D("118.00"), D("18"), 2), INTER)
        self.assertEqual((r.taxable, r.igst, r.cgst, r.line_total),
                         (D("200.00"), D("36.00"), D("0.00"), D("236.00")))

    def test_odd_paisa_split(self):
        r = billing.calculate_line(CartLine(1, "TEST", D("10.50"), D("5"), 1), INTRA)
        self.assertEqual(r.cgst + r.sgst + r.taxable, r.line_total)
        self.assertLessEqual(abs(r.cgst - r.sgst), D("0.01"))
        self.assertEqual(r.tax, D("0.50"))

    def test_discount_then_tax(self):
        r = billing.calculate_line(CartLine(1, "TEST", D("100"), D("12"), 3, D("10")), INTRA)
        self.assertEqual((r.gross, r.discount, r.line_total), (D("300.00"), D("30.00"), D("270.00")))
        self.assertEqual(r.tax, D("28.93"))  # 270*12/112 = 28.928...
        self.assertEqual(r.taxable + r.tax, D("270.00"))

    def test_zero_rate(self):
        r = billing.calculate_line(CartLine(1, "TEST", D("50"), D("0"), 2), INTRA)
        self.assertEqual((r.taxable, r.tax), (D("100.00"), D("0.00")))

    def test_rates_are_per_product_not_global(self):
        t = calculate_invoice([CartLine(1, "A", D("105"), D("5"), 1),
                               CartLine(2, "B", D("128"), D("28"), 1),
                               CartLine(3, "C", D("100"), D("0"), 1)], INTRA)
        self.assertEqual([ln.gst_rate for ln in t.lines], [D("5"), D("28"), D("0")])
        self.assertEqual((t.taxable, t.tax), (D("300.00"), D("33.00")))
        self.assertEqual(set(t.gst_breakdown()), {D("0"), D("5"), D("28")})


class InvoiceTotalsTests(unittest.TestCase):
    def test_round_off_to_rupee(self):
        t = calculate_invoice([CartLine(1, "A", D("10.49"), D("5"), 1),
                               CartLine(2, "B", D("20.00"), D("18"), 1)], INTRA)
        self.assertEqual((t.net, t.grand_total, t.round_off), (D("30.49"), D("30.00"), D("-0.49")))
        t2 = calculate_invoice([CartLine(1, "A", D("10.50"), D("5"), 1)], INTRA)
        self.assertEqual((t2.grand_total, t2.round_off), (D("11.00"), D("0.50")))

    def test_invariants_random_invoices(self):
        rnd = random.Random(7)
        for _ in range(300):
            lines = [CartLine(i, "T", D(rnd.randint(1, 99999)) / 100,
                              D(rnd.choice(["0", "0.25", "3", "5", "12", "18", "28", "40"])),
                              rnd.randint(1, 20), D(rnd.randint(0, 30)))
                     for i in range(rnd.randint(1, 8))]
            for st in (INTRA, INTER):
                t = calculate_invoice(lines, st)
                self.assertEqual(t.taxable + t.tax, t.net)
                self.assertEqual(t.net + t.round_off, t.grand_total)
                self.assertEqual(t.grand_total, t.grand_total.to_integral())
                self.assertEqual(t.subtotal - t.discount, t.net)
                self.assertEqual(t.cgst + t.sgst if st == INTER else t.igst, 0)

    def test_empty_cart_rejected(self):
        with self.assertRaises(BillingError):
            calculate_invoice([], INTRA)

    def test_supply_type(self):
        self.assertEqual(billing.supply_type_for("27", "27"), INTRA)
        self.assertEqual(billing.supply_type_for("27", "29"), INTER)
        with self.assertRaises(BillingError):
            billing.supply_type_for("", "27")


class CartTests(unittest.TestCase):
    def test_same_product_aggregates(self):
        c = Cart()
        c.add(1, "TEST soap", "40", "18", 2, stock=10)
        c.add(1, "TEST soap", "40", "18", 3, stock=10)
        self.assertEqual((len(c.lines), c.quantities()), (1, {1: 5}))

    def test_cumulative_stock_check(self):
        c = Cart()
        c.add(1, "TEST", "10", "5", 5, stock=5)
        with self.assertRaises(BillingError):
            c.add(1, "TEST", "10", "5", 1, stock=5)
        self.assertEqual(c.quantities(), {1: 5})

    def test_invalid_quantities(self):
        c = Cart()
        for q in ("0", "-1", "abc", "1.5", ""):
            with self.assertRaises(BillingError, msg=q):
                c.add(1, "TEST", "10", "5", q, stock=100)
        self.assertTrue(c.is_empty())

    def test_missing_gst_rate_rejected(self):
        with self.assertRaises(BillingError):
            Cart().add(1, "TEST", "10", None, 1, stock=5)

    def test_remove_and_clear(self):
        c = Cart()
        c.add(1, "A", "10", "5", 1, stock=5)
        c.add(2, "B", "10", "5", 1, stock=5)
        c.remove(1)
        self.assertEqual(c.quantities(), {2: 1})
        c.clear()
        self.assertTrue(c.is_empty())
        c.add(3, "C", "10", "5", 1, stock=5)
        self.assertEqual(c.quantities(), {3: 1})  # nothing carried over between bills

    def test_carts_are_independent(self):
        a, b = Cart(), Cart()
        a.add(1, "A", "10", "5", 1, stock=5)
        self.assertTrue(b.is_empty())

    def test_no_float_drift(self):
        c = Cart()
        c.add(1, "A", "0.10", "0", 1, stock=5)
        c.add(2, "B", "0.20", "0", 1, stock=5)
        self.assertEqual(c.totals(INTRA).net, D("0.30"))


class PaymentTests(unittest.TestCase):
    def test_cash_change(self):
        self.assertEqual(billing.validate_payment("Cash", D("95.00"), "100"),
                         (D("100.00"), D("5.00"), ""))

    def test_cash_short(self):
        with self.assertRaises(BillingError):
            billing.validate_payment("Cash", D("95.00"), "90")

    def test_card_only_last4(self):
        self.assertEqual(billing.validate_payment("Card", D("10"), None, "1234")[2], "1234")
        with self.assertRaises(BillingError):
            billing.validate_payment("Card", D("10"), None, "4111111111111111")

    def test_upi_and_unknown(self):
        self.assertEqual(billing.validate_payment("UPI", D("10.00"), None, "TESTREF1")[2], "TESTREF1")
        with self.assertRaises(BillingError):
            billing.validate_payment("Cheque", D("10"))
