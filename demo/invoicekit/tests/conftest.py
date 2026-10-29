"""Shared fixtures for the demo target's test suite."""

from __future__ import annotations

from decimal import Decimal

import pytest

from invoicekit import Customer, Invoice, LineItem


@pytest.fixture()
def customer() -> Customer:
    return Customer(name="Ada Lovelace", email="ada@example.com")


@pytest.fixture()
def line_items() -> list[LineItem]:
    return [
        LineItem(sku="widget-a", quantity=2, unit_price=Decimal("10.00")),
        LineItem(sku="widget-b", quantity=3, unit_price=Decimal("5.00")),
    ]


@pytest.fixture()
def invoice(customer: Customer, line_items: list[LineItem]) -> Invoice:
    return Invoice(
        customer=customer,
        currency="eur",
        line_items=line_items,
        discount_pct=Decimal("10"),
    )
