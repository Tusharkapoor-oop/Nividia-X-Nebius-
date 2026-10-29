"""Regression tests for the Phase 5 findings D1, D2, and result provenance.

D1  skipped/xfailed counts must be measured against the old-pin GREEN run
    recorded before the bump, never against a post-bump run that failed to
    collect. The anti-masking rule stays at full strength.
D2  a rollback message states the real reason (statuses and counts), never a
    999999 sentinel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from upgradepilot.agent import (
    TriageResult,
    proof_card_markdown,
    run_upgrade,
)
from upgradepilot.config import Settings
from upgradepilot.editing import EditsPayload, PatchEdit
from upgradepilot.harness import RepoWorkdir, VenvInfo
from upgradepilot.llm import LLMClient
from upgradepilot.models import PytestResult
from upgradepilot.pipeline import UpgradeRequest
from upgradepilot.tiers import ModelTier
from upgradepilot.verify import VerifyOutcome, VerifyStatus

_CHEAP = ModelTier(
    role="cheap",
    model_id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    context_window=262144,
    input_price_per_m=0.06,
    output_price_per_m=0.24,
    max_tokens=512,
)
_DEFAULT = ModelTier(
    role="default",
    model_id="nvidia/Nemotron-3_5-Lightning",
    context_window=1048576,
    input_price_per_m=0.06,
    output_price_per_m=0.24,
    max_tokens=4096,
)
_STRONG = _DEFAULT.model_copy(update={"role": "strong"})
_TIERS = {"cheap": _CHEAP, "default": _DEFAULT, "strong": _STRONG}


def _mock_llm(responses: list[str]) -> LLMClient:
    """LLM client whose HTTP transport returns canned chat completions."""
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
        Settings(nebius_api_key="mock", tavily_api_key="mock", token_cost_cap_usd=10.0),
        http_client=http_client,
    )


def _single_test_repo(tmp_path: Path) -> Path:
    """One source file and one test file: no internal held-out split."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo_root / "tests").mkdir()
    (repo_root / "tests" / "test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    return repo_root


def _wire_agent(monkeypatch: pytest.MonkeyPatch, outcomes: list[VerifyOutcome]) -> None:
    sequence = iter(outcomes)
    monkeypatch.setattr("upgradepilot.agent.verify", lambda *args, **kwargs: next(sequence))
    monkeypatch.setattr(
        "upgradepilot.agent._run_triage",
        lambda **kwargs: TriageResult(
            search_query="demo 2.0 migration", candidate_files=["src/app.py"]
        ),
    )
    monkeypatch.setattr("upgradepilot.agent._run_research", lambda *args, **kwargs: "context")
    monkeypatch.setattr(
        "upgradepilot.agent._run_patch",
        lambda **kwargs: EditsPayload(
            files=[PatchEdit(path="src/app.py", action="write", content="x = 2\n")]
        ),
    )
    fake_llm = _mock_llm(["unused"])
    monkeypatch.setattr("upgradepilot.agent.LLMClient", lambda *args, **kwargs: fake_llm)


def _run(
    tmp_path: Path,
    repo_root: Path,
    *,
    settings: Settings | None = None,
    max_iterations: int = 1,
    versions: dict[str, str] | None = None,
    reference_outcome: VerifyOutcome | None = None,
) -> Any:
    return run_upgrade(
        request=UpgradeRequest(repo=str(repo_root), package="demo", to_version="2.0"),
        repo=RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD"),
        venv=VenvInfo(directory=tmp_path / "venv", python="python"),
        settings=settings or Settings(nebius_api_key="mock", tavily_api_key="mock"),
        artifacts_dir=tmp_path / "artifacts",
        tiers=_TIERS,
        max_iterations=max_iterations,
        versions=versions,
        reference_outcome=reference_outcome,
    )


def test_agent_does_not_flag_skips_that_predate_the_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1: a patch that restores collection is not test-masking.

    The old-pin GREEN run skipped one test conditionally; the post-bump
    baseline collected nothing; the repaired run collects and skips the same
    one test. Comparing against the non-collecting baseline called this
    CHEATED; comparing against the old-pin run certifies GREEN.
    """
    repo_root = _single_test_repo(tmp_path)
    reference = VerifyOutcome(
        status=VerifyStatus.GREEN,
        run_id="old-pin",
        result=PytestResult(exit_code=0, passed=19, skipped=1),
    )
    _wire_agent(
        monkeypatch,
        [
            VerifyOutcome(
                status=VerifyStatus.ENV_FAIL,
                run_id="baseline",
                result=PytestResult(exit_code=2, passed=0, output_tail=["ImportError"]),
            ),
            VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="iter1",
                result=PytestResult(exit_code=0, passed=19, skipped=1),
            ),
            # held-out certification run for the injected behavioural file
            VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="heldout",
                result=PytestResult(exit_code=0, passed=4),
            ),
        ],
    )

    report = _run(tmp_path, repo_root, reference_outcome=reference)

    assert report.status is VerifyStatus.GREEN
    assert report.guard_clean is True
    assert report.reference_outcome is reference
    assert any(step.step == "reference_verify" for step in report.steps)


def test_agent_still_flags_a_newly_skipped_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1: adding a skip relative to the old-pin GREEN run is still CHEATED."""
    repo_root = _single_test_repo(tmp_path)
    reference = VerifyOutcome(
        status=VerifyStatus.GREEN,
        run_id="old-pin",
        result=PytestResult(exit_code=0, passed=20, skipped=0),
    )
    _wire_agent(
        monkeypatch,
        [
            VerifyOutcome(
                status=VerifyStatus.ENV_FAIL,
                run_id="baseline",
                result=PytestResult(exit_code=2, passed=0, output_tail=["ImportError"]),
            ),
            VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="iter1",
                result=PytestResult(exit_code=0, passed=19, skipped=1),
            ),
        ],
    )

    report = _run(tmp_path, repo_root, reference_outcome=reference)

    assert report.status is VerifyStatus.CHEATED
    assert report.attempts[-1].status == "guard_violation"
    assert "newly skipped" in report.attempts[-1].detail
    # The tree is restored: the skipping patch never survives the run.
    assert (repo_root / "src" / "app.py").read_text(encoding="utf-8") == "x = 1\n"


def test_rollback_message_states_the_real_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D2: the message names the statuses and counts, not a sentinel."""
    repo_root = _single_test_repo(tmp_path)
    _wire_agent(
        monkeypatch,
        [
            VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="baseline",
                result=PytestResult(exit_code=1, passed=3, failed=2),
            ),
            VerifyOutcome(
                status=VerifyStatus.ENV_FAIL,
                run_id="iter1",
                result=PytestResult(exit_code=4, passed=0, failed=0),
            ),
        ],
    )

    report = _run(tmp_path, repo_root)

    detail = report.attempts[0].detail
    assert "did not improve" in detail
    assert "ENV_FAIL" in detail
    assert "STUCK" in detail
    assert "3 passed" in detail
    assert "2 failed" in detail
    assert "999999" not in detail
    assert all("999999" not in step.detail for step in report.steps)


def test_partial_progress_and_flat_rerun_report_real_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D2: 'no failing count to beat' is stated, never encoded as 999999."""
    repo_root = _single_test_repo(tmp_path)
    _wire_agent(
        monkeypatch,
        [
            VerifyOutcome(
                status=VerifyStatus.ENV_FAIL,
                run_id="baseline",
                result=PytestResult(exit_code=2, passed=0, output_tail=["ImportError"]),
            ),
            VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="iter1",
                result=PytestResult(exit_code=1, passed=1, failed=3),
            ),
            VerifyOutcome(
                status=VerifyStatus.STUCK,
                run_id="iter2",
                result=PytestResult(exit_code=1, passed=1, failed=3),
            ),
        ],
    )

    report = _run(tmp_path, repo_root, max_iterations=2)

    assert report.attempts[0].status == "partial_progress"
    assert "now collects with 3 failing" in report.attempts[0].detail
    assert report.attempts[1].status == "rolled_back"
    assert "still STUCK with 3 failing" in report.attempts[1].detail
    assert "best 3 seen so far" in report.attempts[1].detail
    assert all("999999" not in step.detail for step in report.steps)


def test_report_records_provider_models_and_resolved_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every report states its provider, models, run class, and versions."""
    repo_root = _single_test_repo(tmp_path)
    _wire_agent(
        monkeypatch,
        [
            VerifyOutcome(
                status=VerifyStatus.GREEN,
                run_id="baseline",
                result=PytestResult(exit_code=0, passed=1),
            )
        ],
    )

    report = _run(
        tmp_path,
        repo_root,
        settings=Settings(nvidia_api_key="mock", tavily_api_key="mock", llm_provider="nvidia-nim"),
        versions={"python": "3.13.15", "pytest": "8.4.1", "demo": "2.0"},
    )

    assert report.provider == "nvidia-nim"
    assert report.run_class == "dev"
    assert report.models["default"] == _DEFAULT.model_id
    assert report.versions["demo"] == "2.0"

    card = proof_card_markdown(report)
    assert "NVIDIA NIM (dev run - not submission-eligible)" in card
    assert "demo 2.0" in card


def test_agent_provider_label_never_claims_a_dev_run_is_submission() -> None:
    """The label is the single place provider wording is decided."""
    from upgradepilot.agent import provider_label

    assert provider_label("nvidia-nim", "dev").startswith("NVIDIA NIM (dev run")
    assert "not submission-eligible" in provider_label("nvidia-nim", "dev")
    assert provider_label("tokenfactory", "submission") == "Nebius Token Factory (submission run)"
    assert "dev run" in provider_label("tokenfactory", "dev")
