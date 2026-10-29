"""Held-out behavioural contract for the invoicekit demo case.

This file lives OUTSIDE ``demo/invoicekit`` on purpose. It is never copied into
the agent's work tree, and it is not referenced by any prompt: the agent cannot
read it, so a pass here means the migrated source kept its public behaviour
rather than being tuned to the visible tests.

It is committed *before* the first agent run (see git history), and it only
touches the project's public API: ``Customer``, ``LineItem``, ``Invoice``,
``invoicekit.pricing``, ``invoicekit.report``.

Run it against a checkout with:

    python -m pytest demo/heldout -q   # with the checkout importable

The demo runner (``bench/demo_case.py``) copies this directory into a scratch
checkout, never into the repository the agent patches.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoicekit import (
    MAX_LINE_ITEMS,
    Customer,
    Invoice,
    LineItem,
    render_text,
    summary_payload,
)
from invoicekit.pricing import breakdown


def _customer() -> Customer:
    return Customer(name="Katherine Johnson", email="katherine+invoices@example.co.uk")


def _invoice(**overrides: object) -> Invoice:
    values: dict[str, object] = {
        "customer": _customer(),
        "currency": "eur",
        "line_items": [LineItem(sku=" orbit-1 ", quantity=3, unit_price=Decimal("0.335"))],
        "discount_pct": Decimal("0"),
    }
    values.update(overrides)
    return Invoice(**values)  # type: ignore[arg-type]


def test_plus_addresses_are_valid_and_missing_tld_is_not() -> None:
    assert _customer().email == "katherine+invoices@example.co.uk"
    with pytest.raises(ValidationError):
        Customer(name="Katherine", email="katherine@example")


def test_sku_normalisation_survives_the_upgrade() -> None:
    item = LineItem(sku=" orbit-1 ", quantity=1, unit_price=Decimal("1.00"))
    assert item.sku == "ORBIT-1"


def test_quantity_boundaries_are_inclusive() -> None:
    assert LineItem(sku="ORBIT-1", quantity=1000, unit_price=Decimal("1.00")).quantity == 1000
    with pytest.raises(ValidationError):
        LineItem(sku="ORBIT-1", quantity=1001, unit_price=Decimal("1.00"))


def test_line_item_cap_is_inclusive() -> None:
    items = [
        LineItem(sku=f"ORBIT-{index:03d}", quantity=1, unit_price=Decimal("1.00"))
        for index in range(MAX_LINE_ITEMS)
    ]
    assert len(_invoice(line_items=items).line_items) == MAX_LINE_ITEMS


def test_zero_and_full_discount_are_accepted() -> None:
    free = _invoice(discount_pct=Decimal("100"))
    assert breakdown(free)["discount"] == breakdown(free)["subtotal"]
    assert breakdown(free)["total"] == Decimal("0.00")


def test_discount_above_one_hundred_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _invoice(discount_pct=Decimal("100.01"))


def test_currency_is_normalised_when_loaded_from_a_payload() -> None:
    payload = {
        "customer": {"name": "Katherine Johnson", "email": "k@example.com"},
        "currency": " inr ",
        "line_items": [{"sku": "orbit-1", "quantity": 1, "unit_price": "100.00"}],
        "discount_pct": "0",
    }
    assert Invoice.from_payload(payload).currency == "INR"


def test_models_stay_immutable_after_the_upgrade() -> None:
    invoice = _invoice()
    with pytest.raises((TypeError, ValueError)):
        invoice.currency = "USD"  # type: ignore[misc]
    with pytest.raises((TypeError, ValueError)):
        invoice.customer.name = "Someone Else"  # type: ignore[misc]


def test_rounding_and_tax_are_unchanged() -> None:
    # 3 x 0.335 = 1.005 -> 1.01 (half up); INR 18% of 1.01 = 0.1818 -> 0.18.
    figures = breakdown(_invoice(currency="INR"))
    assert figures["subtotal"] == Decimal("1.01")
    assert figures["tax"] == Decimal("0.18")
    assert figures["total"] == Decimal("1.19")


def test_report_text_keeps_its_headings_and_order() -> None:
    lines = render_text(_invoice()).splitlines()
    assert lines[0].startswith("Invoice for Katherine Johnson <")
    assert lines[1] == "Currency: EUR"
    assert lines[-1] == "Total: 1.20"


def test_summary_payload_serialises_totals_as_strings() -> None:
    totals = summary_payload(_invoice())["totals"]
    assert totals["subtotal"] == "1.01"
    assert totals["total"] == "1.20"
