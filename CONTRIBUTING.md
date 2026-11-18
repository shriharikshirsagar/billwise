# Contributing to Billwise

## Development setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t .
```

## Ground rules

- **Money is `Decimal`.** Never use floats for amounts.
- **Billing rules live in `billing.py`.** Any change to how GST, discounts or rounding work needs tests and a note in `CHANGELOG.md`.
- **Stored invoices are never recalculated.** Each invoice keeps its own line values.
- **Database changes are additive.** Add a new numbered migration in `db.py`. Never drop or rename columns that hold history.
- **Tests use temporary databases.** Use `tests.helpers.TempDBTestCase` and label fixtures `TEST`.
- **One theme.** Colours, fonts and styles come from `theme.py`; shared widgets come from `ui.py`.
- **Every visible button must do something.** The GUI tests check this.
- **Privacy.** Never log or export passwords, full Aadhaar numbers or full customer phone numbers.

## Commit style

Use short imperative subjects, for example `Add GST summary export`. Explain *why* in the body when it isn't obvious.
