"""Password hashing, masking and role permissions (standard library only)."""
import hashlib
import hmac
import re
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 390_000
MIN_PASSWORD_LENGTH = 6

# Role-based permissions. Designations other than these get CASHIER rights.
PERMISSIONS = {
    "Admin": {"admin_panel", "inventory", "employees", "invoices", "cancel_invoice",
              "analytics", "reports", "customers", "suppliers", "settings", "billing"},
    "Manager": {"admin_panel", "inventory", "invoices", "analytics", "reports",
                "customers", "suppliers", "billing"},
}
CASHIER_PERMISSIONS = {"billing"}
ROLES = ("Admin", "Manager", "Cashier")


def permissions_for(designation):
    return PERMISSIONS.get((designation or "").strip().title(), CASHIER_PERMISSIONS)


def can(designation, permission):
    return permission in permissions_for(designation)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "%s$%d$%s$%s" % (ALGORITHM, ITERATIONS, salt.hex(), digest.hex())


def is_hashed(stored):
    return isinstance(stored, str) and stored.startswith(ALGORITHM + "$")


def verify_password(password, stored):
    """Return (ok, needs_rehash).

    Legacy rows hold a plain-text password: it is compared in constant time
    and, if correct, the caller re-hashes it (``needs_rehash``).
    """
    if not stored or password is None:
        return False, False
    if is_hashed(stored):
        try:
            _, iters, salt, digest = stored.split("$")
            calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                       bytes.fromhex(salt), int(iters))
        except (ValueError, TypeError):
            return False, False
        ok = hmac.compare_digest(calc.hex(), digest)
        return ok, ok and int(iters) < ITERATIONS
    ok = hmac.compare_digest(str(stored).encode("utf-8"), password.encode("utf-8"))
    return ok, ok


def validate_new_password(password):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return "Password must be at least %d characters." % MIN_PASSWORD_LENGTH
    return None


def mask_aadhaar(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    return "XXXX-XXXX-" + digits[-4:] if len(digits) >= 4 else "XXXX"


def valid_phone(phone):
    """Indian mobile number: 10 digits starting with 6-9."""
    return bool(re.fullmatch(r"[6-9]\d{9}", str(phone or "").strip()))


def valid_aadhaar(value):
    return bool(re.fullmatch(r"[2-9]\d{11}", str(value or "").strip()))


GSTIN_RE = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


def valid_gstin(value):
    return bool(GSTIN_RE.fullmatch(str(value or "").strip().upper()))
