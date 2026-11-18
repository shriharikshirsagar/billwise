import os
from datetime import datetime
from decimal import Decimal as D

import pandas as pd

import db
import invoices
import reports
from tests import fixtures as fx
from tests.helpers import TempDBTestCase
from tests.test_services import cart_with


class ReportTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.cm = db.connect()
        self.conn = self.cm.__enter__()
        fx.setup_store(self.conn)
        self.a = fx.add_product(self.conn, "A", "118", "18", 50, cost="70")
        self.b = fx.add_product(self.conn, "B", "105", "5", 4, cost="60")
        day1, day2 = datetime(2026, 11, 1, 10), datetime(2026, 11, 2, 10)
        mk = lambda items, when, st="27": invoices.create_invoice(  # noqa: E731
            self.conn, cart_with(self.conn, *items).lines, dict(fx.TEST_CUSTOMER), st, "UPI",
            None, "", "TESTER", when)
        self.b1 = mk([(self.a, 2)], day1)                 # 236.00
        self.b2 = mk([(self.a, 1), (self.b, 1)], day2, "29")  # 223.00 inter
        self.b3 = mk([(self.b, 1)], day2)                 # cancelled below
        invoices.cancel_invoice(self.conn, self.b3, "TESTER", "TEST")
        with db.transaction(self.conn):
            self.conn.execute("INSERT INTO bill(bill_no, date, customer_name, customer_no, bill_details) "
                              "VALUES ('TESTOLD1','2026-11-02','TEST old','9000000000',?)",
                              ("TEST A\t\t\t3\t\t\t354.0\nbroken line\tParle Products\tx\n"
                               "───\nTotal\t\t\tRs. 354.0",))

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        super().tearDown()

    def test_daily_sales_excludes_cancelled_and_counts_legacy(self):
        df = reports.sales_by_day(self.conn, "2026-11-01", "2026-11-30")
        self.assertEqual(list(df["Date"]), ["2026-11-01", "2026-11-02"])
        self.assertEqual(list(df["Invoices"]), [1, 2])
        self.assertEqual(list(df["Sales"]), [D("236.00"), D("223.00") + D("354.0")])

    def test_monthly(self):
        df = reports.sales_by_month(self.conn, 2026)
        self.assertEqual(len(df), 12)
        self.assertEqual(df.loc[df["Month"] == "2026-11", "Invoices"].iloc[0], 3)

    def test_profit(self):
        p = reports.profit_summary(self.conn, "2026-11-01", "2026-11-30")
        # taxable: A 3 x 100 = 300, B 1 x 100 = 100 ; cost 3x70 + 60 = 270
        self.assertEqual((p["revenue"], p["cost"], p["gross_profit"]),
                         (D("400.00"), D("270.00"), D("130.00")))

    def test_best_sellers_include_legacy_quantities_and_skip_bad_lines(self):
        df = reports.best_sellers(self.conn, "2026-11-01", "2026-11-30")
        self.assertEqual(df.iloc[0]["Product"], "TEST A")
        self.assertEqual(df.iloc[0]["Qty sold"], 6)  # 3 new + 3 legacy
        self.assertEqual(reports.parse_legacy_details("x\tParle Products\ty"), [])

    def test_gst_summary(self):
        df = reports.gst_summary(self.conn, "2026-11-01", "2026-11-30")
        intra18 = df[(df["GST %"] == "18") & (df["Supply"] == "Intra-state")].iloc[0]
        self.assertEqual((intra18["CGST"], intra18["SGST"]), (D("18.00"), D("18.00")))
        inter = df[df["Supply"] == "Inter-state"]
        self.assertEqual(sum(inter["IGST"], D(0)), D("23.00"))

    def test_inventory_valuation_and_low_stock(self):
        v = reports.inventory_valuation(self.conn)
        row = v[v["Product"] == "TEST B"].iloc[0]
        self.assertEqual(row["Stock"], 3)  # 4 - 1 sold (cancelled one restored)
        self.assertEqual(row["Stock value (cost)"], D("180.00"))
        self.assertEqual(row["Low stock"], "YES")
        self.assertEqual(list(reports.low_stock_report(self.conn)["Product"]), ["TEST B"])

    def test_register_masks_phone(self):
        df = reports.invoice_register(self.conn, "2026-11-01", "2026-11-30")
        self.assertTrue(all("XXXX" in p for p in df["Phone"]))
        self.assertIn("CANCELLED", list(df["Status"]))

    def test_exports(self):
        xl = os.path.join(self.tmp, "r.xlsx")
        sheets = {name: fn(self.conn, "2026-11-01", "2026-11-30")
                  for name, fn in reports.REPORTS.items()}
        reports.export_excel(sheets, xl)
        back = pd.read_excel(xl, sheet_name="GST summary")
        self.assertAlmostEqual(float(back["Total GST"].sum()), 59.00, places=2)
        with pd.ExcelFile(xl) as book:
            self.assertEqual(set(book.sheet_names), set(sheets))
        for name, df in sheets.items():
            self.assertNotIn("password", " ".join(df.columns).lower())
            self.assertNotIn("aadhar", " ".join(df.columns).lower())
        pdf = reports.export_pdf("GST summary", sheets["GST summary"], os.path.join(self.tmp, "g.pdf"))
        self.assertGreater(os.path.getsize(pdf), 1000)
        empty = reports.export_pdf("Empty", reports.gst_summary(self.conn, "2000-01-01", "2000-01-02"),
                                   os.path.join(self.tmp, "e.pdf"))
        self.assertTrue(os.path.exists(empty))
