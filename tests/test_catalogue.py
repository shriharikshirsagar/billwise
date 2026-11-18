import db
import demo_catalogue
import inventory
import invoices
from people import ValidationError
from tests import fixtures as fx
from tests.helpers import TempDBTestCase
from tests.test_services import cart_with


class DemoCatalogueTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        self.cm = db.connect()
        self.conn = self.cm.__enter__()
        fx.setup_store(self.conn)

    def tearDown(self):
        self.cm.__exit__(None, None, None)
        super().tearDown()

    def test_catalogue_definition_is_clean(self):
        skus = [row[0] for row in demo_catalogue.CATALOGUE]
        self.assertEqual(len(skus), len(set(skus)))
        self.assertTrue(all(s.startswith("DEMO-") for s in skus))
        rates = {row[8] for row in demo_catalogue.CATALOGUE}
        self.assertGreater(len(rates), 2)  # per-product rates, not one global rate

    def test_load_is_flagged_idempotent_and_removable(self):
        n = demo_catalogue.load(self.conn, "TESTER")
        self.assertEqual(n, len(demo_catalogue.CATALOGUE))
        self.assertEqual(demo_catalogue.load(self.conn, "TESTER"), 0)  # no duplicates
        rows = inventory.list_products(self.conn)
        self.assertTrue(all(r["is_demo"] == 1 for r in rows))
        self.assertTrue(all(r["gst_rate"] not in (None, "") for r in rows))
        self.assertTrue(inventory.low_stock(self.conn))  # some items demonstrate alerts
        real = fx.add_product(self.conn, "real item", "10", "5", 3)
        self.assertEqual(demo_catalogue.remove(self.conn), n)
        left = inventory.list_products(self.conn)
        self.assertEqual([p["product_id"] for p in left], [real])
        demo_moves = self.conn.execute("SELECT COUNT(*) FROM stock_movement WHERE note='DEMO catalogue'")
        self.assertEqual(demo_moves.fetchone()[0], 0)

    def test_removing_demo_keeps_invoices_that_sold_demo_items(self):
        demo_catalogue.load(self.conn, "TESTER")
        pid = inventory.search_products(self.conn, "DEMO-STP-001")[0]["product_id"]
        bill = invoices.create_invoice(self.conn, cart_with(self.conn, (pid, 1)).lines,
                                       dict(fx.TEST_CUSTOMER), "27", "Cash")
        before = invoices.get_invoice(self.conn, bill)
        demo_catalogue.remove(self.conn)
        after = invoices.get_invoice(self.conn, bill)
        self.assertEqual(after["grand_total"], before["grand_total"])
        self.assertEqual(after["items"][0]["product_name"], before["items"][0]["product_name"])
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_search_by_name_brand_and_sku(self):
        demo_catalogue.load(self.conn, "TESTER")
        self.assertTrue(inventory.search_products(self.conn, "atta"))
        self.assertTrue(inventory.search_products(self.conn, "Amul"))
        self.assertEqual(len(inventory.search_products(self.conn, "demo-bev-003")), 1)
        self.assertEqual(inventory.search_products(self.conn, "zzzz-nothing"), [])
        self.assertEqual(inventory.search_products(self.conn, "  "), [])

    def test_sku_must_be_unique(self):
        base = {"product_name": "TEST x", "product_cat": "c", "product_subcat": "s", "stock": "1",
                "mrp": "10", "cost_price": "5", "gst_rate": "5", "sku": "TEST-1"}
        a = inventory.add_product(self.conn, base)
        with self.assertRaises(ValidationError):
            inventory.add_product(self.conn, dict(base, product_name="TEST y"))
        b = inventory.add_product(self.conn, dict(base, product_name="TEST y", sku="TEST-2"))
        p = inventory.get_product(self.conn, b)
        with self.assertRaises(ValidationError):
            inventory.update_product(self.conn, b, dict(p, sku="TEST-1"))
        inventory.update_product(self.conn, a, dict(inventory.get_product(self.conn, a), sku="test-1"))
        self.assertEqual(inventory.get_product(self.conn, a)["sku"], "TEST-1")
