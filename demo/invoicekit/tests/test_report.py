"""Rendering tests for the demo target."""

from __future__ import annotations

import json

from invoicekit import Invoice, render_text, summary_payload


def test_render_text_lists_every_line(invoice: Invoice) -> None:
    text = render_text(invoice)
    assert "Ada Lovelace" in text
    assert "WIDGET-A x2" in text
    assert "WIDGET-B x3" in text
    assert "Currency: EUR" in text


def test_render_text_shows_the_totals_block(invoice: Invoice) -> None:
    text = render_text(invoice)
    assert "Subtotal: 35.00" in text
    assert "Discount: 3.50" in text
    assert "Total: 37.49" in text


def test_summary_payload_exposes_customer_and_items(invoice: Invoice) -> None:
    payload = summary_payload(invoice)
    assert payload["customer"]["email"] == "ada@example.com"
    assert payload["currency"] == "EUR"
    assert [item["sku"] for item in payload["line_items"]] == ["WIDGET-A", "WIDGET-B"]


def test_summary_payload_is_json_serialisable(invoice: Invoice) -> None:
    payload = summary_payload(invoice)
    assert json.loads(json.dumps(payload))["totals"]["total"] == "37.49"
