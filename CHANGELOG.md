# Changelog

## 2.2.1 (2026-11-18)
- Demo catalogue expanded to 74 products (frozen foods and health & wellness added).
- "Returning customer" note moved into the Customer header so the invoicing desk fits 1366x768.
- README screenshots regenerated from the test store data.

## 2.2.0 (2026-11-18)

### Changed
- Visual identity: grouped navigation with a signed-in user block, breadcrumb header with live date and time, ledger-style metric tiles, navy invoice-summary panel, hairline section headings.
- Wording moved from till terms to invoicing terms (Invoicing desk, line items, Issue invoice).
- Quick search moved into the Add item header; zero discount no longer shows as -0.00.

### Added
- Repository presentation: README badges and screenshots, CONTRIBUTING.md, issue and pull-request templates, and a GitHub Actions workflow that runs the test suite.

## 2.1.0 (2026-11-18)

### Added
- Optional demo catalogue (`demo_catalogue.py`): everyday branded products with `DEMO-` SKUs, pack sizes and placeholder prices, flagged DEMO and removable from Settings.
- SKU, brand and pack size on products (database migration 3, additive); SKU must be unique.
- Billing quick search by name, brand or SKU.
- Dashboard 7-day sales chart.

### Changed
- Consistent Billwise branding; flat top bar, softer borders, zebra rows and hover tints.
- Vendor phone is optional (suppliers can be linked instead).

### Removed
- Leftovers from the recovered archive: old debug logs (`analytics.log`, `failure.log`), a stale generated PDF (`bill_with_fields.pdf`), and packaging scripts with hard-coded paths of the original machines (`build..py`, `setup.py`, `main.spec`). They remain in the local git history.

## 2.0.0 (2026-11-18)

First Billwise release.

### Fixed
- Startup: the missing `ttkbootstrap`/`reportlab` dependencies are declared, the unused `twilio` import is removed, the database is created on first run instead of crashing, and screens no longer depend on 16 missing background images.
- Paths are absolute and the launcher uses the current Python interpreter, so the app works from any folder. A child app that fails during start-up is reported instead of vanishing.
- Cart: stock was deducted again for earlier bills in the same session (`Cart.dictionary` was never reset); the cart was shared at class level; products were never cleared, so earlier bills' items leaked into the next PDF; stock was checked per click rather than for the whole cart, which allowed negative stock; zero quantities were accepted; line totals were wrong after Remove; Add To Cart after Total silently did nothing.
- Totals: float money is replaced with `Decimal`, and the PDF was being created before the bill number and date were assigned.
- Invoices: random bill numbers with no uniqueness check are replaced with sequential numbers, and the insert plus stock updates are now one transaction with rollback.
- Admin: `NameError`s in Update Product and Update Employee; the Analytics window left the dashboard hidden; Inventory logout left its window open; double-clicking an empty part of the invoice list raised `IndexError`; deleting several employees including `EMP0000` deleted some of them before showing the error; one bad line made analytics drop a whole bill.
- Validation: the phone regex now accepts numbers starting with 6; Aadhaar, GSTIN, MRP, cost, GST rate and HSN are validated.

### Added
- GST per product (CGST + SGST or IGST from the place of supply), per-line discount, rounding to the rupee with a round-off line, and documented rounding rules.
- Cash, UPI and card payment recording, invoice preview and reprint, and a branded ReportLab tax invoice.
- Invoice cancellation (void) that keeps the record and restores stock.
- Stock adjustments with movement history, low-stock alerts, suppliers, customers with purchase history.
- Roles (Admin / Manager / cashier), salted PBKDF2 password hashing with rehash on login, masked Aadhaar.
- Dashboard, analytics charts, and reports (daily and monthly sales, profit, best sellers, GST summary, invoice register, inventory valuation, low stock) with Excel and PDF export.
- Settings (store details and state, low-stock level, password change, manual backup).
- One-time first-run administrator setup (no default password).
- "Parliamentary Blue & Green" theme defined once in `theme.py`.
- Test suite (unit, integration and GUI) using temporary databases only.

### Database (additive only)
- New columns on `raw_inventory`: `hsn_code`, `gst_rate`, `reorder_level`, `supplier_id`.
- New columns on `bill`: totals, GST split, supply type, payment fields, status and cancellation fields, `calc_version`.
- New tables: `invoice_items`, `stock_movement`, `customer`, `supplier`, `settings`, `invoice_counter`, `schema_version`.
- Original tables and column order are unchanged. A backup is taken automatically before any upgrade of a database that already has data.
