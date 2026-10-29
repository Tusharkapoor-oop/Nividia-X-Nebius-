"""Offline unit tests for Phase 4 agent loop (triage, research, patch, verify, certify)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from upgradepilot.agent import (
    AgentStep,
    TriageResult,
    UpgradeReport,
    _run_patch,
    _run_research,
    _run_triage,
    list_source_files,
    proof_card_markdown,
    run_upgrade,
)
from upgradepilot.config import Settings
from upgradepilot.editing import EditApplied, EditsPayload, PatchEdit
from upgradepilot.harness import RepoWorkdir, VenvInfo
from upgradepilot.llm import LLMClient
from upgradepilot.models import PytestResult
from upgradepilot.pipeline import UpgradeRequest
from upgradepilot.research import TavilyClient, TavilyHit, TavilySearchResult
from upgradepilot.run_ledger import RunLedger
from upgradepilot.tiers import ModelTier
from upgradepilot.verify import VerifyOutcome, VerifyStatus

CHEAP_TIER = ModelTier(
    role="cheap",
    model_id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    context_window=262144,
    input_price_per_m=0.06,
    output_price_per_m=0.24,
    max_tokens=512,
)

DEFAULT_TIER = ModelTier(
    role="default",
    model_id="nvidia/Nemotron-3_5-Lightning",
    context_window=1048576,
    input_price_per_m=0.06,
    output_price_per_m=0.24,
    max_tokens=4096,
)

STRONG_TIER = DEFAULT_TIER.model_copy(update={"role": "strong"})
TIERS = {"cheap": CHEAP_TIER, "default": DEFAULT_TIER, "strong": STRONG_TIER}


def _mock_llm(responses: list[str]) -> LLMClient:
    """Create an LLM client that returns sequenced canned responses."""
    call_idx = 0

    def fake_post(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        content = responses[min(call_idx, len(responses) - 1)]
        call_idx += 1
        return httpx.Response(
            200,
            json={
                "id": "cmpl-mock",
                "model": "nvidia/nemotron",
                "choices": [
                    {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(fake_post))
    return LLMClient(
        Settings(
            nebius_api_key="mock",
            tavily_api_key="mock",
            token_cost_cap_usd=10.0,
        ),
        http_client=http_client,
    )


def test_list_source_files_excludes_tests_and_configs(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "main.py").touch()
    (tmp_path / "src" / "pkg" / "util.py").touch()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").touch()
    (tmp_path / "tests" / "conftest.py").touch()
    (tmp_path / "setup.cfg").touch()

    sources = list_source_files(tmp_path)
    assert "src/pkg/main.py" in sources
    assert "src/pkg/util.py" in sources
    assert all("tests" not in s for s in sources)
    assert all("conftest" not in s for s in sources)


def test_run_triage_parses_json_output() -> None:
    triage_json = json.dumps(
        {
            "search_query": "pydantic 2.0 migration guide Model.dict",
            "failing_symbol": "BaseModel.dict",
            "candidate_files": ["src/pkg/main.py"],
            "summary": "dict() deprecated in favor of model_dump()",
        }
    )
    llm = _mock_llm([triage_json])
    req = UpgradeRequest(repo="dummy", package="pydantic", to_version="2.12.0")

    result = _run_triage(
        llm=llm,
        tier=CHEAP_TIER,
        request=req,
        error_tail=["E   AttributeError: 'Model' object has no attribute 'dict'"],
        source_files=["src/pkg/main.py", "src/pkg/util.py"],
    )

    assert result.search_query == "pydantic 2.0 migration guide Model.dict"
    assert result.failing_symbol == "BaseModel.dict"
    assert result.candidate_files == ["src/pkg/main.py"]


def test_run_triage_fallback_on_unparseable_output() -> None:
    llm = _mock_llm(["I cannot provide JSON right now."])
    req = UpgradeRequest(repo="dummy", package="pydantic", to_version="2.12.0")

    result = _run_triage(
        llm=llm,
        tier=CHEAP_TIER,
        request=req,
        error_tail=["E   ImportError: cannot import name 'X'"],
        source_files=["src/pkg/main.py"],
    )
    assert "pydantic 2.12.0 migration guide" in result.search_query
    assert result.candidate_files == ["src/pkg/main.py"]


def test_run_research_formats_tavily_results() -> None:
    mock_tavily = MagicMock(spec=TavilyClient)
    mock_tavily.search.return_value = TavilySearchResult(
        query="pydantic 2",
        results=[
            TavilyHit(
                title="Pydantic Migration Guide",
                url="https://docs.pydantic.dev/migration",
                content="Use model_dump instead of dict.",
                score=0.9,
            )
        ],
        response_time_s=0.5,
        credits_used=1,
    )
    context = _run_research(mock_tavily, "pydantic 2")
    assert "Pydantic Migration Guide" in context
    assert "https://docs.pydantic.dev/migration" in context
    assert "Use model_dump instead of dict." in context


def test_run_patch_parses_edits_payload(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    patch_json = json.dumps(
        {"files": [{"path": "src/app.py", "action": "write", "content": "def run(): return 42\n"}]}
    )
    llm = _mock_llm([patch_json])
    req = UpgradeRequest(repo=str(tmp_path), package="foo", to_version="2.0")

    payload = _run_patch(
        llm=llm,
        tier=DEFAULT_TIER,
        repo_root=tmp_path,
        request=req,
        candidate_files=["src/app.py"],
        error_tail=["failed"],
        research_context="none",
        iteration=1,
    )
    assert len(payload.files) == 1
    assert payload.files[0].path == "src/app.py"
    assert "return 42" in payload.files[0].content


def test_proof_card_markdown_contains_expected_sections() -> None:
    req = UpgradeRequest(repo="myrepo", package="pydantic", to_version="2.0")
    report = UpgradeReport(
        run_id="run-proof-test-01",
        request=req,
        status=VerifyStatus.GREEN,
        iterations_used=1,
        steps=[AgentStep(step="triage", status="ok", detail="Found symbol")],
        applied_edits=[
            EditApplied(path="src/main.py", action="write", diff="+ new code\n- old code\n")
        ],
    )
    md = proof_card_markdown(report)
    assert "# UpgradePilot Proof Card" in md
    assert "pydantic -> 2.0" in md
    assert "GREEN" in md
    assert "+ new code" in md
    assert "Execution Steps" in md


def test_run_upgrade_successful_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test full agent loop when patch resolves breakage cleanly."""
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "pkg").mkdir(parents=True)
    (repo_root / "src" / "pkg" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    (repo_root / "tests" / "test_b.py").write_text("def test_b(): assert True\n", encoding="utf-8")

    # Mock verify outcomes:
    # 1. baseline -> STUCK
    # 2. iteration 1 -> GREEN
    # 3. held-out certification -> GREEN
    verify_calls = 0

    def mock_verify(*args: Any, **kwargs: Any) -> VerifyOutcome:
        nonlocal verify_calls
        verify_calls += 1
        if verify_calls == 1:
            return VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="run-v1",
                result=PytestResult(exit_code=1, passed=0, failed=1, output_tail=["assert False"]),
            )
        return VerifyOutcome(
            status=VerifyStatus.GREEN,
            run_id=f"run-v{verify_calls}",
            result=PytestResult(exit_code=0, passed=1, failed=0, output_tail=["1 passed"]),
        )

    monkeypatch.setattr("upgradepilot.agent.verify", mock_verify)

    patch_json = json.dumps(
        {"files": [{"path": "src/pkg/app.py", "action": "write", "content": "x = 2\n"}]}
    )
    triage_json = json.dumps(
        {
            "search_query": "foo 2.0",
            "candidate_files": ["src/pkg/app.py"],
        }
    )

    fake_llm = _mock_llm([triage_json, patch_json])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)

    req = UpgradeRequest(repo=str(repo_root), package="foo", to_version="2.0")
    settings = Settings(
        nebius_api_key="mock",
        tavily_api_key="mock",
        token_cost_cap_usd=5.0,
    )
    repo_workdir = RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD")
    venv = VenvInfo(directory=tmp_path / "venv", python="python")

    report = run_upgrade(
        request=req,
        repo=repo_workdir,
        venv=venv,
        settings=settings,
        artifacts_dir=tmp_path / "artifacts",
        tiers=TIERS,
        max_iterations=2,
    )

    assert report.status is VerifyStatus.GREEN
    assert report.iterations_used == 1
    assert len(report.applied_edits) == 1
    assert (tmp_path / "artifacts" / report.run_id / "proof_card.md").is_file()
    ledger_events = [
        event.event for event in RunLedger(tmp_path / "artifacts" / report.run_id).read_all()
    ]
    assert "llm_cost" in ledger_events


def test_run_upgrade_escalates_after_repeated_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")

    outcomes = iter(
        [
            VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="baseline",
                result=PytestResult(exit_code=1, failed=1, output_tail=["fail"]),
            ),
            VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="iter1",
                result=PytestResult(exit_code=1, failed=1, output_tail=["still failing"]),
            ),
            VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="iter2",
                result=PytestResult(exit_code=0, passed=1, output_tail=["1 passed"]),
            ),
            # held-out certification run after visible GREEN
            VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="heldout",
                result=PytestResult(exit_code=0, passed=1, output_tail=["1 passed"]),
            ),
        ]
    )
    monkeypatch.setattr("upgradepilot.agent.verify", lambda *args, **kwargs: next(outcomes))
    monkeypatch.setattr(
        "upgradepilot.agent._run_triage",
        lambda **kwargs: TriageResult(
            search_query="demo 2.0 migration",
            candidate_files=["src/app.py"],
        ),
    )
    monkeypatch.setattr("upgradepilot.agent._run_research", lambda *args, **kwargs: "context")

    tier_roles: list[str] = []

    def fake_patch(**kwargs: Any) -> EditsPayload:
        tier_roles.append(kwargs["tier"].role)
        return EditsPayload(
            files=[
                PatchEdit(
                    path="src/app.py",
                    action="write",
                    content=f"x = {len(tier_roles) + 1}\n",
                )
            ]
        )

    monkeypatch.setattr("upgradepilot.agent._run_patch", fake_patch)
    fake_llm = _mock_llm(["unused"])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)

    report = run_upgrade(
        request=UpgradeRequest(repo=str(repo_root), package="demo", to_version="2.0"),
        repo=RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD"),
        venv=VenvInfo(directory=tmp_path / "venv", python="python"),
        settings=Settings(
            nebius_api_key="mock",
            tavily_api_key="mock",
            escalate_after=1,
        ),
        artifacts_dir=tmp_path / "artifacts",
        tiers=TIERS,
        max_iterations=3,
    )

    assert report.status is VerifyStatus.GREEN
    assert report.iterations_used == 2
    assert tier_roles == ["default", "strong"]


def test_run_upgrade_rolls_back_failed_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    source_file = repo_root / "src" / "app.py"
    source_file.write_text("x = 1\n", encoding="utf-8")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")

    monkeypatch.setattr(
        "upgradepilot.agent.verify",
        lambda *args, **kwargs: VerifyOutcome(
            status=VerifyStatus.STUCK,
            run_id="fail",
            result=PytestResult(exit_code=1, failed=1, output_tail=["fail"]),
        ),
    )
    monkeypatch.setattr(
        "upgradepilot.agent._run_triage",
        lambda **kwargs: TriageResult(
            search_query="demo 2.0 migration",
            candidate_files=["src/app.py"],
        ),
    )
    monkeypatch.setattr("upgradepilot.agent._run_research", lambda *args, **kwargs: "context")
    monkeypatch.setattr(
        "upgradepilot.agent._run_patch",
        lambda **kwargs: EditsPayload(
            files=[PatchEdit(path="src/app.py", action="write", content="x = 999\n")]
        ),
    )
    fake_llm = _mock_llm(["unused"])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)

    report = run_upgrade(
        request=UpgradeRequest(repo=str(repo_root), package="demo", to_version="2.0"),
        repo=RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD"),
        venv=VenvInfo(directory=tmp_path / "venv", python="python"),
        settings=Settings(nebius_api_key="mock", tavily_api_key="mock"),
        artifacts_dir=tmp_path / "artifacts",
        tiers=TIERS,
        max_iterations=1,
    )

    assert report.status is VerifyStatus.STUCK
    assert report.applied_edits == []
    assert source_file.read_text(encoding="utf-8") == "x = 1\n"


def test_run_upgrade_detects_cheating_on_test_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that any attempt to modify tests triggers CHEATED status."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")

    # Baseline fails
    monkeypatch.setattr(
        "upgradepilot.agent.verify",
        lambda *args, **kwargs: VerifyOutcome(
            status=VerifyStatus.STUCK,
            run_id="run-v1",
            result=PytestResult(exit_code=1, passed=0, failed=1, output_tail=["failed"]),
        ),
    )

    # Model maliciously tries to edit test_a.py
    cheating_patch_json = json.dumps(
        {
            "files": [
                {"path": "tests/test_a.py", "action": "write", "content": "def test_a(): pass\n"}
            ]
        }
    )
    fake_llm = _mock_llm(["{}", cheating_patch_json])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)

    req = UpgradeRequest(repo=str(repo_root), package="foo", to_version="2.0")
    settings = Settings(
        nebius_api_key="mock",
        tavily_api_key="mock",
        token_cost_cap_usd=5.0,
    )
    repo_workdir = RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD")
    venv = VenvInfo(directory=tmp_path / "venv", python="python")

    report = run_upgrade(
        request=req,
        repo=repo_workdir,
        venv=venv,
        settings=settings,
        artifacts_dir=tmp_path / "artifacts",
        tiers=TIERS,
        max_iterations=1,
    )

    assert report.status is VerifyStatus.CHEATED


def test_run_upgrade_detects_overfit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that visible tests passing while held-out fails produces OVERFIT."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    (repo_root / "tests" / "test_b.py").write_text("def test_b(): assert True\n", encoding="utf-8")

    # 1. baseline -> STUCK
    # 2. iteration 1 (visible) -> GREEN
    # 3. heldout -> STUCK
    call_idx = 0

    def mock_verify(*args: Any, **kwargs: Any) -> VerifyOutcome:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="v1",
                result=PytestResult(exit_code=1, failed=1, output_tail=["fail"]),
            )
        elif call_idx == 2:
            return VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="v2",
                result=PytestResult(exit_code=0, passed=1, output_tail=["1 passed"]),
            )
        else:
            return VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="v3",
                result=PytestResult(exit_code=1, failed=1, output_tail=["heldout failed"]),
            )

    monkeypatch.setattr("upgradepilot.agent.verify", mock_verify)

    patch_json = json.dumps(
        {"files": [{"path": "src/app.py", "action": "write", "content": "x = 2\n"}]}
    )
    fake_llm = _mock_llm(["{}", patch_json])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)

    req = UpgradeRequest(repo=str(repo_root), package="foo", to_version="2.0")
    settings = Settings(
        nebius_api_key="mock",
        tavily_api_key="mock",
        token_cost_cap_usd=5.0,
    )
    repo_workdir = RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD")
    venv = VenvInfo(directory=tmp_path / "venv", python="python")

    report = run_upgrade(
        request=req,
        repo=repo_workdir,
        venv=venv,
        settings=settings,
        artifacts_dir=tmp_path / "artifacts",
        tiers=TIERS,
        max_iterations=1,
    )

    assert report.status is VerifyStatus.OVERFIT


def test_run_upgrade_two_patch_repair_with_partial_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the loop retains partial-progress patches when failures strictly decrease."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    source_file = repo_root / "src" / "app.py"
    source_file.write_text("func_a = 0\nfunc_b = 0\n", encoding="utf-8")

    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (repo_root / "tests" / "test_b.py").write_text("def test_b(): pass\n", encoding="utf-8")

    # Sequence of verifier calls:
    # 1. baseline: 2 failures
    # 2. iteration 1: 1 failure (partial progress! strictly decreased from 2 -> 1)
    # 3. iteration 2: 0 failures (GREEN!)
    # 4. held-out certify: GREEN!
    call_idx = 0

    def mock_verify(*args: Any, **kwargs: Any) -> VerifyOutcome:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="baseline",
                result=PytestResult(exit_code=1, passed=0, failed=2, output_tail=["2 failed"]),
            )
        elif call_idx == 2:
            return VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="iter1",
                result=PytestResult(
                    exit_code=1, passed=1, failed=1, output_tail=["1 failed, 1 passed"]
                ),
            )
        else:
            return VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id=f"iter{call_idx}",
                result=PytestResult(exit_code=0, passed=2, failed=0, output_tail=["2 passed"]),
            )

    monkeypatch.setattr("upgradepilot.agent.verify", mock_verify)

    patch1_json = json.dumps(
        {
            "files": [
                {"path": "src/app.py", "action": "write", "content": "func_a = 1\nfunc_b = 0\n"}
            ]
        }
    )
    patch2_json = json.dumps(
        {
            "files": [
                {"path": "src/app.py", "action": "write", "content": "func_a = 1\nfunc_b = 1\n"}
            ]
        }
    )
    triage_json = json.dumps({"search_query": "query", "candidate_files": ["src/app.py"]})

    fake_llm = _mock_llm([triage_json, patch1_json, patch2_json])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)

    req = UpgradeRequest(repo=str(repo_root), package="demo", to_version="2.0")
    settings = Settings(nebius_api_key="mock", tavily_api_key="mock")
    repo_workdir = RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD")
    venv = VenvInfo(directory=tmp_path / "venv", python="python")

    report = run_upgrade(
        request=req,
        repo=repo_workdir,
        venv=venv,
        settings=settings,
        artifacts_dir=tmp_path / "artifacts",
        tiers=TIERS,
        max_iterations=3,
    )

    assert report.status is VerifyStatus.GREEN
    assert report.iterations_used == 2
    assert len(report.applied_edits) == 2
    # Verify patch 1 was kept and patch 2 completed the repair
    assert source_file.read_text(encoding="utf-8") == "func_a = 1\nfunc_b = 1\n"
    # Verify the partial_progress attempt status was recorded in step history
    statuses = [attempt.status for attempt in report.attempts]
    assert statuses == ["partial_progress", "GREEN"]
