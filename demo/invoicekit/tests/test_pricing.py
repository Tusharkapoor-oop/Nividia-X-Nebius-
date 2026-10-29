"""Arithmetic tests for the demo target."""

from __future__ import annotations

from decimal import Decimal

import pytest

from invoicekit import (
    Customer,
    Invoice,
    LineItem,
    UnsupportedCurrencyError,
    breakdown,
    discount,
    line_total,
    net,
    subtotal,
    tax,
    total,
)


def test_line_total_multiplies_quantity_by_price() -> None:
    item = LineItem(sku="WIDGET-A", quantity=3, unit_price=Decimal("2.50"))
    assert line_total(item) == Decimal("7.50")


def test_line_total_rounds_half_up_to_cents() -> None:
    item = LineItem(sku="WIDGET-A", quantity=1, unit_price=Decimal("0.005"))
    assert line_total(item) == Decimal("0.01")


def test_subtotal_sums_every_line(invoice: Invoice) -> None:
    assert subtotal(invoice) == Decimal("35.00")


def test_discount_is_a_percentage_of_the_subtotal(invoice: Invoice) -> None:
    assert discount(invoice) == Decimal("3.50")


def test_net_subtracts_the_discount(invoice: Invoice) -> None:
    assert net(invoice) == Decimal("31.50")


def test_tax_uses_the_invoice_currency_rate(invoice: Invoice) -> None:
    assert invoice.currency == "EUR"
    assert tax(invoice) == Decimal("5.99")


def test_total_adds_net_and_tax(invoice: Invoice) -> None:
    assert total(invoice) == Decimal("37.49")


def test_unsupported_currency_has_no_tax_rate(customer: Customer) -> None:
    invoice = Invoice(
        customer=customer,
        currency="GBP",
        line_items=[LineItem(sku="WIDGET-A", quantity=1, unit_price=Decimal("1.00"))],
    )
    with pytest.raises(UnsupportedCurrencyError):
        tax(invoice)


def test_breakdown_reports_every_component(invoice: Invoice) -> None:
    figures = breakdown(invoice)
    assert list(figures) == ["subtotal", "discount", "net", "tax", "total"]
    assert figures["total"] == total(invoice)
