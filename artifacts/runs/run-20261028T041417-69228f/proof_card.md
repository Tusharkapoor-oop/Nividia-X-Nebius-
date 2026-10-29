# UpgradePilot Proof Card: `pydantic -> 2.12.4`

- **Run ID:** `run-20261028T041417-69228f`
- **Target Repo:** `C:\Users\ACER\Downloads\Nividia X nebius\upgradepilot\demo\invoicekit`
- **Final Verdict:** **`GREEN`**
- **Iterations:** 3
- **Cost:** Unpriced (4 of 4 calls; provider publishes no catalog price)
- **Tokens:** 7535 prompt + 2271 completion = 9806 total
- **Guard:** clean (clean (5 test files unchanged))
- **Provider:** NVIDIA NIM (dev run - not submission-eligible)
- **Models:** cheap=nvidia/nemotron-3.5-lightning-30b-a3b, default=nvidia/nemotron-3.5-lightning-30b-a3b, strong=nvidia/nemotron-3-ultra-550b-a55b
- **Environment:** pydantic 2.12.4, pytest 9.2.0, python 3.13.15
- **Test Suite Partition:** 2 visible, 1 held-out

## Execution Steps

| Step | Status | Tier | Detail |
|---|---|---|---|
| reference_verify | `ok` | - | Old-pin reference: GREEN (30 passed, 0 failed, 0 skipped, 0 xfailed) |
| heldout_split | `ok` | - | 2 visible, 1 held-out |
| guard_snapshot | `ok` | - | Hashed 5 test-surface files |
| heldout_quarantine | `ok` | - | Physically quarantined 1 held-out test file(s) outside worktree |
| baseline_verify | `start` | - | Testing visible suite before agent changes |
| baseline_verify | `ok` | - | Breakage confirmed: ENV_FAIL |
| triage | `start` | cheap | Analyzing failure and query |
| triage | `ok` | cheap | Query: 'pydantic 2.12 regex removed use pattern Field'; Candidates: 1 |
| research | `start` | - | Searching Tavily for 'pydantic 2.12 regex removed use pattern Field' |
| research | `ok` | - | Retrieved 3875 chars of context |
| patch_attempt_1 | `start` | default | Generating patch using nvidia/nemotron-3.5-lightning-30b-a3b |
| guard_check_1 | `ok` | - | clean (4 test files unchanged) |
| verify_1 | `failed` | - | Visible tests did not improve: the run is ENV_FAIL (0 passed, 0 failed, 0 error(s), exit 4), not an improvement on the previous ENV_FAIL (0 passed, 0 failed, 0 error(s)); rolled back 1 file(s) |
| patch_attempt_2 | `start` | default | Generating patch using nvidia/nemotron-3.5-lightning-30b-a3b |
| patch_attempt_2 | `failed` | default | EditError: Model returned invalid edits JSON: {   "files": [     {       "path": "src/invoicekit/models.py",       "action": "write",       "content": "from __future__ import annotations\n\nfrom decimal import Decimal\nfrom typing import Any, Dic; rolled back 0 file(s) |
| patch_attempt_3 | `start` | strong | Generating patch using nvidia/nemotron-3-ultra-550b-a55b |
| guard_check_3 | `ok` | - | clean (4 test files unchanged) |
| verify_3 | `ok` | - | Visible tests passed GREEN |
| certify_heldout | `start` | - | Verifying 1 held-out tests |
| certify_heldout | `ok` | - | Held-out verdict: GREEN; final: GREEN |

## Verification Results

- **Old-pin Reference (before the bump):** `GREEN` (exit 0, 30 passed, 0 failed, 0 skipped, 0 xfailed)
- **Baseline Visible Tests:** `ENV_FAIL` (exit 4, 0 passed, 0 failed in 0.00s)
- **Final Visible Tests:** `GREEN` (exit 0, 13 passed, 0 failed in 0.08s)
- **Held-out Tests:** `GREEN` (exit 0, 17 passed, 0 failed in 0.07s)

## Patch Attempts

### Attempt 1 — `rolled_back` (default)

Visible tests did not improve: the run is ENV_FAIL (0 passed, 0 failed, 0 error(s), exit 4), not an improvement on the previous ENV_FAIL (0 passed, 0 failed, 0 error(s)); rolled back 1 file(s)

Verification: `ENV_FAIL` (exit 4, 0 passed, 0 failed)

`src/invoicekit/models.py` (write)

```diff
--- a/src/invoicekit/models.py
+++ b/src/invoicekit/models.py
@@ -1,11 +1,3 @@
-"""Invoice models for the UpgradePilot demo target.
-
-This is an original demo project written for this repository (MIT). It exists
-so the upgrade pipeline can be exercised end to end on a codebase we own and
-can talk about freely. It is deliberately pinned to pydantic v1: the upgrade
-to v2 is the demo, and the project is *not* part of the benchmark.
-"""
-
 from __future__ import annotations
 
 from decimal import Decimal
@@ -21,7 +13,7 @@
     """The party being invoiced."""
 
     name: str = Field(..., min_length=1, max_length=80)
-    email: str = Field(..., regex=EMAIL_PATTERN)
+    email: str = Field(..., pattern=EMAIL_PATTERN)
 
     class Config:
         allow_mutation = False

```

### Attempt 2 — `invalid` (default)

EditError: Model returned invalid edits JSON: {
  "files": [
    {
      "path": "src/invoicekit/models.py",
      "action": "write",
      "content": "from __future__ import annotations\n\nfrom decimal import Decimal\nfrom typing import Any, Dic; rolled back 0 file(s)

### Attempt 3 — `GREEN` (strong)

Verification: `GREEN` (exit 0, 13 passed, 0 failed)

`src/invoicekit/models.py` (write)

```diff
--- a/src/invoicekit/models.py
+++ b/src/invoicekit/models.py
@@ -11,7 +11,7 @@
 from decimal import Decimal
 from typing import Any, Dict, List
 
-from pydantic import BaseModel, Field, root_validator, validator
+from pydantic import BaseModel, Field, field_validator, model_validator
 
 EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
 MAX_LINE_ITEMS = 50
@@ -21,10 +21,9 @@
     """The party being invoiced."""
 
     name: str = Field(..., min_length=1, max_length=80)
-    email: str = Field(..., regex=EMAIL_PATTERN)
+    email: str = Field(..., pattern=EMAIL_PATTERN)
 
-    class Config:
-        allow_mutation = False
+    model_config = {"frozen": True}
 
 
 class LineItem(BaseModel):
@@ -34,10 +33,10 @@
     quantity: int = Field(..., gt=0, le=1000)
     unit_price: Decimal = Field(..., ge=0)
 
-    class Config:
-        allow_mutation = False
+    model_config = {"frozen": True}
 
-    @validator("sku", pre=True)
+    @field_validator("sku", mode="before")
+    @classmethod
     def _normalise_sku(cls, value: Any) -> Any:
         if isinstance(value, str):
             return value.strip().upper()
@@ -52,25 +51,25 @@
     line_items: List[LineItem]
     discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
 
-    class Config:
-        allow_mutation = False
+    model_config = {"frozen": True}
 
-    @validator("currency", pre=True)
+    @field_validator("currency", mode="before")
+    @classmethod
     def _normalise_currency(cls, value: Any) -> Any:
         if isinstance(value, str):
             return value.strip().upper()
         return value
 
-    @root_validator
-    def _check_invoice_shape(cls, values: Dict[str, Any]) -> Dict[str, Any]:
-        items = values.get("line_items") or []
+    @model_validator(mode="after")
+    def _check_invoice_shape(self) -> "Invoice":
+        items = self.line_items
         if not items:
             raise ValueError("an invoice needs at least one line item")
         if len(items) > MAX_LINE_ITEMS:
             raise ValueError(f"an invoice supports at most {MAX_LINE_ITEMS} line items")
-        return values
+        return self
 
     @classmethod
     def from_payload(cls, payload: Dict[str, Any]) -> "Invoice":
         """Build an invoice from a raw mapping (API payload, JSON body, ...)."""
-        return cls.parse_obj(payload)
+        return cls.model_validate(payload)

```


## Applied Patches

### `src/invoicekit/models.py` (write)

```diff
--- a/src/invoicekit/models.py
+++ b/src/invoicekit/models.py
@@ -11,7 +11,7 @@
 from decimal import Decimal
 from typing import Any, Dict, List
 
-from pydantic import BaseModel, Field, root_validator, validator
+from pydantic import BaseModel, Field, field_validator, model_validator
 
 EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"
 MAX_LINE_ITEMS = 50
@@ -21,10 +21,9 @@
     """The party being invoiced."""
 
     name: str = Field(..., min_length=1, max_length=80)
-    email: str = Field(..., regex=EMAIL_PATTERN)
+    email: str = Field(..., pattern=EMAIL_PATTERN)
 
-    class Config:
-        allow_mutation = False
+    model_config = {"frozen": True}
 
 
 class LineItem(BaseModel):
@@ -34,10 +33,10 @@
     quantity: int = Field(..., gt=0, le=1000)
     unit_price: Decimal = Field(..., ge=0)
 
-    class Config:
-        allow_mutation = False
+    model_config = {"frozen": True}
 
-    @validator("sku", pre=True)
+    @field_validator("sku", mode="before")
+    @classmethod
     def _normalise_sku(cls, value: Any) -> Any:
         if isinstance(value, str):
             return value.strip().upper()
@@ -52,25 +51,25 @@
     line_items: List[LineItem]
     discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
 
-    class Config:
-        allow_mutation = False
+    model_config = {"frozen": True}
 
-    @validator("currency", pre=True)
+    @field_validator("currency", mode="before")
+    @classmethod
     def _normalise_currency(cls, value: Any) -> Any:
         if isinstance(value, str):
             return value.strip().upper()
         return value
 
-    @root_validator
-    def _check_invoice_shape(cls, values: Dict[str, Any]) -> Dict[str, Any]:
-        items = values.get("line_items") or []
+    @model_validator(mode="after")
+    def _check_invoice_shape(self) -> "Invoice":
+        items = self.line_items
         if not items:
             raise ValueError("an invoice needs at least one line item")
         if len(items) > MAX_LINE_ITEMS:
             raise ValueError(f"an invoice supports at most {MAX_LINE_ITEMS} line items")
-        return values
+        return self
 
     @classmethod
     def from_payload(cls, payload: Dict[str, Any]) -> "Invoice":
         """Build an invoice from a raw mapping (API payload, JSON body, ...)."""
-        return cls.parse_obj(payload)
+        return cls.model_validate(payload)

```

