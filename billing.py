"""Billwise billing engine - pure functions, no GUI and no database.

Rounding rules (approved, documented in README):
  * All money is ``decimal.Decimal``; floats are never used for amounts.
  * Prices stored on products are MRP, i.e. INCLUSIVE of GST.
  * Per line:
      gross     = unit_price x qty                         (2 dp)
      discount  = gross x discount% / 100                  (2 dp, half-up)
      line_total= gross - discount       (what the customer pays for the line)
      tax       = line_total x rate / (100 + rate)         (2 dp, half-up)
      taxable   = line_total - tax
    Intra-state: CGST = tax / 2 (2 dp, half-up), SGST = tax - CGST
                 (so an odd paisa sits in CGST and CGST+SGST == tax exactly).
    Inter-state: IGST = tax.
  * Invoice totals are sums of the stored line values.
  * Grand total = sum of line totals rounded to the nearest rupee (half-up);
    the difference is shown as "Round off".
  Invariants: taxable + tax == line_total; sum(lines) + round_off == grand_total.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CALC_VERSION = 1
PAISA = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")
INTRA = "INTRA"
INTER = "INTER"
PAYMENT_MODES = ("Cash", "UPI", "Card")


class BillingError(ValueError):
    """Raised for invalid billing input (shown to the user as-is)."""


def to_decimal(value, what="amount"):
    if isinstance(value, Decimal):
        d = value
    elif value is None or (isinstance(value, str) and not value.strip()):
        raise BillingError("Missing %s." % what)
    else:
        try:
            # str() first so a legacy REAL like 10.1 becomes Decimal('10.1')
            d = Decimal(str(value).strip())
        except InvalidOperation:
            raise BillingError("Invalid %s: %r" % (what, value)) from None
    if not d.is_finite():
        raise BillingError("Invalid %s: %r" % (what, value))
    return d


def money(value):
    return to_decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


def fmt(value):
    """Format money for display: 1234.5 -> '1,234.50'."""
    return "{:,.2f}".format(money(value))


def parse_rate(value):
    rate = to_decimal(value, "GST rate")
    if rate < 0 or rate > 100:
        raise BillingError("GST rate must be between 0 and 100.")
    return rate.normalize() if rate == rate.to_integral() else rate


def parse_qty(value):
    text = str(value).strip()
    if not text.isdigit() or int(text) <= 0:
        raise BillingError("Quantity must be a whole number greater than zero.")
    return int(text)


def parse_discount(value):
    if value is None or str(value).strip() == "":
        return Decimal("0")
    d = to_decimal(value, "discount %")
    if d < 0 or d > 100:
        raise BillingError("Discount must be between 0 and 100 %.")
    return d


@dataclass
class CartLine:
    product_id: int
    name: str
    unit_price: Decimal          # MRP, GST inclusive
    gst_rate: Decimal
    qty: int
    discount_pct: Decimal = Decimal("0")
    hsn_code: str = ""
    cost_price: Decimal = None


@dataclass
class LineResult:
    line_no: int
    product_id: int
    name: str
    hsn_code: str
    qty: int
    unit_price: Decimal
    discount_pct: Decimal
    gross: Decimal
    discount: Decimal
    taxable: Decimal
    gst_rate: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    line_total: Decimal
    cost_price: Decimal = None

    @property
    def tax(self):
        return self.cgst + self.sgst + self.igst


@dataclass
class InvoiceTotals:
    supply_type: str
    lines: list = field(default_factory=list)
    subtotal: Decimal = ZERO
    discount: Decimal = ZERO
    taxable: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    igst: Decimal = ZERO
    net: Decimal = ZERO
    round_off: Decimal = ZERO
    grand_total: Decimal = ZERO

    @property
    def tax(self):
        return self.cgst + self.sgst + self.igst

    def gst_breakdown(self):
        """{rate: (taxable, cgst, sgst, igst)} for the GST summary table."""
        out = {}
        for ln in self.lines:
            t = out.setdefault(ln.gst_rate, [ZERO, ZERO, ZERO, ZERO])
            t[0] += ln.taxable
            t[1] += ln.cgst
            t[2] += ln.sgst
            t[3] += ln.igst
        return {k: tuple(v) for k, v in sorted(out.items())}


def calculate_line(line, supply_type, line_no=1):
    if supply_type not in (INTRA, INTER):
        raise BillingError("Unknown supply type %r" % supply_type)
    qty = parse_qty(line.qty)
    price = money(line.unit_price)
    if price < 0:
        raise BillingError("Price cannot be negative.")
    rate = parse_rate(line.gst_rate)
    disc_pct = parse_discount(line.discount_pct)

    gross = money(price * qty)
    discount = money(gross * disc_pct / 100)
    line_total = gross - discount
    tax = money(line_total * rate / (100 + rate))
    taxable = line_total - tax
    if supply_type == INTRA:
        cgst = money(tax / 2)
        sgst = tax - cgst
        igst = ZERO
    else:
        cgst = sgst = ZERO
        igst = tax
    return LineResult(line_no, line.product_id, line.name, line.hsn_code or "", qty, price,
                      disc_pct, gross, discount, taxable, rate, cgst, sgst, igst, line_total,
                      None if line.cost_price is None else money(line.cost_price))


def calculate_invoice(lines, supply_type):
    if not lines:
        raise BillingError("Cart is empty.")
    res = InvoiceTotals(supply_type=supply_type)
    for i, line in enumerate(lines, start=1):
        r = calculate_line(line, supply_type, i)
        res.lines.append(r)
        res.subtotal += r.gross
        res.discount += r.discount
        res.taxable += r.taxable
        res.cgst += r.cgst
        res.sgst += r.sgst
        res.igst += r.igst
        res.net += r.line_total
    res.grand_total = res.net.quantize(RUPEE, rounding=ROUND_HALF_UP).quantize(PAISA)
    res.round_off = res.grand_total - res.net
    return res


def supply_type_for(store_state_code, place_of_supply_code):
    if not store_state_code:
        raise BillingError("Store state is not set. Ask the administrator to set it in Settings.")
    if not place_of_supply_code:
        raise BillingError("Choose the place of supply (customer state).")
    return INTRA if store_state_code == place_of_supply_code else INTER


def validate_payment(mode, grand_total, tendered=None, reference=""):
    """Returns (tendered, change, reference) as stored on the invoice."""
    if mode not in PAYMENT_MODES:
        raise BillingError("Choose a payment mode (Cash, UPI or Card).")
    reference = (reference or "").strip()
    if mode == "Cash":
        paid = grand_total if tendered in (None, "") else money(tendered)
        if paid < grand_total:
            raise BillingError("Cash received is less than the amount payable.")
        return paid, paid - grand_total, ""
    if mode == "Card":
        if reference and (not reference.isdigit() or len(reference) != 4):
            raise BillingError("For card payments enter only the last 4 digits of the card.")
    elif mode == "UPI" and len(reference) > 40:
        raise BillingError("UPI reference is too long.")
    return grand_total, ZERO, reference


class Cart:
    """Cart that merges repeated additions of the same product.

    Stock is validated against the total quantity already in the cart.
    """

    def __init__(self):
        self.lines = []

    def find(self, product_id):
        for ln in self.lines:
            if ln.product_id == product_id:
                return ln
        return None

    def add(self, product_id, name, unit_price, gst_rate, qty, stock,
            discount_pct=0, hsn_code="", cost_price=None):
        qty = parse_qty(qty)
        if gst_rate is None or str(gst_rate).strip() == "":
            raise BillingError("GST rate is not set for '%s'. Ask the administrator to set it." % name)
        rate = parse_rate(gst_rate)
        disc = parse_discount(discount_pct)
        existing = self.find(product_id)
        in_cart = existing.qty if existing else 0
        if stock is None or in_cart + qty > int(stock):
            raise BillingError("Only %s of '%s' in stock (%d already in cart)."
                               % (stock, name, in_cart))
        if existing:
            existing.qty += qty
            existing.discount_pct = disc
            return existing
        line = CartLine(product_id, name, money(unit_price), rate, qty, disc, hsn_code or "",
                        None if cost_price in (None, "") else money(cost_price))
        self.lines.append(line)
        return line

    def remove(self, product_id):
        line = self.find(product_id)
        if line is None:
            raise BillingError("That product is not in the cart.")
        self.lines.remove(line)
        return line

    def set_qty(self, product_id, qty, stock):
        line = self.find(product_id)
        if line is None:
            raise BillingError("That product is not in the cart.")
        qty = parse_qty(qty)
        if qty > int(stock):
            raise BillingError("Only %s of '%s' in stock." % (stock, line.name))
        line.qty = qty

    def clear(self):
        self.lines.clear()

    def is_empty(self):
        return not self.lines

    def quantities(self):
        return {ln.product_id: ln.qty for ln in self.lines}

    def totals(self, supply_type):
        return calculate_invoice(self.lines, supply_type)
