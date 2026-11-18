"""Optional DEMONSTRATION catalogue for Billwise.

* Every product is flagged ``is_demo = 1`` and has a ``DEMO-`` SKU.
* Prices are round PLACEHOLDER values chosen for demonstration - they are NOT
  market prices. GST rates are illustrative and must be verified before real
  use. No barcodes are included.
* Brand names are used only to describe everyday products; Billwise is not
  affiliated with any brand or retailer.

Load / remove from Administration > Settings, or from the command line:
    python demo_catalogue.py --load
    python demo_catalogue.py --remove
"""
import sys

import db
import inventory

DEMO_STOCK = 40
LOW_STOCK_DEMO = {"DEMO-DRY-002", "DEMO-SNK-004", "DEMO-HOM-003"}  # show low-stock alerts

# sku, brand, product, pack, category, sub-category, MRP*, cost*, GST %*   (* placeholders)
CATALOGUE = [
    ("DEMO-STP-001", "Aashirvaad", "Whole Wheat Atta", "5 kg", "Staples", "Atta & Flours", "300", "255", "5"),
    ("DEMO-STP-002", "Fortune", "Chakki Fresh Atta", "10 kg", "Staples", "Atta & Flours", "550", "470", "5"),
    ("DEMO-STP-003", "India Gate", "Basmati Rice Classic", "1 kg", "Staples", "Rice", "200", "165", "5"),
    ("DEMO-STP-004", "Daawat", "Rozana Basmati Rice", "5 kg", "Staples", "Rice", "500", "420", "5"),
    ("DEMO-STP-005", "Tata Sampann", "Toor Dal Unpolished", "1 kg", "Staples", "Pulses", "180", "150", "5"),
    ("DEMO-STP-006", "Tata Sampann", "Moong Dal", "500 g", "Staples", "Pulses", "90", "75", "5"),
    ("DEMO-STP-007", "Fortune", "Refined Sunflower Oil", "1 L", "Staples", "Edible Oil", "160", "138", "5"),
    ("DEMO-STP-008", "Saffola", "Gold Blended Oil", "1 L", "Staples", "Edible Oil", "190", "162", "5"),
    ("DEMO-STP-009", "Tata Salt", "Iodised Salt", "1 kg", "Staples", "Salt & Sugar", "30", "24", "0"),
    ("DEMO-STP-010", "Madhur", "Pure Sugar", "1 kg", "Staples", "Salt & Sugar", "55", "47", "5"),
    ("DEMO-STP-011", "Everest", "Turmeric Powder", "200 g", "Staples", "Spices", "70", "58", "5"),
    ("DEMO-STP-012", "MDH", "Garam Masala", "100 g", "Staples", "Spices", "90", "74", "5"),
    ("DEMO-DRY-001", "Amul", "Taaza Toned Milk", "1 L", "Dairy", "Milk", "70", "64", "0"),
    ("DEMO-DRY-002", "Mother Dairy", "Full Cream Milk", "500 ml", "Dairy", "Milk", "35", "32", "0"),
    ("DEMO-DRY-003", "Amul", "Pasteurised Butter", "100 g", "Dairy", "Butter & Ghee", "60", "53", "5"),
    ("DEMO-DRY-004", "Amul", "Pure Ghee", "1 L", "Dairy", "Butter & Ghee", "650", "575", "5"),
    ("DEMO-DRY-005", "Amul", "Fresh Paneer", "200 g", "Dairy", "Curd & Paneer", "90", "80", "0"),
    ("DEMO-DRY-006", "Mother Dairy", "Classic Dahi", "400 g", "Dairy", "Curd & Paneer", "50", "44", "5"),
    ("DEMO-DRY-007", "Amul", "Cheese Slices", "200 g", "Dairy", "Cheese", "150", "130", "5"),
    ("DEMO-SNK-001", "Parle", "Parle-G Gold Biscuits", "1 kg", "Snacks", "Biscuits", "150", "128", "5"),
    ("DEMO-SNK-002", "Britannia", "Good Day Cashew Cookies", "250 g", "Snacks", "Biscuits", "60", "51", "5"),
    ("DEMO-SNK-003", "Sunfeast", "Dark Fantasy Choco Fills", "300 g", "Snacks", "Biscuits", "160", "136", "5"),
    ("DEMO-SNK-004", "Haldiram's", "Aloo Bhujia", "400 g", "Snacks", "Namkeen", "110", "93", "5"),
    ("DEMO-SNK-005", "Bikaji", "Bikaneri Bhujia", "400 g", "Snacks", "Namkeen", "100", "85", "5"),
    ("DEMO-SNK-006", "Lay's", "Classic Salted Chips", "90 g", "Snacks", "Chips", "40", "34", "5"),
    ("DEMO-SNK-007", "Cadbury", "Dairy Milk Silk", "150 g", "Snacks", "Chocolates", "180", "155", "5"),
    ("DEMO-SNK-008", "Nestle", "KitKat 4 Finger", "37 g", "Snacks", "Chocolates", "30", "25", "5"),
    ("DEMO-BEV-001", "Tata Tea", "Premium Leaf Tea", "1 kg", "Beverages", "Tea & Coffee", "500", "430", "5"),
    ("DEMO-BEV-002", "Red Label", "Natural Care Tea", "500 g", "Beverages", "Tea & Coffee", "280", "240", "5"),
    ("DEMO-BEV-003", "Bru", "Instant Coffee", "100 g", "Beverages", "Tea & Coffee", "250", "215", "5"),
    ("DEMO-BEV-004", "Real", "Mixed Fruit Juice", "1 L", "Beverages", "Juices", "120", "102", "5"),
    ("DEMO-BEV-005", "Thums Up", "Soft Drink", "750 ml", "Beverages", "Soft Drinks", "45", "37", "40"),
    ("DEMO-BEV-006", "Bisleri", "Packaged Drinking Water", "1 L", "Beverages", "Water", "20", "15", "5"),
    ("DEMO-BRK-001", "Kellogg's", "Corn Flakes Original", "475 g", "Breakfast", "Cereals", "200", "170", "5"),
    ("DEMO-BRK-002", "Quaker", "Oats", "1 kg", "Breakfast", "Cereals", "200", "172", "5"),
    ("DEMO-BRK-003", "Maggi", "2-Minute Masala Noodles", "280 g (4 pack)", "Breakfast", "Noodles & Pasta", "60", "51", "5"),
    ("DEMO-BRK-004", "Kissan", "Mixed Fruit Jam", "500 g", "Breakfast", "Spreads", "160", "137", "5"),
    ("DEMO-PER-001", "Lux", "Soft Touch Soap (3 x 100 g)", "300 g", "Personal Care", "Bath & Body", "120", "100", "5"),
    ("DEMO-PER-002", "Dove", "Cream Beauty Bathing Bar", "100 g", "Personal Care", "Bath & Body", "60", "50", "5"),
    ("DEMO-PER-003", "Clinic Plus", "Strength & Shine Shampoo", "340 ml", "Personal Care", "Hair Care", "200", "168", "5"),
    ("DEMO-PER-004", "Parachute", "Coconut Oil", "500 ml", "Personal Care", "Hair Care", "220", "188", "5"),
    ("DEMO-PER-005", "Colgate", "Strong Teeth Toothpaste", "200 g", "Personal Care", "Oral Care", "110", "93", "5"),
    ("DEMO-PER-006", "Oral-B", "Pro-Health Toothbrush", "1 pc", "Personal Care", "Oral Care", "50", "41", "5"),
    ("DEMO-HOM-001", "Surf Excel", "Easy Wash Detergent Powder", "1 kg", "Home Care", "Laundry", "140", "116", "18"),
    ("DEMO-HOM-002", "Tide", "Plus Detergent Powder", "2 kg", "Home Care", "Laundry", "250", "207", "18"),
    ("DEMO-HOM-003", "Vim", "Dishwash Liquid Gel", "750 ml", "Home Care", "Dishwash", "170", "141", "18"),
    ("DEMO-HOM-004", "Lizol", "Floor Cleaner Citrus", "975 ml", "Home Care", "Cleaners", "230", "190", "18"),
    ("DEMO-HOM-005", "Harpic", "Toilet Cleaner", "1 L", "Home Care", "Cleaners", "200", "166", "18"),
    ("DEMO-BAB-001", "Pampers", "Baby Diaper Pants (M)", "20 pcs", "Baby Care", "Diapers", "400", "340", "5"),
    ("DEMO-BAB-002", "Himalaya", "Gentle Baby Wipes", "72 pcs", "Baby Care", "Wipes", "150", "126", "5"),
    ("DEMO-STN-001", "Classmate", "Single Line Notebook", "172 pages", "Stationery", "Notebooks", "60", "48", "0"),
    ("DEMO-STN-002", "Reynolds", "Trimax Gel Pen (Blue)", "1 pc", "Stationery", "Pens", "40", "32", "18"),
    ("DEMO-STP-013", "Rajdhani", "Besan", "500 g", "Staples", "Atta & Flours", "70", "59", "5"),
    ("DEMO-STP-014", "Tata Sampann", "Chana Dal", "1 kg", "Staples", "Pulses", "120", "101", "5"),
    ("DEMO-STP-015", "Fortune", "Kachi Ghani Mustard Oil", "1 L", "Staples", "Edible Oil", "180", "154", "5"),
    ("DEMO-STP-016", "Catch", "Red Chilli Powder", "200 g", "Staples", "Spices", "80", "66", "5"),
    ("DEMO-DRY-008", "Amul", "Masti Buttermilk", "500 ml", "Dairy", "Milk", "30", "26", "0"),
    ("DEMO-SNK-009", "Kurkure", "Masala Munch", "90 g", "Snacks", "Chips", "20", "17", "5"),
    ("DEMO-SNK-010", "Britannia", "Marie Gold", "250 g", "Snacks", "Biscuits", "40", "34", "5"),
    ("DEMO-BEV-007", "Cadbury", "Bournvita Health Drink", "500 g", "Beverages", "Health Drinks", "250", "214", "5"),
    ("DEMO-BEV-008", "Tropicana", "Orange Delight Juice", "1 L", "Beverages", "Juices", "130", "110", "5"),
    ("DEMO-BRK-005", "Saffola", "Masala Oats", "500 g", "Breakfast", "Cereals", "190", "162", "5"),
    ("DEMO-BRK-006", "Yippee", "Magic Masala Noodles", "240 g (4 pack)", "Breakfast", "Noodles & Pasta", "60", "51", "5"),
    ("DEMO-FRZ-001", "McCain", "French Fries", "420 g", "Frozen", "Frozen Snacks", "140", "118", "5"),
    ("DEMO-FRZ-002", "Amul", "Vanilla Ice Cream Tub", "1 L", "Frozen", "Ice Cream", "200", "168", "5"),
    ("DEMO-FRZ-003", "Safal", "Frozen Green Peas", "500 g", "Frozen", "Frozen Vegetables", "100", "84", "5"),
    ("DEMO-PER-007", "Nivea", "Soft Light Moisturising Cream", "100 ml", "Personal Care", "Skin Care", "200", "168", "5"),
    ("DEMO-PER-008", "Gillette", "Guard Razor", "1 pc", "Personal Care", "Shaving", "50", "41", "5"),
    ("DEMO-PER-009", "Dettol", "Original Handwash Refill", "750 ml", "Personal Care", "Bath & Body", "130", "108", "5"),
    ("DEMO-HLT-001", "Dabur", "Chyawanprash", "500 g", "Health & Wellness", "Ayurveda", "220", "186", "5"),
    ("DEMO-HLT-002", "Dabur", "Honey", "500 g", "Health & Wellness", "Honey & Spreads", "230", "195", "5"),
    ("DEMO-HOM-006", "Scotch-Brite", "Scrub Pad (Pack of 3)", "3 pcs", "Home Care", "Dishwash", "60", "49", "18"),
    ("DEMO-HOM-007", "Good Knight", "Gold Flash Refill", "45 ml", "Home Care", "Repellents", "90", "74", "18"),
    ("DEMO-HOM-008", "Odonil", "Room Freshener Blocks", "4 x 50 g", "Home Care", "Fresheners", "200", "166", "18"),
]


def demo_count(conn):
    return conn.execute("SELECT COUNT(*) FROM raw_inventory WHERE is_demo = 1").fetchone()[0]


def load(conn, user=""):
    """Add the catalogue (skips SKUs that already exist). Returns rows added."""
    added = 0
    with db.transaction(conn):
        for sku, brand, name, pack, cat, sub, mrp, cost, rate in CATALOGUE:
            if conn.execute("SELECT 1 FROM raw_inventory WHERE sku = ?", (sku,)).fetchone():
                continue
            inventory.add_product(conn, {
                "product_name": "%s %s %s" % (brand, name, pack), "brand": brand, "pack_size": pack,
                "product_cat": cat, "product_subcat": sub, "sku": sku, "mrp": mrp,
                "cost_price": cost, "gst_rate": rate, "hsn_code": "", "vendor_phn": "",
                "reorder_level": "",
                "stock": str(4 if sku in LOW_STOCK_DEMO else DEMO_STOCK), "is_demo": 1}, user)
            added += 1
    return added


def remove(conn):
    """Delete demo products and their demo opening-stock entries.

    Invoices are never touched: any invoice that sold a demo product keeps its
    stored lines (the product name and amounts are saved on the invoice)."""
    with db.transaction(conn):
        ids = [r[0] for r in conn.execute("SELECT product_id FROM raw_inventory WHERE is_demo = 1")]
        for pid in ids:
            conn.execute("DELETE FROM stock_movement WHERE product_id = ? AND movement_type = 'OPENING' "
                         "AND note = 'DEMO catalogue'", (pid,))
        conn.execute("DELETE FROM raw_inventory WHERE is_demo = 1")
    return len(ids)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("--load", "--remove"):
        print(__doc__)
        sys.exit(1)
    db.init_db()
    with db.connect() as c:
        if sys.argv[1] == "--load":
            print("Added %d demo products." % load(c, "DEMO"))
        else:
            print("Removed %d demo products." % remove(c))
