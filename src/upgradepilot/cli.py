"""CLI entry points: doctor / upgrade / bench / catalog / web.

Doctor never requires API keys and never prints a full key. Strict key checks
belong to run entry points. No check reports success unless the underlying
call actually succeeded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from upgradepilot import __version__
from upgradepilot.catalog import Catalog, CatalogError, fetch_catalog
from upgradepilot.config import ConfigError, Settings, load_settings, load_settings_for_run
from upgradepilot.secrets import mask_secret
from upgradepilot.tiers import ModelTier, TierConfigError, build_tiers
from upgradepilot.web.app import run_server

app = typer.Typer(add_completion=False, help="UpgradePilot CLI")
console = Console()


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"check": name, "ok": ok, "detail": detail}


def _git_version() -> str:
    try:
        completed = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return f"unavailable: {exc}"
    if completed.returncode != 0:
        return f"git exit {completed.returncode}"
    return completed.stdout.strip()[:60]


def _tier_detail(tiers: dict[str, ModelTier]) -> str:
    parts: list[str] = []
    for tier in tiers.values():
        if tier.is_priced:
            assert tier.input_price_per_m is not None  # narrowed by is_priced
            assert tier.output_price_per_m is not None  # narrowed by is_priced
            parts.append(
                f"{tier.role}: {tier.model_id} "
                f"in=${tier.input_price_per_m:.2f}/M out=${tier.output_price_per_m:.2f}/M "
                f"ctx={tier.context_window}"
            )
        else:
            parts.append(f"{tier.role}: {tier.model_id} unpriced (provider publishes no catalog)")
    return "; ".join(parts)


def _print_tier_table(title: str, tiers: dict[str, ModelTier]) -> None:
    """Render one tier table; unpriced tiers say so instead of showing $0."""
    table = Table(title=title)
    table.add_column("Tier")
    table.add_column("model_id")
    table.add_column("$ in / M")
    table.add_column("$ out / M")
    table.add_column("ctx")
    for role, tier in tiers.items():
        if tier.is_priced:
            assert tier.input_price_per_m is not None  # narrowed by is_priced
            assert tier.output_price_per_m is not None  # narrowed by is_priced
            price_in = f"{tier.input_price_per_m:.2f}"
            price_out = f"{tier.output_price_per_m:.2f}"
        else:
            price_in = "n/a"
            price_out = "n/a"
        table.add_row(
            role,
            tier.model_id,
            price_in,
            price_out,
            "n/a" if tier.context_window is None else str(tier.context_window),
        )
    console.print(table)


def _doctor_checks(settings: Settings) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "python>=3.11",
            sys.version_info[:2] >= (3, 11),
            ".".join(str(part) for part in sys.version_info[:3]),
        )
    )
    git_version = _git_version()
    checks.append(_check("git", "git version" in git_version, git_version))

    checks.append(
        _check(
            "keys",
            settings.keys_configured,
            f"provider={settings.llm_provider} "
            f"{settings.active_key_name}={mask_secret(settings.active_api_key)} "
            f"TAVILY={mask_secret(settings.tavily_api_key)}",
        )
    )

    checks.append(
        _check(
            "hackathon mode",
            True,
            "DEV (nvidia-nim): submission requires LLM_PROVIDER=tokenfactory "
            "and a real Nebius Token Factory call"
            if settings.llm_provider == "nvidia-nim"
            else "SUBMISSION PATH (tokenfactory)",
        )
    )

    catalog: Catalog | None = None
    if settings.llm_provider == "tokenfactory":
        try:
            catalog = fetch_catalog(settings)
            checks.append(
                _check("tokenfactory catalog", True, f"{len(catalog.models)} models listed")
            )
        except CatalogError as exc:
            checks.append(_check("tokenfactory catalog", False, str(exc)[:240]))

    tiers: dict[str, ModelTier] | None = None
    if settings.llm_provider == "nvidia-nim":
        # The provider has no pricing catalog; tier ids are validated against
        # the provider at first call. Refusing to price them is honest, not a
        # failure. USD cap is replaced by the request cap.
        from upgradepilot.tiers import build_tiers_unpriced

        try:
            tiers = build_tiers_unpriced(settings)
            checks.append(
                _check(
                    "tier mapping",
                    True,
                    _tier_detail(tiers) + f"; cap=requests/{settings.max_llm_calls_per_run}",
                )
            )
        except TierConfigError as exc:
            checks.append(_check("tier mapping", False, str(exc)[:240]))
    elif catalog is not None:
        try:
            tiers = build_tiers(settings, catalog)
            checks.append(_check("tier mapping", True, _tier_detail(tiers)))
        except TierConfigError as exc:
            checks.append(_check("tier mapping", False, str(exc)[:240]))

    if not settings.active_api_key:
        chat_label = "llm chat" if settings.llm_provider == "nvidia-nim" else "tokenfactory chat"
        checks.append(_check(chat_label, True, "skipped (no key)"))
    elif settings.llm_provider == "nvidia-nim":
        # doctor's live chat probe runs for the provider actually configured;
        # it still budgets conservatively (max_tokens=96).
        from upgradepilot.llm import LLMClient

        tier: ModelTier | None = tiers["cheap"] if tiers is not None else None
        if tier is None:
            checks.append(_check("llm chat", False, "skipped: tier mapping unavailable"))
        else:
            client: LLMClient | None = None
            try:
                client = LLMClient(settings)
                response = client.chat(
                    [{"role": "user", "content": "Reply with exactly: OK"}],
                    tier,
                    max_tokens=96,
                )
                checks.append(
                    _check(
                        "llm chat",
                        "OK" in response.content,
                        f"{tier.model_id} in={response.usage.prompt_tokens} "
                        f"out={response.usage.completion_tokens} "
                        f"finish={response.finish_reason!r} "
                        f"content={response.content[:24]!r} "
                        f"(unpriced provider; cost not reported)",
                    )
                )
            except Exception as exc:  # doctor must report, never traceback
                checks.append(
                    _check(
                        "llm chat",
                        False,
                        type(exc).__name__ + ": " + str(exc)[:160],
                    )
                )
            finally:
                if client is not None:
                    client.close()
    elif tiers is None:
        checks.append(
            _check(
                "tokenfactory chat",
                False,
                "skipped: live catalog unavailable, so no call can be priced safely",
            )
        )
    else:
        from upgradepilot.llm import LLMClient

        tf_tier = tiers["cheap"]
        tf_client: LLMClient | None = None
        try:
            tf_client = LLMClient(settings)
            response = tf_client.chat(
                [{"role": "user", "content": "Reply with exactly: OK"}],
                tf_tier,
                max_tokens=32,
            )
            checks.append(
                _check(
                    "tokenfactory chat",
                    "OK" in response.content,
                    f"{tf_tier.model_id} in={response.usage.prompt_tokens} "
                    f"out={response.usage.completion_tokens} "
                    f"content={response.content[:24]!r}",
                )
            )
        except Exception as exc:  # doctor must report, never traceback
            checks.append(
                _check(
                    "tokenfactory chat",
                    False,
                    type(exc).__name__ + ": " + str(exc)[:160],
                )
            )
        finally:
            if tf_client is not None:
                tf_client.close()

    if not settings.tavily_api_key:
        checks.append(_check("tavily search", True, "skipped (no key)"))
    else:
        from upgradepilot.research import TavilyClient

        tavily = TavilyClient(settings)
        try:
            result = tavily.search("pydantic 2.0 migration guide", max_results=1)
            checks.append(
                _check(
                    "tavily search",
                    bool(result.results),
                    f"{len(result.results)} result(s), credits={result.credits_used}",
                )
            )
        except Exception as exc:  # doctor must report, never traceback
            checks.append(
                _check(
                    "tavily search",
                    False,
                    type(exc).__name__ + ": " + str(exc)[:160],
                )
            )
        finally:
            tavily.close()

    return checks


def _doctor(json_output: bool) -> int:
    settings = load_settings()
    checks = _doctor_checks(settings)
    passed = all(check["ok"] for check in checks)

    if json_output:
        payload = {"version": __version__, "checks": checks, "pass": passed}
        console.print_json(json.dumps(payload))
        return 0 if passed else 1

    table = Table(title=f"UpgradePilot doctor v{__version__}")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for check in checks:
        table.add_row(
            check["check"],
            "[green]OK[/green]" if check["ok"] else "[red]FAIL[/red]",
            check["detail"],
        )
    console.print(table)
    return 0 if passed else 1


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="machine-readable output"),
) -> None:
    """Environment, keys, catalog, tier pricing, and live API checks."""
    raise typer.Exit(_doctor(json_output))


@app.command()
def upgrade(
    repo: Path = typer.Argument(
        ..., exists=True, readable=True, help="target repo (copied to a disposable workdir)"
    ),
    package: str = typer.Option(..., "--package", "-p", help="package to upgrade"),
    to_version: str = typer.Option(..., "--to", help="target version, e.g. 2.9.0"),
    max_iterations: int = typer.Option(
        5, "--max-iterations", "-i", min=1, max=20, help="maximum repair iterations"
    ),
    held_out_fraction: float = typer.Option(
        0.25, "--held-out", min=0.01, max=0.99, help="share of tests to hold out"
    ),
    artifacts_dir: Path = typer.Option(
        Path("artifacts/runs"), "--artifacts-dir", help="artifacts output directory"
    ),
    json_output: bool = typer.Option(False, "--json", help="output JSON report"),
) -> None:
    """Prepare a disposable checkout, install the target version, then repair.

    The target path is never patched in place: setup copies it under the run
    artifacts directory and installs ``package==to_version`` in a fresh venv.
    """
    from upgradepilot.agent import AgentStep, run_upgrade
    from upgradepilot.pipeline import UpgradeRequest
    from upgradepilot.prepare import PreparationError, prepare_target
    from upgradepilot.verify import VerifyStatus

    try:
        settings = load_settings_for_run()
    except ConfigError as exc:
        if json_output:
            console.print_json(json.dumps({"status": "ENV_FAIL", "error": str(exc)}))
        else:
            console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(1) from exc

    source = repo.resolve()
    artifacts_root = artifacts_dir.resolve()
    request = UpgradeRequest(repo=str(source), package=package, to_version=to_version)

    if not json_output:
        console.print(
            f"[bold cyan]UpgradePilot:[/] preparing a disposable checkout of "
            f"[bold]{source}[/] for [bold]{package}=={to_version}[/]"
        )

    try:
        prepared = prepare_target(
            source,
            artifacts_root,
            package,
            to_version,
            verify_old_pin=True,
            pytest_timeout_s=float(settings.pytest_timeout_seconds),
        )
    except PreparationError as exc:
        if json_output:
            console.print_json(json.dumps({"status": "ENV_FAIL", "error": str(exc)}))
        else:
            console.print(f"[red]Setup failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    def on_step(step: AgentStep) -> None:
        if json_output:
            return
        style = "green" if step.status == "ok" else ("yellow" if step.status == "start" else "red")
        tier_tag = f" [{step.tier}]" if step.tier else ""
        console.print(f"[{style}]-[/{style}] [bold]{step.step}[/bold]{tier_tag}: {step.detail}")

    if not json_output:
        console.print(
            f"[bold cyan]UpgradePilot:[/] Upgrading [bold]{package}[/] to "
            f"[bold]{to_version}[/] in {prepared.repo.root}"
        )

    report = run_upgrade(
        request=request,
        repo=prepared.repo,
        venv=prepared.venv,
        settings=settings,
        artifacts_dir=artifacts_root,
        run_id=prepared.run_id,
        max_iterations=max_iterations,
        held_out_fraction=held_out_fraction,
        ledger=prepared.ledger,
        step_callback=on_step,
        reference_outcome=prepared.reference_outcome,
        versions=prepared.versions,
    )

    if json_output:
        console.print_json(json.dumps(report.model_dump(mode="json")))
    else:
        status_style = "green" if report.status is VerifyStatus.GREEN else "red"
        table = Table(title=f"UpgradePilot Result: {package} -> {to_version}")
        table.add_column("Property", style="bold")
        table.add_column("Value")
        table.add_row("Final Status", f"[{status_style}]{report.status.value}[/{status_style}]")
        table.add_row("Iterations", str(report.iterations_used))
        if report.cost.fully_priced:
            cost_str = f"${report.cost.total_cost_usd:.4f}"
        else:
            cost_str = (
                f"Unpriced ({report.cost.unpriced_calls} of {report.cost.calls} calls; "
                "provider publishes no catalog price)"
            )
        table.add_row("Cost", cost_str)
        table.add_row(
            "Tokens",
            f"{report.cost.total_prompt_tokens} in / "
            f"{report.cost.total_completion_tokens} out "
            f"({report.cost.total_tokens} total)",
        )
        proof_card = next(
            (path for path in reversed(report.artifacts) if path.endswith("proof_card.md")),
            None,
        )
        if proof_card:
            table.add_row("Proof Card", proof_card)
        table.add_row("Setup Record", str(prepared.setup_path))
        console.print(table)

    raise typer.Exit(0 if report.status is VerifyStatus.GREEN else 1)


@app.command()
def bench(
    case: str | None = typer.Option(None, "--case", "-c", help="Verify one benchmark case by id"),
    all_cases: bool = typer.Option(
        False, "--all", "-a", help="Run every candidate case in bench/cases.json"
    ),
    list_cases: bool = typer.Option(
        False, "--list", "-l", help="List all benchmark cases and their statuses"
    ),
    results: bool = typer.Option(
        False, "--results", "-r", help="Print the results table from raw JSON artifacts"
    ),
) -> None:
    """Run the held-out benchmark suite (Phase 5).

    Verifies candidate cases from bench/cases.json by cloning the repo,
    building a clean venv, running pytest pre/post dependency bump, and
    recording real evidence under artifacts/phase2/<case>/.
    """
    import importlib.util
    from types import ModuleType

    repo_root = Path(__file__).resolve().parents[2]
    cases_path = repo_root / "bench" / "cases.json"

    _bench_dir = repo_root / "bench"

    def _load_bench_module(name: str, file_name: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"bench.{name}", _bench_dir / file_name)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    _results_table = _load_bench_module("results_table", "results_table.py")
    build_results_table = _results_table.build_results_table

    if list_cases or (not case and not all_cases and not results):
        import json

        data = json.loads(cases_path.read_text(encoding="utf-8"))
        table = Table(title="Benchmark Cases")
        table.add_column("Case ID", style="bold")
        table.add_column("Status")
        table.add_column("Dependency")
        table.add_column("Old → New")
        for c in data["cases"]:
            table.add_row(
                c["id"],
                c["status"],
                f"{c['dep']} {c['old_pin']} → {c['new_pin']}",
            )
        console.print(table)
        raise typer.Exit(0)

    if results:
        md = build_results_table(repo_root / "artifacts" / "phase2")
        console.print(md)
        raise typer.Exit(0)

    spec = importlib.util.spec_from_file_location(
        "bench.verify_case", repo_root / "bench" / "verify_case.py"
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    cases = mod._load_cases()

    if case:
        if case not in cases:
            console.print(f"[red]unknown case {case!r}[/red]")
            raise typer.Exit(2)
        codes = [mod.run_case(cases[case])]
    elif all_cases:
        codes = [mod.run_case(c) for c in cases.values() if c["status"] == "candidate"]
    else:
        console.print("[red]specify --case <id>, --all, --list, or --results[/red]")
        raise typer.Exit(2)

    exit_code = max(codes) if codes else 0
    raise typer.Exit(exit_code)


@app.command()
def catalog() -> None:
    """Fetch the live catalog and print the configured tier mapping."""
    settings = load_settings()
    if settings.llm_provider == "nvidia-nim":
        from upgradepilot.tiers import build_tiers_unpriced

        tiers = build_tiers_unpriced(settings)
        _print_tier_table("nvidia-nim tiers (unpriced: provider publishes no catalog)", tiers)
        return
    try:
        live_catalog = fetch_catalog(settings)
        tiers = build_tiers(settings, live_catalog)
    except (CatalogError, TierConfigError) as exc:
        console.print(f"[red]{type(exc).__name__}:[/red] {exc}")
        raise typer.Exit(1) from exc

    _print_tier_table(f"live tokenfactory catalog - {len(live_catalog.models)} models", tiers)


site_app = typer.Typer(add_completion=False, help="Static recorded-runs site (GitHub Pages)")
app.add_typer(site_app, name="site")


@site_app.command("build")
def site_build(
    out: Path | None = typer.Option(None, "--out", help="output directory (default: docs/)"),
    artifacts: Path | None = typer.Option(
        None, "--artifacts", help="artifact root (default: artifacts/)"
    ),
) -> None:
    """Render the static site from artifact JSON files only.

    Every page is generated from a result file; an unreadable artifact is
    reported and listed on the home page rather than skipped silently.
    """
    from upgradepilot.config import repo_root
    from upgradepilot.site import build_site

    root = repo_root()
    site = build_site(artifacts or root / "artifacts", out or root / "docs")
    target = out or root / "docs"
    console.print(
        f"wrote {target}: {len(site.records)} recorded run(s), "
        f"{len(site.problems)} unreadable artifact(s)"
    )
    for path, reason in site.problems:
        console.print(f"[yellow]unreadable[/yellow] {path}: {reason}")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="listen host"),
    port: int = typer.Option(8000, min=1, max=65535, help="listen port"),
) -> None:
    """Start the local FastAPI web app."""
    run_server(host=host, port=port)


def main() -> None:  # pragma: no cover - entry point wiring
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
