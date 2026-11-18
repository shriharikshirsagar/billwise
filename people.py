"""Employees (with authentication), customers and suppliers."""
import secrets

import db
import security
from billing import BillingError

MASTER_ADMIN_ID = "EMP0000"


class ValidationError(BillingError):
    pass


def _clean(data, key):
    return str(data.get(key) or "").strip()


# ------------------------------------------------------------ employees
def employee_count(conn):
    return conn.execute("SELECT COUNT(*) FROM employee").fetchone()[0]


def create_first_admin(conn, name, password, settings=None):
    """One-time setup: only allowed while the employee table is empty."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("Enter the administrator's name.")
    err = security.validate_new_password(password)
    if err:
        raise ValidationError(err)
    with db.transaction(conn):
        if employee_count(conn):
            raise ValidationError("An administrator already exists.")
        conn.execute("INSERT INTO employee(emp_id, name, contact_num, address, aadhar_num, "
                     "password, designation) VALUES (?,?,?,?,?,?,?)",
                     (MASTER_ADMIN_ID, name, "", "", "", security.hash_password(password), "Admin"))
        if settings:
            db.set_settings(conn, settings)
    return MASTER_ADMIN_ID


def authenticate(conn, emp_id, password):
    """Return a dict of the employee's public fields, or None.

    A legacy plain-text password is upgraded to a salted hash on success.
    """
    emp_id = (emp_id or "").strip()
    row = conn.execute("SELECT * FROM employee WHERE emp_id = ?", (emp_id,)).fetchone()
    if row is None:
        security.verify_password(password or "", security.hash_password("x"))  # equal timing
        return None
    ok, needs_rehash = security.verify_password(password or "", row["password"])
    if not ok:
        return None
    if needs_rehash:
        with db.transaction(conn):
            conn.execute("UPDATE employee SET password = ? WHERE emp_id = ?",
                         (security.hash_password(password), emp_id))
    return {"emp_id": row["emp_id"], "name": row["name"], "designation": row["designation"]}


def change_password(conn, emp_id, old_password, new_password):
    if not authenticate(conn, emp_id, old_password):
        raise ValidationError("Current password is incorrect.")
    err = security.validate_new_password(new_password)
    if err:
        raise ValidationError(err)
    with db.transaction(conn):
        conn.execute("UPDATE employee SET password = ? WHERE emp_id = ?",
                     (security.hash_password(new_password), emp_id))


def new_employee_id(conn):
    for _ in range(1000):
        emp_id = "EMP%04d" % secrets.randbelow(10000)
        if emp_id == MASTER_ADMIN_ID:
            continue
        if not conn.execute("SELECT 1 FROM employee WHERE emp_id = ?", (emp_id,)).fetchone():
            return emp_id
    raise ValidationError("Could not allocate a free employee ID.")


def _validate_employee(data, new):
    name, phone = _clean(data, "name"), _clean(data, "contact_num")
    aadhaar, designation = _clean(data, "aadhar_num"), _clean(data, "designation")
    address, password = _clean(data, "address"), data.get("password") or ""
    if not name:
        raise ValidationError("Please enter employee name.")
    if not security.valid_phone(phone):
        raise ValidationError("Invalid phone number (10 digits, starting 6-9).")
    if (new or aadhaar) and not security.valid_aadhaar(aadhaar):
        raise ValidationError("Invalid Aadhaar number (12 digits).")
    if not designation or not designation.replace(" ", "").isalpha():
        raise ValidationError("Please enter a designation (letters only).")
    if not address:
        raise ValidationError("Please enter address.")
    if new or password:
        err = security.validate_new_password(password)
        if err:
            raise ValidationError(err)
    return name, phone, aadhaar, designation.title(), address, password


def add_employee(conn, data):
    name, phone, aadhaar, designation, address, password = _validate_employee(data, True)
    with db.transaction(conn):
        emp_id = new_employee_id(conn)
        conn.execute("INSERT INTO employee(emp_id, name, contact_num, address, aadhar_num, "
                     "password, designation) VALUES (?,?,?,?,?,?,?)",
                     (emp_id, name, phone, address, aadhaar,
                      security.hash_password(password), designation))
    return emp_id


def update_employee(conn, emp_id, data):
    """Blank password / Aadhaar mean 'keep the current value'."""
    name, phone, aadhaar, designation, address, password = _validate_employee(data, False)
    if emp_id == MASTER_ADMIN_ID and designation != "Admin":
        raise ValidationError("The master administrator must keep the Admin designation.")
    with db.transaction(conn):
        cur = conn.execute("UPDATE employee SET name=?, contact_num=?, address=?, designation=? "
                           "WHERE emp_id=?", (name, phone, address, designation, emp_id))
        if cur.rowcount != 1:
            raise ValidationError("Employee %s not found." % emp_id)
        if aadhaar:
            conn.execute("UPDATE employee SET aadhar_num=? WHERE emp_id=?", (aadhaar, emp_id))
        if password:
            conn.execute("UPDATE employee SET password=? WHERE emp_id=?",
                         (security.hash_password(password), emp_id))


def delete_employees(conn, emp_ids, acting_emp_id=None):
    emp_ids = list(emp_ids)
    if MASTER_ADMIN_ID in emp_ids:
        raise ValidationError("Cannot delete the master administrator (EMP0000).")
    if acting_emp_id and acting_emp_id in emp_ids:
        raise ValidationError("You cannot delete your own account while logged in.")
    with db.transaction(conn):
        for e in emp_ids:
            conn.execute("DELETE FROM employee WHERE emp_id = ?", (e,))
    return len(emp_ids)


def list_employees(conn, search=""):
    """Public view: no password, Aadhaar masked."""
    like = "%%%s%%" % (search or "").strip()
    rows = conn.execute("SELECT emp_id, name, contact_num, address, aadhar_num, designation "
                        "FROM employee WHERE emp_id LIKE ? OR name LIKE ? ORDER BY emp_id",
                        (like, like)).fetchall()
    return [dict(r, aadhar_num=security.mask_aadhaar(r["aadhar_num"])) for r in rows]


def get_employee(conn, emp_id):
    for e in list_employees(conn, emp_id):
        if e["emp_id"] == emp_id:
            return e
    return None


# ------------------------------------------------------------ customers
def _validate_customer(data):
    name, phone = _clean(data, "name"), _clean(data, "phone")
    gstin = _clean(data, "gstin").upper()
    if not name:
        raise ValidationError("Please enter customer name.")
    if not security.valid_phone(phone):
        raise ValidationError("Invalid customer phone number (10 digits, starting 6-9).")
    if gstin and not security.valid_gstin(gstin):
        raise ValidationError("Invalid GSTIN.")
    return dict(name=name, phone=phone, email=_clean(data, "email"),
                address=_clean(data, "address"), state_code=_clean(data, "state_code"),
                gstin=gstin)


def find_customer_by_phone(conn, phone):
    row = conn.execute("SELECT * FROM customer WHERE phone = ?", ((phone or "").strip(),)).fetchone()
    return dict(row) if row else None


def save_customer(conn, data):
    """Insert, or update the customer with the same phone. Returns customer_id."""
    c = _validate_customer(data)
    with db.transaction(conn):
        row = conn.execute("SELECT customer_id FROM customer WHERE phone = ?", (c["phone"],)).fetchone()
        if row:
            conn.execute("UPDATE customer SET name=?, email=?, address=?, state_code=?, gstin=? "
                         "WHERE customer_id=?", (c["name"], c["email"], c["address"],
                                                 c["state_code"], c["gstin"], row[0]))
            return row[0]
        cur = conn.execute("INSERT INTO customer(name, phone, email, address, state_code, gstin, "
                           "created_at) VALUES (?,?,?,?,?,?,?)",
                           (c["name"], c["phone"], c["email"], c["address"], c["state_code"],
                            c["gstin"], db.now_iso()))
        return cur.lastrowid


def list_customers(conn, search=""):
    like = "%%%s%%" % (search or "").strip()
    sql = """SELECT c.*, COUNT(b.bill_no) AS invoices,
                    COALESCE(SUM(CASE WHEN b.status='CANCELLED' THEN 0
                                      ELSE CAST(b.grand_total AS REAL) END), 0) AS spent
             FROM customer c LEFT JOIN bill b ON b.customer_id = c.customer_id
             WHERE c.name LIKE ? OR c.phone LIKE ?
             GROUP BY c.customer_id ORDER BY c.name"""
    return [dict(r) for r in conn.execute(sql, (like, like))]


def customer_history(conn, customer_id):
    row = conn.execute("SELECT phone FROM customer WHERE customer_id=?", (customer_id,)).fetchone()
    phone = row[0] if row else None
    return [dict(r) for r in conn.execute(
        "SELECT bill_no, date, grand_total, payment_mode, status FROM bill "
        "WHERE customer_id = ? OR (customer_id IS NULL AND customer_no = ?) "
        "ORDER BY date DESC, bill_no DESC", (customer_id, phone))]


# ------------------------------------------------------------ suppliers
def _validate_supplier(data):
    name, phone = _clean(data, "name"), _clean(data, "phone")
    gstin = _clean(data, "gstin").upper()
    if not name:
        raise ValidationError("Please enter supplier name.")
    if phone and not security.valid_phone(phone):
        raise ValidationError("Invalid supplier phone number.")
    if gstin and not security.valid_gstin(gstin):
        raise ValidationError("Invalid GSTIN.")
    return (name, phone, _clean(data, "email"), _clean(data, "address"), gstin)


def save_supplier(conn, data, supplier_id=None):
    vals = _validate_supplier(data)
    with db.transaction(conn):
        if supplier_id:
            conn.execute("UPDATE supplier SET name=?, phone=?, email=?, address=?, gstin=? "
                         "WHERE supplier_id=?", vals + (supplier_id,))
            return supplier_id
        return conn.execute("INSERT INTO supplier(name, phone, email, address, gstin, created_at) "
                            "VALUES (?,?,?,?,?,?)", vals + (db.now_iso(),)).lastrowid


def delete_supplier(conn, supplier_id):
    with db.transaction(conn):
        conn.execute("UPDATE raw_inventory SET supplier_id = NULL WHERE supplier_id = ?", (supplier_id,))
        conn.execute("DELETE FROM supplier WHERE supplier_id = ?", (supplier_id,))


def list_suppliers(conn, search=""):
    like = "%%%s%%" % (search or "").strip()
    return [dict(r) for r in conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM raw_inventory p WHERE p.supplier_id = s.supplier_id) "
        "AS products FROM supplier s WHERE s.name LIKE ? OR s.phone LIKE ? ORDER BY s.name",
        (like, like))]
