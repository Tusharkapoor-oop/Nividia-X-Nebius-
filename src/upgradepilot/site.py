"""Static "recorded runs" site generated only from artifact JSON files.

The site never invents a run, a status, or a number: every page is rendered
from files under ``artifacts/`` (agent upgrade reports, Phase 5 strategy
results, and demo-case results). Files that cannot be parsed are listed on the
index as unreadable evidence instead of being silently skipped.

Output is plain semantic HTML + one stylesheet + copied JSON evidence, with no
JavaScript, so it deploys to GitHub Pages from ``docs/`` as-is.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from upgradepilot.agent import provider_label

_PROVIDER_NAMES = {"tokenfactory": "Nebius Token Factory", "nvidia-nim": "NVIDIA NIM"}
_RUN_ID_TS = re.compile(r"run-(\d{8}T\d{6})")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_LOCAL_USER_PATH = re.compile(
    r"(?i)\b[A-Z]:(?:\\+|/+)Users(?:\\+|/+)[^\\/]+|/(?:home|Users)/[^/]+"
)
_PUBLIC_SECRET = re.compile(r"\b(?:sk|pk|tvly|napi|nfma)[-_][A-Za-z0-9_\-]{16,}\b")


@dataclass
class Record:
    """One evidence file, normalised for display."""

    slug: str
    kind: str
    title: str
    status: str
    provider: str
    run_class: str
    recorded_at: str
    timestamp_source: str
    source_path: str
    raw_json: str
    proof_card: str = ""
    summary: list[tuple[str, str]] = field(default_factory=list)
    steps: list[tuple[str, str, str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    models: dict[str, str] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    suite: str = ""
    cost: str = ""
    tokens: str = ""
    guard: str = ""
    split: str = ""

    @property
    def provider_label(self) -> str:
        if not self.provider:
            return "provider not recorded"
        return provider_label(self.provider, self.run_class)


@dataclass
class SiteData:
    records: list[Record] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)


def _slug(*parts: str) -> str:
    raw = "-".join(part for part in parts if part)
    return _SAFE_NAME.sub("-", raw).strip("-") or "run"


def _run_id_timestamp(run_id: str) -> str:
    match = _RUN_ID_TS.search(run_id)
    if not match:
        return ""
    stamp = match.group(1)
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"


def _public_text(value: str) -> str:
    """Remove local account roots and key-shaped strings from public artifacts."""
    return _PUBLIC_SECRET.sub("<redacted>", _LOCAL_USER_PATH.sub("<local-user-path>", value))


def _public_json(value: Any) -> Any:
    """Recursively sanitize copied JSON without changing the source evidence."""
    if isinstance(value, str):
        return _public_text(value)
    if isinstance(value, list):
        return [_public_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _public_json(item) for key, item in value.items()}
    return value


def _cost_text(cost_usd: Any, fully_priced: Any, unpriced_calls: Any = None) -> str:
    if fully_priced and isinstance(cost_usd, (int, float)):
        return f"${cost_usd:.4f}"
    if unpriced_calls:
        return f"unpriced ({unpriced_calls} call(s))"
    return "unpriced"


def _suite(outcome: dict[str, Any] | None) -> str:
    if not isinstance(outcome, dict):
        return "not run"
    result = outcome.get("result") or {}
    return (
        f"{outcome.get('status', '?')}: {result.get('passed', 0)} passed, "
        f"{result.get('failed', 0)} failed, {result.get('errors', 0)} error(s), "
        f"exit {result.get('exit_code')}"
    )


def _from_agent(path: Path, data: dict[str, Any], rel: str) -> Record:
    run_id = str(data.get("run_id") or path.parent.name)
    request = data.get("request") or {}
    # Artifact evidence can contain the submitter's machine-local checkout path.
    # It is not needed to identify a recorded run and should not be published.
    if request.get("repo"):
        request = {**request, "repo": _public_text(str(request["repo"]))}
    cost = data.get("cost") or {}
    split = data.get("split") or {}
    steps = [
        (
            str(step.get("step", "")),
            str(step.get("status", "")),
            str(step.get("detail", "")),
            str(step.get("tier") or ""),
        )
        for step in data.get("steps") or []
        if isinstance(step, dict)
    ]
    recorded_at = _run_id_timestamp(run_id)
    record = Record(
        slug=_slug("agent", run_id),
        kind="agent",
        title=f"agent: {request.get('package', '?')} -> {request.get('to_version', '?')}",
        status=str(data.get("status", "UNKNOWN")),
        provider=str(data.get("provider") or ""),
        run_class=str(
            data.get("run_class")
            or ("submission" if data.get("provider") == "tokenfactory" else "dev")
        ),
        recorded_at=recorded_at,
        timestamp_source="run id (UTC)" if recorded_at else "not recorded",
        source_path=rel,
        raw_json="",
        models={str(k): str(v) for k, v in (data.get("models") or {}).items()},
        versions={str(k): str(v) for k, v in (data.get("versions") or {}).items()},
        suite=_suite(data.get("visible_outcome")),
        cost=_cost_text(
            cost.get("total_cost_usd"), cost.get("fully_priced"), cost.get("unpriced_calls")
        ),
        tokens=(
            f"{cost.get('total_prompt_tokens', 0)} in / "
            f"{cost.get('total_completion_tokens', 0)} out, {cost.get('calls', 0)} call(s)"
        ),
        guard=(
            "clean" if data.get("guard_clean") else f"VIOLATED ({data.get('guard_summary', '')})"
        ),
        split=(
            f"{len(split.get('visible') or [])} visible, {len(split.get('held_out') or [])} held-out"
            if split
            else "no split recorded"
        ),
        steps=steps,
    )
    record.summary = [
        ("Target repo", str(request.get("repo", ""))),
        ("Iterations", str(data.get("iterations_used", 0))),
        ("Old-pin reference", _suite(data.get("reference_outcome"))),
        ("Baseline (after bump)", _suite(data.get("baseline_outcome"))),
        ("Held-out suite", _suite(data.get("heldout_outcome"))),
        ("Test split", record.split),
        ("Guard", record.guard),
    ]
    return record


def _from_strategy(path: Path, data: dict[str, Any], rel: str, *, kind: str) -> Record:
    case_id = str(data.get("case_id", path.parent.parent.name))
    strategy = str(data.get("strategy", path.parent.name))
    raw_versions = data.get("versions")
    versions: dict[str, Any] = raw_versions if isinstance(raw_versions, dict) else {}
    cost = data.get("cost_usd")
    heldout = data.get("heldout_after") or {}
    if kind == "demo" and heldout:
        heldout_text = (
            f"{heldout.get('status', '?')}: {heldout.get('passed', 0)} passed, "
            f"{heldout.get('failed', 0)} failed"
        )
        visible_text = str(data.get("suite") or "not recorded")
        suite = f"visible {visible_text}; held-out {heldout_text}"
    else:
        suite = (
            f"exit {data.get('exit_code')}: {data.get('passed', 0)} passed, "
            f"{data.get('failed', 0)} failed, {data.get('errors', 0)} error(s)"
        )
        heldout_text = "not applicable"
    recorded_at = str(data.get("recorded_at") or "")
    record = Record(
        slug=_slug(kind, case_id, strategy),
        kind=kind,
        title=f"{case_id}: {strategy}",
        status=str(data.get("status", "UNKNOWN")),
        provider=str(data.get("provider") or ""),
        run_class=str(data.get("run_class") or "dev"),
        recorded_at=recorded_at,
        timestamp_source="result file (UTC)" if recorded_at else "not recorded",
        source_path=rel,
        raw_json="",
        suite=suite,
        cost=_cost_text(cost, data.get("fully_priced")),
        tokens=(
            f"{data.get('prompt_tokens', 0)} in / {data.get('completion_tokens', 0)} out, "
            f"{data.get('llm_calls', 0)} call(s)"
        ),
        versions={str(k): str(v) for k, v in versions.items()},
        models={str(k): str(v) for k, v in (data.get("models") or {}).items()},
        guard=(
            "clean"
            if data.get("guard_clean", True)
            else str(data.get("guard_summary") or "VIOLATED")
        ),
    )
    record.summary = [
        ("Case", case_id),
        ("Strategy", strategy),
        ("Old pin", str(data.get("old_pin", ""))),
        ("New pin", str(data.get("new_pin", ""))),
        ("Old-pin suite", str(data.get("old_pin_status") or data.get("reference_status") or "")),
        ("Post-bump suite", str(data.get("bumped_status") or "")),
        ("Held-out contract", heldout_text),
        ("Agent verdict", str(data.get("agent_status") or "—")),
        ("Guard", record.guard),
        ("Wall time", f"{data.get('wall_time_s', 0)} s"),
    ]
    record.notes = [str(note) for note in data.get("notes") or []]
    if data.get("status_note"):
        record.notes.insert(0, str(data["status_note"]))
    return record


def collect(artifacts_root: Path) -> SiteData:
    """Read every known artifact file; unreadable ones are reported, not hidden."""
    root = artifacts_root.resolve()
    site = SiteData()
    if not root.is_dir():
        site.problems.append((str(root), "artifacts directory does not exist"))
        return site

    def load(path: Path, builder: Any, *args: Any, **kwargs: Any) -> None:
        rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        try:
            data = _public_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            site.problems.append((rel, f"{type(exc).__name__}: {exc}"))
            return
        if not isinstance(data, dict):
            site.problems.append((rel, "artifact is not a JSON object"))
            return
        try:
            site.records.append(builder(path, data, rel, *args, **kwargs))
        except (KeyError, TypeError, ValueError) as exc:
            site.problems.append((rel, f"unexpected artifact shape: {type(exc).__name__}: {exc}"))

    for path in sorted(root.glob("runs/*/upgrade_report.json")):
        load(path, _from_agent)
    for path in sorted(root.glob("phase5/*/*/result.json")):
        load(path, _from_strategy, kind="phase5")
    for path in sorted(root.glob("demo/*/*/result.json")):
        load(path, _from_strategy, kind="demo")

    site.records.sort(key=lambda record: (record.recorded_at, record.slug), reverse=True)
    return site


_CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --fg: #14171c;
  --muted: #4b5563;
  --card: #f4f6f8;
  --border: #c9ced6;
  --accent: #12459e;
  --accent-soft: #e6edf9;
  --ok: #14532d;
  --ok-bg: #dcfce7;
  --warn: #713f12;
  --warn-bg: #fef3c7;
  --bad: #7f1d1d;
  --bad-bg: #fee2e2;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115;
    --fg: #eceff4;
    --muted: #b4bcc8;
    --card: #171a21;
    --border: #3a4150;
    --accent: #9cc2ff;
    --accent-soft: #1b2436;
    --ok: #bbf7d0;
    --ok-bg: #10361f;
    --warn: #fde68a;
    --warn-bg: #3a2c05;
    --bad: #fecaca;
    --bad-bg: #3d1414;
  }
}
* { box-sizing: border-box; }
html { font-size: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 1rem/1.6 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
}
a { color: var(--accent); text-decoration-thickness: 2px; }
a:hover { text-decoration-thickness: 3px; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; border-radius: 2px; }
.skip-link {
  position: absolute; left: -999px; top: 0; background: var(--bg); color: var(--fg);
  padding: .75rem 1rem; border: 2px solid var(--accent); z-index: 10;
}
.skip-link:focus { left: .5rem; top: .5rem; }
header.site { border-bottom: 1px solid var(--border); padding: 1rem 1.25rem; }
header.site .wrap { max-width: 68rem; margin: 0 auto; display: flex; flex-wrap: wrap; gap: .75rem 1.5rem; align-items: baseline; }
header.site h1 { font-size: 1.25rem; margin: 0; }
nav ul { list-style: none; display: flex; flex-wrap: wrap; gap: .25rem 1rem; margin: 0; padding: 0; }
main { max-width: 68rem; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }
h1, h2, h3 { line-height: 1.25; }
h1 { font-size: clamp(1.5rem, 4vw, 2rem); margin-top: 0; }
p.lead { color: var(--muted); max-width: 46rem; }
.banner {
  background: var(--accent-soft); border: 1px solid var(--border); border-radius: .5rem;
  padding: .75rem 1rem; margin: 0 0 1.5rem;
}
.tablewrap { overflow-x: auto; border: 1px solid var(--border); border-radius: .5rem; }
table { border-collapse: collapse; width: 100%; min-width: 44rem; }
caption { text-align: left; padding: .75rem 1rem; color: var(--muted); }
th, td { text-align: left; padding: .6rem .75rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-size: .9rem; letter-spacing: .01em; text-transform: uppercase; color: var(--muted); }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) { background: var(--card); }
.badge {
  display: inline-block; padding: .1rem .55rem; border-radius: 999px;
  font-size: .85rem; font-weight: 600; border: 1px solid transparent;
}
.badge.green { color: var(--ok); background: var(--ok-bg); border-color: var(--ok); }
.badge.warn { color: var(--warn); background: var(--warn-bg); border-color: var(--warn); }
.badge.bad { color: var(--bad); background: var(--bad-bg); border-color: var(--bad); }
.card { background: var(--card); border: 1px solid var(--border); border-radius: .5rem; padding: 1rem 1.25rem; margin: 0 0 1.5rem; }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1.25rem; margin: 0; }
dl.meta dt { font-weight: 600; }
dl.meta dd { margin: 0; overflow-wrap: anywhere; }
ol.timeline { list-style: none; margin: 0; padding: 0; }
ol.timeline li { border-left: 3px solid var(--border); padding: .4rem 0 .4rem 1rem; }
ol.timeline .step { font-weight: 600; }
ol.timeline .detail { color: var(--muted); overflow-wrap: anywhere; }
pre.proof {
  background: var(--card); border: 1px solid var(--border); border-radius: .5rem;
  padding: 1rem; overflow-x: auto; font-size: .875rem; line-height: 1.5;
}
.empty { border: 2px dashed var(--border); border-radius: .5rem; padding: 1.5rem; text-align: center; }
footer.site { border-top: 1px solid var(--border); padding: 1rem 1.25rem; color: var(--muted); }
footer.site .wrap { max-width: 68rem; margin: 0 auto; }
@media (max-width: 40rem) {
  dl.meta { grid-template-columns: 1fr; }
  dl.meta dt { margin-top: .5rem; }
  main { padding: 1.25rem 1rem 3rem; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""

_STATUS_CLASS = {
    "GREEN": "green",
    "STUCK": "warn",
    "ENV_FAIL": "bad",
    "CHEATED": "bad",
    "OVERFIT": "bad",
    "UNKNOWN": "warn",
}


def _badge(status: str) -> str:
    css = _STATUS_CLASS.get(status.upper(), "warn")
    return f'<span class="badge {css}">{html.escape(status)}</span>'


def _page(title: str, body: str, *, root: str = ".") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} - UpgradePilot recorded runs</title>
<link rel="stylesheet" href="{root}/styles.css">
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site">
  <div class="wrap">
    <h1>UpgradePilot recorded runs</h1>
    <nav aria-label="Site">
      <ul>
        <li><a href="{root}/index.html">Runs</a></li>
        <li><a href="{root}/comparison.html">Comparison</a></li>
        <li><a href="{root}/about.html">About this site</a></li>
      </ul>
    </nav>
  </div>
</header>
<main id="main">
{body}
</main>
<footer class="site"><div class="wrap">Static site generated from artifact JSON files. Every value on these pages was read from a file in the repository.</div></footer>
</body>
</html>
"""


def _runs_table(records: list[Record], *, link_prefix: str) -> str:
    rows = []
    for record in records:
        href = f"{link_prefix}{record.slug}.html"
        timestamp = record.recorded_at or "not recorded"
        rows.append(
            "<tr>"
            f'<td><a href="{html.escape(href)}">{html.escape(record.title)}</a></td>'
            f"<td>{html.escape(record.kind)}</td>"
            f"<td>{_badge(record.status)}</td>"
            f"<td>{html.escape(record.provider_label)}</td>"
            f'<td><time datetime="{html.escape(record.recorded_at)}">{html.escape(timestamp)}</time></td>'
            f"<td>{html.escape(record.suite)}</td>"
            "</tr>"
        )
    return (
        '<div class="tablewrap" role="region" aria-labelledby="runs-caption" tabindex="0">'
        "<table>"
        '<caption id="runs-caption">Recorded runs, newest first. Every row links to its evidence page.</caption>'
        '<thead><tr><th scope="col">Run</th><th scope="col">Kind</th>'
        '<th scope="col">Status</th><th scope="col">Provider</th>'
        '<th scope="col">Recorded at (UTC)</th><th scope="col">Suite</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _index(site: SiteData) -> str:
    banner = (
        '<p class="banner"><strong>This site shows recorded runs, not a live service.</strong> '
        "Each page reads committed artifact files from the repository. To run the pipeline "
        "yourself, clone the repo and run <code>upgradepilot doctor</code> then "
        "<code>upgradepilot upgrade &lt;repo&gt; --package &lt;name&gt; --to &lt;version&gt;</code> "
        "(see the README).</p>"
    )
    if not site.records:
        body = banner + (
            '<h2>Runs</h2><div class="empty"><p><strong>No recorded runs found.</strong></p>'
            "<p>The artifact directory contains no parseable result files, so this page "
            "deliberately shows nothing rather than placeholder data.</p></div>"
        )
    else:
        body = banner + "<h2>Runs</h2>" + _runs_table(site.records, link_prefix="runs/")
    if site.problems:
        items = "".join(
            f"<li><code>{html.escape(path)}</code>: {html.escape(reason)}</li>"
            for path, reason in site.problems
        )
        body += (
            '<section aria-labelledby="problems"><h2 id="problems">Unreadable artifacts</h2>'
            '<p class="lead">These files exist but could not be rendered. They are listed '
            "instead of being dropped, so the page cannot look complete when evidence is missing.</p>"
            f"<ul>{items}</ul></section>"
        )
    else:
        body += (
            '<section aria-labelledby="problems"><h2 id="problems">Unreadable artifacts</h2>'
            '<p class="lead">None: every artifact file found was parsed successfully.</p></section>'
        )
    return _page("Runs", body)


def _detail(record: Record) -> str:
    def kv_table(rows: list[tuple[str, str]]) -> str:
        return (
            '<dl class="meta">'
            + "".join(
                f"<dt>{html.escape(key)}</dt><dd>{html.escape(value or '—')}</dd>"
                for key, value in rows
            )
            + "</dl>"
        )

    meta = kv_table(
        [
            ("Status", record.status),
            ("Provider", record.provider_label),
            ("Run class", record.run_class),
            ("Recorded at", f"{record.recorded_at or 'not recorded'} ({record.timestamp_source})"),
            ("Visible suite", record.suite),
            ("Guard", record.guard),
            ("Cost", record.cost),
            ("Tokens", record.tokens),
            ("Evidence file", record.source_path),
            *record.summary,
        ]
    )
    body = [
        f'<p><a href="../index.html">Back to all runs</a></p><h1>{html.escape(record.title)}</h1>',
        f'<p>{_badge(record.status)} <span class="badge warn">Recorded run</span></p>',
        f'<div class="card"><h2>Summary</h2>{meta}</div>',
    ]
    if record.models:
        model_rows = "".join(
            f"<dt>{html.escape(role)}</dt><dd>{html.escape(name)}</dd>"
            for role, name in record.models.items()
        )
        body.append(f'<div class="card"><h2>Models</h2><dl class="meta">{model_rows}</dl></div>')
    if record.versions:
        version_rows = "".join(
            f"<dt>{html.escape(name)}</dt><dd>{html.escape(version)}</dd>"
            for name, version in sorted(record.versions.items())
        )
        body.append(
            f'<div class="card"><h2>Resolved environment</h2><dl class="meta">{version_rows}</dl></div>'
        )
    if record.steps:
        items = "".join(
            f'<li><span class="step">{html.escape(step)}</span> {_badge(status)}'
            + (f' <span class="badge warn">{html.escape(tier)}</span>' if tier else "")
            + (f'<div class="detail">{html.escape(detail)}</div>' if detail else "")
            + "</li>"
            for step, status, detail, tier in record.steps
        )
        body.append(
            f'<section aria-labelledby="timeline"><h2 id="timeline">Timeline</h2>'
            f'<ol class="timeline">{items}</ol></section>'
        )
    if record.notes:
        items = "".join(f"<li>{html.escape(note)}</li>" for note in record.notes)
        body.append(
            f'<section aria-labelledby="notes"><h2 id="notes">Notes</h2><ul>{items}</ul></section>'
        )
    if record.proof_card:
        body.append(
            '<section aria-labelledby="proof"><h2 id="proof">Proof card</h2>'
            f'<pre class="proof">{html.escape(record.proof_card)}</pre></section>'
        )
    body.append(
        f'<p><a href="../data/{html.escape(record.slug)}/artifact.json">Raw JSON evidence</a></p>'
    )
    return _page(record.title, "\n".join(body), root="..")


def _comparison(site: SiteData) -> str:
    def table(records: list[Record], caption: str, empty_label: str) -> str:
        if not records:
            return (
                f'<div class="empty"><p><strong>No {html.escape(empty_label)} recorded yet.</strong></p>'
                "<p>This table is generated from result files; nothing is estimated.</p></div>"
            )
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(record.title)}</td>"
            f"<td>{html.escape(record.provider_label)}</td>"
            f"<td>{_badge(record.status)}</td>"
            f"<td>{html.escape(record.suite or '—')}</td>"
            f"<td>{html.escape(record.cost)}</td>"
            f"<td>{html.escape(record.tokens)}</td>"
            f'<td><time datetime="{html.escape(record.recorded_at)}">{html.escape(record.recorded_at or "not recorded")}</time></td>'
            "</tr>"
            for record in records
        )
        return (
            '<div class="tablewrap" role="region" tabindex="0">'
            f"<table><caption>{html.escape(caption)}</caption>"
            '<thead><tr><th scope="col">Run</th><th scope="col">Provider</th>'
            '<th scope="col">Status</th><th scope="col">Suite</th><th scope="col">Cost</th>'
            '<th scope="col">Tokens</th><th scope="col">Recorded at (UTC)</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )

    benchmark = [r for r in site.records if r.kind == "phase5"]
    demo = [r for r in site.records if r.kind == "demo"]
    body = [
        "<h1>Comparison</h1>",
        '<p class="lead">Benchmark rows and demo-case rows are kept separate on purpose: the '
        "demo case is self-written and is not a benchmark result.</p>",
        '<section aria-labelledby="bench"><h2 id="bench">Benchmark strategies (Phase 5)</h2>',
        table(
            benchmark,
            "Real runs of each strategy on the same pinned checkout.",
            "benchmark strategies",
        ),
        "</section>",
        '<section aria-labelledby="demo"><h2 id="demo">Demo case (not a benchmark)</h2>',
        table(
            demo,
            "invoicekit, pydantic 1.10.22 to 2.12.4, plus the external held-out contract.",
            "demo-case strategies",
        ),
        "</section>",
    ]
    return _page("Comparison", "\n".join(body))


def _about(site: SiteData) -> str:
    providers = sorted({record.provider for record in site.records if record.provider})
    provider_text = (
        ", ".join(_PROVIDER_NAMES.get(p, p) for p in providers) or "no provider recorded"
    )
    body = f"""
<h1>About this site</h1>
<p class="lead">A static rendering of the run evidence committed in this repository. There is no
server, no database, and no JavaScript: <code>upgradepilot site build</code> reads the artifact
JSON files and writes these pages.</p>
<h2>What a recorded run is</h2>
<p>Each page corresponds to one result file: an agent upgrade report
(<code>artifacts/runs/</code>), a Phase 5 strategy result
(<code>artifacts/phase5/</code>), or a demo-case result
(<code>artifacts/demo/</code>). Statuses, counts, tokens, and timestamps are copied from those
files; the timestamp comes from the run id or the result file itself and the page says which.</p>
<h2>Providers</h2>
<p>Recorded providers on this build: <strong>{html.escape(provider_text)}</strong>.
Runs are labelled with the provider that produced them. An NVIDIA NIM run is a development run
and is never presented as a Nebius Token Factory run.</p>
<h2>Run it locally</h2>
<pre class="proof">git clone &lt;repository&gt;
cd upgradepilot
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[web,dev]"
copy .env.example .env   # add keys
upgradepilot doctor
upgradepilot upgrade &lt;repo&gt; --package &lt;name&gt; --to &lt;version&gt;</pre>
<h2>Honest limits</h2>
<ul>
<li>The hosted site shows <strong>recorded runs</strong>, not a live service.</li>
<li>An empty table means no result file exists; it never means "nothing failed".</li>
<li>Unreadable artifact files are listed on the home page rather than hidden.</li>
</ul>
"""
    return _page("About", body)


def build_site(artifacts_root: Path, out_dir: Path) -> SiteData:
    """Render the site into ``out_dir`` and copy the raw evidence it cites."""
    site = collect(artifacts_root)
    out = out_dir.resolve()
    (out / "runs").mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "styles.css").write_text(_CSS.strip() + "\n", encoding="utf-8")

    for record in site.records:
        source = artifacts_root / record.source_path
        data_dir = out / "data" / record.slug
        data_dir.mkdir(parents=True, exist_ok=True)
        public_artifact = _public_json(json.loads(source.read_text(encoding="utf-8")))
        (data_dir / "artifact.json").write_text(
            json.dumps(public_artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        proof_path = source.parent / "proof_card.md"
        if proof_path.is_file():
            record.proof_card = _public_text(
                proof_path.read_text(encoding="utf-8", errors="replace")
            )
            (data_dir / "proof_card.md").write_text(record.proof_card, encoding="utf-8")
        (out / "runs" / f"{record.slug}.html").write_text(_detail(record), encoding="utf-8")

    (out / "index.html").write_text(_index(site), encoding="utf-8")
    (out / "comparison.html").write_text(_comparison(site), encoding="utf-8")
    (out / "about.html").write_text(_about(site), encoding="utf-8")
    return site
