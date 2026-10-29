"""Model-level tests for the demo target."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoicekit import MAX_LINE_ITEMS, Customer, Invoice, LineItem


def test_customer_accepts_a_valid_email() -> None:
    customer = Customer(name="Ada", email="ada@example.com")
    assert customer.email == "ada@example.com"
    assert customer.name == "Ada"


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "ada@example", "ada.example.com", "ada@.com", "@example.com"],
)
def test_customer_rejects_a_malformed_email(email: str) -> None:
    with pytest.raises(ValidationError):
        Customer(name="Ada", email=email)


def test_sku_is_stripped_and_uppercased() -> None:
    item = LineItem(sku="  widget-a  ", quantity=1, unit_price=Decimal("1.00"))
    assert item.sku == "WIDGET-A"


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        LineItem(sku="WIDGET-A", quantity=0, unit_price=Decimal("1.00"))


def test_quantity_is_capped() -> None:
    with pytest.raises(ValidationError):
        LineItem(sku="WIDGET-A", quantity=1001, unit_price=Decimal("1.00"))


def test_unit_price_may_not_be_negative() -> None:
    with pytest.raises(ValidationError):
        LineItem(sku="WIDGET-A", quantity=1, unit_price=Decimal("-0.01"))


def test_invoice_requires_at_least_one_line_item(customer: Customer) -> None:
    with pytest.raises(ValidationError):
        Invoice(customer=customer, currency="EUR", line_items=[])


def test_invoice_rejects_too_many_line_items(customer: Customer) -> None:
    items = [
        LineItem(sku=f"SKU-{index:03d}", quantity=1, unit_price=Decimal("1.00"))
        for index in range(MAX_LINE_ITEMS + 1)
    ]
    with pytest.raises(ValidationError):
        Invoice(customer=customer, currency="EUR", line_items=items)


def test_currency_is_normalised(invoice: Invoice) -> None:
    assert invoice.currency == "EUR"


def test_discount_must_be_a_percentage(customer: Customer, line_items: list[LineItem]) -> None:
    with pytest.raises(ValidationError):
        Invoice(
            customer=customer,
            currency="EUR",
            line_items=line_items,
            discount_pct=Decimal("100.5"),
        )


def test_models_are_immutable(invoice: Invoice) -> None:
    with pytest.raises((TypeError, ValueError)):
        invoice.currency = "USD"  # type: ignore[misc]


def test_from_payload_builds_a_valid_invoice() -> None:
    invoice = Invoice.from_payload(
        {
            "customer": {"name": "Grace Hopper", "email": "grace@example.com"},
            "currency": "usd",
            "line_items": [
                {"sku": "navy-1", "quantity": 4, "unit_price": "2.50"},
            ],
        }
    )
    assert invoice.currency == "USD"
    assert invoice.line_items[0].sku == "NAVY-1"
    assert invoice.discount_pct == Decimal("0")


def test_from_payload_still_validates() -> None:
    with pytest.raises(ValidationError):
        Invoice.from_payload(
            {
                "customer": {"name": "Grace Hopper", "email": "grace@example"},
                "currency": "USD",
                "line_items": [{"sku": "NAVY-1", "quantity": 1, "unit_price": "1.00"}],
            }
        )
