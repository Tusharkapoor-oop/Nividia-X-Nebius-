"""FastAPI application factory: Phase 6 web UI.

Endpoints
---------
- ``GET  /``                          accessible single-page UI
- ``GET  /healthz``                   liveness probe (Phase 0 contract)
- ``GET  /api/runs``                  run summaries, newest first
- ``GET  /api/runs/{run_id}``         report + proof card + setup + error
- ``GET  /api/runs/{run_id}/events``  SSE replay, then live tail while running
- ``POST /api/runs``                  start one background upgrade run
- ``GET  /api/bench``                 benchmark results from raw artifacts

Only one upgrade run executes at a time; a second ``POST`` while one is
active returns 409. The target repo is never modified: runs work on a
disposable checkout under the run's artifact directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse

from upgradepilot import __version__
from upgradepilot.config import ConfigError
from upgradepilot.prepare import PreparationError
from upgradepilot.web.runs import (
    BenchResults,
    RunBusyError,
    RunController,
    RunDetail,
    RunSummary,
    StartRunRequest,
    StartRunResponse,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    *,
    artifacts_dir: Path | None = None,
    bench_dir: Path | None = None,
    bench_artifacts: Path | None = None,
) -> FastAPI:
    """Create the FastAPI app. Requires the ``web`` extra.

    ``artifacts_dir`` defaults to ``./artifacts/runs`` (the CLI default) and
    the bench paths default to this repository's ``bench/`` and
    ``artifacts/phase2/``; tests pass explicit paths.
    """
    from fastapi import FastAPI

    fastapi_app = FastAPI(
        title="UpgradePilot",
        version=__version__,
        docs_url="/docs",
    )
    controller = RunController(
        Path(artifacts_dir) if artifacts_dir is not None else Path("artifacts/runs"),
        bench_dir=bench_dir,
        bench_artifacts=bench_artifacts,
    )
    fastapi_app.state.run_controller = controller

    @fastapi_app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @fastapi_app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    @fastapi_app.get("/api/runs", response_model=list[RunSummary])
    def list_runs() -> list[RunSummary]:
        return controller.list_runs()

    @fastapi_app.get("/api/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: str) -> RunDetail:
        try:
            return controller.get_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @fastapi_app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str) -> Response:
        try:
            controller.resolve_run_dir(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return StreamingResponse(
            controller.events(run_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @fastapi_app.post("/api/runs", response_model=StartRunResponse, status_code=202)
    def start_run(request: StartRunRequest) -> StartRunResponse:
        try:
            run_id = controller.start_run(request)
        except RunBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except PreparationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return StartRunResponse(run_id=run_id)

    @fastapi_app.get("/api/bench", response_model=BenchResults)
    def bench() -> BenchResults:
        try:
            return controller.bench_results()
        except OSError:
            raise HTTPException(status_code=503, detail="bench artifacts unreadable") from None

    if _STATIC_DIR.is_dir():
        from fastapi.staticfiles import StaticFiles

        fastapi_app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return fastapi_app


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Block serving the app with uvicorn until interrupted."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError('The web extra is not installed. Run: pip install -e ".[web]"') from exc

    uvicorn.run(
        "upgradepilot.web.app:create_app",
        factory=True,
        host=host,
        port=port,
    )
