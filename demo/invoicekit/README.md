# invoicekit (demo target)

A tiny invoice calculator, written for this repository as the **demo target**
for UpgradePilot. It is MIT licensed, original code, and is **not** part of the
benchmark case set (`bench/cases.json`).

It is pinned to pydantic `1.10.22` and uses v1-only APIs:

- `Field(..., regex=...)`
- `@validator` / `@root_validator`
- `class Config: allow_mutation = False`
- `BaseModel.parse_obj`

Bumping to pydantic v2 breaks the import with a `PydanticUserError`, so the
suite cannot even collect until the source (never the tests) is migrated.

Because a model may already have seen similar public code, a successful
UpgradePilot run on this project shows that the *pipeline* works end to end.
It is not evidence of generalisation to unseen repositories.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m pip install pytest
.venv/Scripts/python.exe -m pytest
```
