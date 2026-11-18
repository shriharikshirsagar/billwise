"""PDF accuracy: every amount printed on the PDF equals the stored value."""
import os

from pypdf import PdfReader

import db
import invoice_pdf
import invoices
from billing import fmt
from tests import fixtures as fx
from tests.helpers import TempDBTestCase
from tests.test_services import cart_with


def pdf_text(path):
    return "\n".join(p.extract_text() for p in PdfReader(path).pages)


class PdfAccuracyTests(TempDBTestCase):
    def _make(self, state, mode="Cash", ref=""):
        with db.connect() as conn:
            fx.setup_store(conn)
            a = fx.add_product(conn, "pdf item A", "99.99", "18", 20)
            b = fx.add_product(conn, "pdf item B", "45.50", "5", 20)
            c = fx.add_product(conn, "pdf item C", "250", "28", 20)
            cart = cart_with(conn, (a, 3, "10"), (b, 2), (c, 1, "5"))
            bill = invoices.create_invoice(conn, cart.lines, dict(fx.TEST_CUSTOMER), state, mode,
                                           "1000" if mode == "Cash" else None, ref, "TESTER")
            inv = invoices.get_invoice(conn, bill)
            path = invoice_pdf.generate_invoice_pdf(
                inv, invoice_pdf.store_details(conn), os.path.join(self.tmp, "%s.pdf" % bill))
        return inv, path

    def _assert_matches(self, inv, path):
        text = pdf_text(path)
        self.assertIn(inv["bill_no"], text)
        self.assertIn("billwise", text)
        self.assertIn(inv["customer_name"], text)
        checks = [("Subtotal (MRP)", inv["subtotal"]), ("Taxable amount", inv["taxable_total"]),
                  ("Total GST", inv["tax_total"]), ("Round off", inv["round_off"]),
                  ("TOTAL PAYABLE (Rs.)", inv["grand_total"])]
        if inv["supply_type"] == "INTRA":
            checks += [("CGST", inv["cgst_total"]), ("SGST", inv["sgst_total"])]
        else:
            checks += [("IGST", inv["igst_total"])]
        lines = [ln.strip() for ln in text.splitlines()]
        for label, value in checks:
            # ReportLab table cells are extracted one per line: label, then value.
            found = [lines[i + 1] for i, ln in enumerate(lines[:-1]) if ln == label]
            self.assertIn(fmt(value), found, "%s on PDF %s != DB %s" % (label, found, fmt(value)))
        for it in inv["items"]:
            self.assertIn(it["product_name"], text)
            self.assertIn(fmt(it["line_total"]), text)
            self.assertIn(fmt(it["taxable_amount"]), text)
        return text

    def test_intra_pdf_matches_db(self):
        inv, path = self._make(fx.TEST_STORE_STATE)
        text = self._assert_matches(inv, path)
        self.assertIn("Intra-state", text)
        self.assertIn("Cash received", text)

    def test_inter_pdf_matches_db(self):
        inv, path = self._make(fx.OTHER_STATE, mode="Card", ref="4321")
        text = self._assert_matches(inv, path)
        self.assertIn("Inter-state", text)
        self.assertIn("4321", text)
        self.assertNotIn("SGST", text.split("GST summary")[0].split("Amount")[0])

    def test_reprint_is_identical_in_values(self):
        inv, path = self._make(fx.TEST_STORE_STATE)
        first = pdf_text(path)
        with db.connect() as conn:
            again = invoices.get_invoice(conn, inv["bill_no"])
            path2 = invoice_pdf.generate_invoice_pdf(again, invoice_pdf.store_details(conn),
                                                     os.path.join(self.tmp, "reprint.pdf"))
        self.assertEqual(first, pdf_text(path2))

    def test_cancelled_and_legacy_render(self):
        inv, _ = self._make(fx.TEST_STORE_STATE)
        with db.connect() as conn:
            invoices.cancel_invoice(conn, inv["bill_no"], "TESTER", "TEST reason")
            c = invoices.get_invoice(conn, inv["bill_no"])
            p = invoice_pdf.generate_invoice_pdf(c, invoice_pdf.store_details(conn),
                                                 os.path.join(self.tmp, "c.pdf"))
            self.assertIn("CANCELLED", pdf_text(p))
            with db.transaction(conn):
                conn.execute("INSERT INTO bill(bill_no, date, customer_name, customer_no, bill_details) "
                             "VALUES ('TESTLEGACY','2025-05-01','TEST old','9000000000',"
                             "'TEST item\t2\t40.0\nTotal\tRs. 40.0')")
            legacy = invoices.get_invoice(conn, "TESTLEGACY")
            self.assertTrue(legacy["legacy"])
            p2 = invoice_pdf.generate_invoice_pdf(legacy, invoice_pdf.store_details(conn),
                                                  os.path.join(self.tmp, "l.pdf"))
            self.assertIn("TEST item", pdf_text(p2))
