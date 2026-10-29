"""Run orchestration for the Phase 6 web UI.

One :class:`RunController` per app instance owns:

- listing and reading run artifacts under ``artifacts/runs``;
- starting a single background upgrade run (``POST /api/runs``);
- streaming a run's ``events.jsonl`` as Server-Sent Events, replaying past
  events first and then tailing while the run is still executing;
- rendering the benchmark results table from raw Phase 2 artifacts.

The controller never runs two upgrade runs at the same time: a run owns real
venvs, subprocesses, and API spend, so a second start returns 409 until the
first finishes.
"""

from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from upgradepilot.agent import UpgradeReport, UpgradeRequest, run_upgrade
from upgradepilot.config import Settings, load_settings_for_run, repo_root
from upgradepilot.prepare import PreparationError, prepare_target
from upgradepilot.run_ledger import new_run_id

#: How often the SSE generator checks for new events while a run is active.
POLL_INTERVAL_S = 0.2

#: Emit an SSE comment (keep-alive) every N poll iterations (~every 5s).
KEEPALIVE_EVERY = 25

_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class StartRunRequest(BaseModel):
    """Body of ``POST /api/runs``."""

    repo: str
    package: str = Field(min_length=1)
    to_version: str = Field(min_length=1)
    max_iterations: int = Field(default=5, ge=1, le=20)
    held_out_fraction: float = Field(default=0.25, ge=0.01, le=0.99)


class RunSummary(BaseModel):
    """One row in the runs table."""

    run_id: str
    status: str
    package: str = ""
    to_version: str = ""
    iterations: int | None = None
    guard_clean: bool | None = None
    active: bool = False
    error: str | None = None


class RunDetail(BaseModel):
    """Full detail for one run: report, proof card, setup record, error."""

    run_id: str
    active: bool = False
    report: UpgradeReport | None = None
    proof_card: str | None = None
    setup: dict[str, Any] | None = None
    error: str | None = None


class StartRunResponse(BaseModel):
    """Accepted-run response; stream ``/api/runs/{run_id}/events`` live."""

    run_id: str


class BenchResults(BaseModel):
    """Benchmark table rows plus the markdown rendering of the same data."""

    available: bool = False
    rows: list[dict[str, Any]] = Field(default_factory=list)
    markdown: str = ""


class RunBusyError(RuntimeError):
    """Another upgrade run is already in progress."""


class _ActiveRun:
    """Bookkeeping for the one run the controller currently owns."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.error: str | None = None
        self.thread: threading.Thread | None = None


class RunController:
    """Reads run artifacts, starts runs, and streams their event ledgers."""

    def __init__(
        self,
        artifacts_root: Path,
        *,
        bench_dir: Path | None = None,
        bench_artifacts: Path | None = None,
    ) -> None:
        self.artifacts_root = artifacts_root
        self.bench_dir = bench_dir if bench_dir is not None else repo_root() / "bench"
        self.bench_artifacts = (
            bench_artifacts
            if bench_artifacts is not None
            else repo_root() / "artifacts" / "phase2"
        )
        self._active: _ActiveRun | None = None
        self._lock = threading.Lock()

    # -- read side -------------------------------------------------------

    @property
    def active_run_id(self) -> str | None:
        """Run id currently executing, if any."""
        return self._active.run_id if self._active is not None else None

    def resolve_run_dir(self, run_id: str) -> Path:
        """Validate ``run_id`` and return its artifact directory.

        Raises ``ValueError`` for anything that is not a plain run id, so a
        crafted id can never escape ``artifacts_root``.
        """
        if not _SAFE_RUN_ID.fullmatch(run_id) or ".." in run_id:
            raise ValueError(f"invalid run id: {run_id!r}")
        return self.artifacts_root / run_id

    def list_runs(self) -> list[RunSummary]:
        """Newest-first summaries built from report/setup/error artifacts."""
        if not self.artifacts_root.is_dir():
            return []
        active_id = self.active_run_id
        summaries: list[RunSummary] = []
        for run_dir in sorted(self.artifacts_root.iterdir(), reverse=True):
            if not run_dir.is_dir() or not _SAFE_RUN_ID.fullmatch(run_dir.name):
                continue
            report = self._read_report(run_dir)
            active = run_dir.name == active_id
            error = self._read_error(run_dir)
            if report is not None:
                status = report.status.value
                summaries.append(
                    RunSummary(
                        run_id=run_dir.name,
                        status=status,
                        package=report.request.package,
                        to_version=report.request.to_version,
                        iterations=report.iterations_used,
                        guard_clean=report.guard_clean,
                        active=active,
                        error=error,
                    )
                )
                continue
            setup = self._read_json(run_dir / "setup.json")
            summaries.append(
                RunSummary(
                    run_id=run_dir.name,
                    status="failed" if error else ("running" if active else "unknown"),
                    package=str(setup.get("package", "")) if setup else "",
                    to_version=str(setup.get("to_version", "")) if setup else "",
                    active=active,
                    error=error,
                )
            )
        return summaries

    def get_run(self, run_id: str) -> RunDetail:
        """Full run detail: parsed report, proof card, setup, and error."""
        run_dir = self.resolve_run_dir(run_id)
        report = self._read_report(run_dir)
        proof_card_path = run_dir / "proof_card.md"
        proof_card = (
            proof_card_path.read_text(encoding="utf-8") if proof_card_path.is_file() else None
        )
        return RunDetail(
            run_id=run_id,
            active=self.active_run_id == run_id,
            report=report,
            proof_card=proof_card,
            setup=self._read_json(run_dir / "setup.json"),
            error=self._read_error(run_dir),
        )

    def bench_results(self) -> BenchResults:
        """Rows and markdown for the benchmark table, if the bench exists."""
        module_path = self.bench_dir / "results_table.py"
        if not module_path.is_file():
            return BenchResults(available=False)
        spec = importlib.util.spec_from_file_location("bench.results_table", module_path)
        if spec is None or spec.loader is None:
            return BenchResults(available=False)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows: list[dict[str, Any]] = module.build_results_table_json(self.bench_artifacts)
        markdown: str = module.build_results_table(self.bench_artifacts)
        return BenchResults(available=True, rows=rows, markdown=markdown)

    # -- write side ------------------------------------------------------

    def start_run(self, request: StartRunRequest) -> str:
        """Kick off one background run and return its id immediately.

        Raises :class:`ConfigError` when API keys are missing (surfaced as
        HTTP 422) and :class:`RunBusyError` when a run is already active
        (surfaced as HTTP 409).
        """
        if not self._lock.acquire(blocking=False):
            active = self.active_run_id or "unknown"
            raise RunBusyError(f"run {active} is already in progress")
        try:
            settings = load_settings_for_run()
            if not Path(request.repo).is_dir():
                raise PreparationError(f"target source is not a directory: {request.repo}")
        except BaseException:
            self._lock.release()
            raise

        state = _ActiveRun(new_run_id())
        self._active = state
        thread = threading.Thread(
            target=self._worker,
            args=(state, request, settings),
            name=f"upgradepilot-web-{state.run_id}",
            daemon=True,
        )
        state.thread = thread
        thread.start()
        return state.run_id

    def _worker(self, state: _ActiveRun, request: StartRunRequest, settings: Settings) -> None:
        """Background thread: prepare the checkout, then run the agent loop."""
        try:
            prepared = prepare_target(
                Path(request.repo).resolve(),
                self.artifacts_root,
                request.package,
                request.to_version,
                run_id=state.run_id,
                verify_old_pin=True,
                pytest_timeout_s=float(settings.pytest_timeout_seconds),
            )
            run_upgrade(
                request=UpgradeRequest(
                    repo=request.repo,
                    package=request.package,
                    to_version=request.to_version,
                ),
                repo=prepared.repo,
                venv=prepared.venv,
                settings=settings,
                artifacts_dir=self.artifacts_root,
                run_id=prepared.run_id,
                max_iterations=request.max_iterations,
                held_out_fraction=request.held_out_fraction,
                ledger=prepared.ledger,
                reference_outcome=prepared.reference_outcome,
                versions=prepared.versions,
            )
        except Exception as exc:
            state.error = f"{type(exc).__name__}: {exc}"
            try:
                run_dir = self.artifacts_root / state.run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "error.json").write_text(
                    json.dumps({"error": state.error}), encoding="utf-8"
                )
            except OSError:
                pass
        finally:
            self._active = None
            self._lock.release()

    # -- SSE -------------------------------------------------------------

    def events(self, run_id: str) -> Iterator[str]:
        """Replay ``events.jsonl`` from the start, then tail until finished.

        Emits one SSE ``data:`` message per ledger line, then ``event: done``
        when the run is over (plus ``event: run_error`` first if it failed).
        Implemented as a plain sync generator so FastAPI runs it in its own
        threadpool — no shared event-loop state between requests.
        """
        run_dir = self.resolve_run_dir(run_id)
        path = run_dir / "events.jsonl"
        offset = 0
        pending = b""
        polls = 0
        while True:
            chunk = b""
            try:
                with path.open("rb") as handle:
                    handle.seek(offset)
                    chunk = handle.read()
                    offset = handle.tell()
            except FileNotFoundError:
                pass
            if chunk:
                pending += chunk
                *lines, pending = pending.split(b"\n")
                for line in lines:
                    if line.strip():
                        yield _sse_data(line.decode("utf-8", errors="replace"))
                polls = 0
                continue

            if self.active_run_id == run_id:
                polls += 1
                if polls % KEEPALIVE_EVERY == 0:
                    yield ": ping\n\n"
                time.sleep(POLL_INTERVAL_S)
                continue

            # The run is over: emit any trailing partial line, then finish.
            if pending.strip():
                yield _sse_data(pending.decode("utf-8", errors="replace"))
                pending = b""
            error = self._read_error(run_dir)
            if error:
                yield _sse_event("run_error", json.dumps({"error": error}))
            yield _sse_event("done", json.dumps({"run_id": run_id}))
            return

    # -- helpers ---------------------------------------------------------

    def _read_report(self, run_dir: Path) -> UpgradeReport | None:
        path = run_dir / "upgrade_report.json"
        if not path.is_file():
            return None
        try:
            return UpgradeReport.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _read_error(self, run_dir: Path) -> str | None:
        payload = self._read_json(run_dir / "error.json")
        if payload is None:
            return None
        error = payload.get("error")
        return str(error) if error else None


def _sse_data(payload: str) -> str:
    """One SSE message with an unnamed (default ``message``) event."""
    return f"data: {payload}\n\n"


def _sse_event(event: str, payload: str) -> str:
    """One SSE message with an explicit event name."""
    return f"event: {event}\ndata: {payload}\n\n"


__all__ = [
    "BenchResults",
    "RunBusyError",
    "RunController",
    "RunDetail",
    "RunSummary",
    "StartRunRequest",
    "StartRunResponse",
]
