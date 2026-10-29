"""Invoice arithmetic, kept separate from the pydantic models."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict

from invoicekit.models import Invoice, LineItem

TAX_RATES: Dict[str, Decimal] = {
    "EUR": Decimal("0.19"),
    "INR": Decimal("0.18"),
    "USD": Decimal("0.07"),
}

CENT = Decimal("0.01")


class UnsupportedCurrencyError(ValueError):
    """The invoice currency has no configured tax rate."""


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(item: LineItem) -> Decimal:
    return _cents(Decimal(item.quantity) * item.unit_price)


def subtotal(invoice: Invoice) -> Decimal:
    total = Decimal("0")
    for item in invoice.line_items:
        total += line_total(item)
    return _cents(total)


def discount(invoice: Invoice) -> Decimal:
    return _cents(subtotal(invoice) * invoice.discount_pct / Decimal("100"))


def net(invoice: Invoice) -> Decimal:
    return _cents(subtotal(invoice) - discount(invoice))


def tax(invoice: Invoice) -> Decimal:
    rate = TAX_RATES.get(invoice.currency)
    if rate is None:
        raise UnsupportedCurrencyError(f"no tax rate configured for {invoice.currency}")
    return _cents(net(invoice) * rate)


def total(invoice: Invoice) -> Decimal:
    return _cents(net(invoice) + tax(invoice))


def breakdown(invoice: Invoice) -> Dict[str, Decimal]:
    return {
        "subtotal": subtotal(invoice),
        "discount": discount(invoice),
        "net": net(invoice),
        "tax": tax(invoice),
        "total": total(invoice),
    }
