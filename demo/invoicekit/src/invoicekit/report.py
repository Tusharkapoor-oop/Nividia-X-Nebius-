"""Text and JSON renderers for invoices."""

from __future__ import annotations

import json
from typing import Any, Dict

from invoicekit import pricing
from invoicekit.models import Invoice


def render_text(invoice: Invoice) -> str:
    """Render a plain-text invoice, one line per item plus a totals block."""
    lines = [
        f"Invoice for {invoice.customer.name} <{invoice.customer.email}>",
        f"Currency: {invoice.currency}",
    ]
    for item in invoice.line_items:
        lines.append(
            f"  {item.sku} x{item.quantity} @ {item.unit_price} = {pricing.line_total(item)}"
        )
    totals = pricing.breakdown(invoice)
    lines.append(f"Subtotal: {totals['subtotal']}")
    lines.append(f"Discount: {totals['discount']}")
    lines.append(f"Net: {totals['net']}")
    lines.append(f"Tax ({invoice.currency}): {totals['tax']}")
    lines.append(f"Total: {totals['total']}")
    return "\n".join(lines)


def summary_payload(invoice: Invoice) -> Dict[str, Any]:
    """JSON-serialisable view of an invoice plus its computed totals."""
    payload = invoice.dict()
    payload["totals"] = {key: str(value) for key, value in pricing.breakdown(invoice).items()}
    return json.loads(json.dumps(payload, default=str))
