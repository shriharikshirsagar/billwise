"""Clearly labelled TEST fixtures (not real products, people or invoices)."""
import db
import inventory
import people

TEST_STORE_STATE = "27"  # Maharashtra
OTHER_STATE = "29"       # Karnataka


def setup_store(conn, state=TEST_STORE_STATE):
    db.set_settings(conn, {"store_name": "TEST STORE (fixture)", "store_state_code": state,
                           "store_gstin": "", "low_stock_threshold": "5"})


def add_product(conn, name, mrp, rate, stock, cost="0", reorder=""):
    return inventory.add_product(conn, {
        "product_name": "TEST " + name, "product_cat": "TEST cat", "product_subcat": "TEST sub",
        "stock": str(stock), "mrp": str(mrp), "cost_price": str(cost), "gst_rate": str(rate),
        "vendor_phn": "9000000000", "hsn_code": "", "reorder_level": str(reorder)}, user="TESTER")


def add_admin(conn, password="testpass1"):
    return people.create_first_admin(conn, "TEST Admin", password)


TEST_CUSTOMER = {"name": "TEST Customer", "phone": "9876543210"}
