"""Invoice models for the UpgradePilot demo target.

This is an original demo project written for this repository (MIT). It exists
so the upgrade pipeline can be exercised end to end on a codebase we own and
can talk about freely. It is deliberately pinned to pydantic v1: the upgrade
to v2 is the demo, and the project is *not* part of the benchmark.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from pydantic import BaseModel, Field, root_validator, validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
MAX_LINE_ITEMS = 50


class Customer(BaseModel):
    """The party being invoiced."""

    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., regex=EMAIL_PATTERN)

    class Config:
        allow_mutation = False


class LineItem(BaseModel):
    """One billable line: a SKU, how many, and the unit price."""

    sku: str = Field(..., min_length=3, max_length=32)
    quantity: int = Field(..., gt=0, le=1000)
    unit_price: Decimal = Field(..., ge=0)

    class Config:
        allow_mutation = False

    @validator("sku", pre=True)
    def _normalise_sku(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class Invoice(BaseModel):
    """An invoice: one customer, one currency, one or more line items."""

    customer: Customer
    currency: str = Field(..., min_length=3, max_length=3)
    line_items: List[LineItem]
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)

    class Config:
        allow_mutation = False

    @validator("currency", pre=True)
    def _normalise_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @root_validator
    def _check_invoice_shape(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        items = values.get("line_items") or []
        if not items:
            raise ValueError("an invoice needs at least one line item")
        if len(items) > MAX_LINE_ITEMS:
            raise ValueError(f"an invoice supports at most {MAX_LINE_ITEMS} line items")
        return values

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "Invoice":
        """Build an invoice from a raw mapping (API payload, JSON body, ...)."""
        return cls.parse_obj(payload)
