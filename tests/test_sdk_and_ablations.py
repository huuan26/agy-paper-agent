"""Unit and integration tests for Milestone 4 (AGY Python SDK Adapter & 4 Ablations)."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import types as pytypes
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agy_paper_agent.ablation_harness import (
    ablate_citation_sources,
    ablate_deterministic_gates,
    ablate_plot_safety_and_fidelity,
    run_full_ablation_suite,
)
from agy_paper_agent.bundle import init_paper_bundle
from agy_paper_agent.contracts import OutlineContract
from agy_paper_agent.sdk_adapter import (
    GoogleAntigravityBackend,
    SDKBudgetSettings,
    SDKPaperCoAuthorRunner,
    StageTelemetry,
    build_sdk_custom_tools,
)
from agy_paper_agent.tools import CandidateQuery

REPO_ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = REPO_ROOT / "examples" / "pilot_rc_fihgnn"


# ---------------------------------------------------------------------------
# 1. GoogleAntigravityBackend Config & Safety Policy Tests (Mocked SDK Module)
# ---------------------------------------------------------------------------


def test_google_antigravity_backend_config_wiring_and_raster_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify exact LocalAgentConfig parameters against official google.antigravity spec."""
    google_pkg = pytypes.ModuleType("google")
    agy_mod = pytypes.ModuleType("google.antigravity")
    hooks_pkg = pytypes.ModuleType("google.antigravity.hooks")

    class FakeAgentBehavior:
        AUTONOMOUS = "AUTONOMOUS"
        INTERACTIVE = "INTERACTIVE"

    class FakeCapabilitiesConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class FakeBudgetConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class FakeLocalAgentConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class FakePolicy:
        @staticmethod
        def deny(tool_name: str, when: Any = None, name: str = "") -> dict[str, Any]:
            return {"action": "deny", "tool": tool_name, "when": when, "name": name}

        @staticmethod
        def allow_all() -> dict[str, Any]:
            return {"action": "allow_all"}

    agy_types = pytypes.SimpleNamespace(
        AgentBehavior=FakeAgentBehavior,
        CapabilitiesConfig=FakeCapabilitiesConfig,
        BudgetConfig=FakeBudgetConfig,
    )
    agy_mod.LocalAgentConfig = FakeLocalAgentConfig  # type: ignore[attr-defined]
    agy_mod.types = agy_types  # type: ignore[attr-defined]
    hooks_pkg.policy = FakePolicy  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.antigravity", agy_mod)
    monkeypatch.setitem(sys.modules, "google.antigravity.hooks", hooks_pkg)

    backend = GoogleAntigravityBackend(
        budget=SDKBudgetSettings(max_model_calls=12, max_total_tokens=200_000),
        vertex=True,
        project="quant-research-gcp",
        location="us-central1",
    )

    # Interactive Co-Author mode -> AgentBehavior.INTERACTIVE, model unset by default
    cfg_inter = backend.build_agent_config(
        bundle_dir=tmp_path,
        auto_approve=False,
        response_schema=OutlineContract,
    )
    kw = cfg_inter.kwargs
    assert "model" not in kw
    assert kw["response_schema"] is OutlineContract
    assert kw["capabilities"].kwargs["agent_behavior"] == "INTERACTIVE"
    assert kw["budget_config"].kwargs["max_model_calls"] == 12
    assert kw["vertex"] is True and kw["project"] == "quant-research-gcp"
    assert str(REPO_ROOT / "skills") in kw["skills_paths"]
    assert len(kw["tools"]) == 4

    # Verify declarative policy blocks image-generator but allows research subagents
    deny_invoke = kw["policies"][0]
    assert deny_invoke["when"]({"TypeName": "image-generator"}) is True
    assert deny_invoke["when"]({"TypeName": "research"}) is False

    # Batch Benchmark mode (auto_approve=True) -> AgentBehavior.AUTONOMOUS
    cfg_auto = backend.build_agent_config(bundle_dir=tmp_path, auto_approve=True)
    assert cfg_auto.kwargs["capabilities"].kwargs["agent_behavior"] == "AUTONOMOUS"


# ---------------------------------------------------------------------------
# 2. SDKPaperCoAuthorRunner Telemetry, HITL Guard & Stage 5 Rollback Tests
# ---------------------------------------------------------------------------


def test_sdk_runner_telemetry_hitl_guard_and_stage5_rollback(tmp_path: Path) -> None:
    bundle = init_paper_bundle(tmp_path / "sdk_bundle")
    (bundle / "contract" / "idea.md").write_text(
        "# Idea\nHypergraph operator with $M = 4$ blocks.", encoding="utf-8"
    )
    (bundle / "contract" / "experimental_log.md").write_text(
        "# Experimental Log\n- Sharpe = 2.15\n", encoding="utf-8"
    )
    clean_tex = (
        "\\documentclass{article}\n\\usepackage{booktabs}\n\\begin{document}\n"
        "\\section{Results}\n"
        "\\begin{tabular}{lc}\\toprule Model & Sharpe \\\\ "
        "\\midrule Ours & 2.15 \\\\ \\bottomrule\\end{tabular}\n"
        "\\end{document}\n"
    )
    (bundle / "manuscript" / "main.tex").write_text(clean_tex, encoding="utf-8")

    # Verify custom tool `inspect_paper_bundle_tool` directly
    tools = build_sdk_custom_tools(bundle)
    inspected = json.loads(tools[0]())
    assert inspected["has_canonical_contract"] is True

    class FakeBackend:
        async def run_turn(
            self,
            prompt: str,
            *,
            stage_name: str,
            bundle_dir: Path,
            auto_approve: bool,
            response_schema: type[BaseModel] | None = None,
            model: str | None = None,
        ) -> tuple[Any, StageTelemetry]:
            tel = StageTelemetry(
                stage=stage_name,
                wall_clock_sec=0.25,
                prompt_tokens=500,
                candidates_tokens=150,
                thoughts_tokens=200,
                total_tokens=850,
            )
            if stage_name.startswith("stage5_critic_"):
                role = stage_name.replace("stage5_critic_", "")
                return {"reviewer_role": role, "score_1_to_10": 8.0, "blocking_issues": []}, tel
            if stage_name == "stage5_revision":
                # Inject an ungrounded table number 8.88 -> must rollback!
                (bundle_dir / "manuscript" / "main.tex").write_text(
                    clean_tex.replace("2.15", "8.88"), encoding="utf-8"
                )
            return "ok", tel

    runner = SDKPaperCoAuthorRunner(FakeBackend())

    # Guard: stage="all" without auto_approve=True is rejected
    with pytest.raises(ValueError, match="requires auto_approve=True"):
        asyncio.run(runner.run_pipeline(bundle, stage="all", auto_approve=False))

    if shutil.which("pdflatex") is not None:
        res = asyncio.run(runner.run_pipeline(bundle, stage="stage5_refinement", auto_approve=True))
        assert res["stage5"]["outcome"] == "rollback"
        assert res["telemetry"]["thoughts_tokens"] == 800  # 4 turns * 200
        assert res["telemetry"]["total_tokens"] == 3400  # 4 turns * 850
        restored = (bundle / "manuscript" / "main.tex").read_text(encoding="utf-8")
        assert "2.15" in restored and "8.88" not in restored


# ---------------------------------------------------------------------------
# 3. Four Quantitative Ablation Benchmarks (Multi-Source vs S2, 4-Gate vs None)
# ---------------------------------------------------------------------------


def test_ablation_1_multisource_beats_s2_only_on_non_s2_papers() -> None:
    def mock_http(url: str, headers: dict[str, str]) -> bytes:
        # Simulate Applied Math / Finance papers indexed in Crossref & OpenAlex but missing on S2
        if "api.crossref.org" in url and "10.1007" in url:
            return json.dumps(
                {
                    "message": {
                        "DOI": "10.1007/s10614-022-10268-0",
                        "title": ["Intraday Lead-Lag Relations in Index Futures"],
                        "published-print": {"date-parts": [[2023, 5, 1]]},
                        "author": [{"given": "Fei", "family": "Ren"}],
                        "container-title": ["Computational Economics"],
                        "abstract": "Lead-lag empirical analysis.",
                    }
                }
            ).encode("utf-8")
        if "api.openalex.org" in url:
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W111",
                            "doi": "https://doi.org/10.1145/3719002",
                            "title": "A Survey on Hypergraph Mining",
                            "publication_year": 2025,
                            "publication_date": "2025-02-01",
                            "authorships": [{"author": {"display_name": "Geon Lee"}}],
                            "primary_location": {"source": {"display_name": "ACM CSUR"}},
                            "abstract_inverted_index": {"Survey": [0], "abstract": [1]},
                        }
                    ]
                }
            ).encode("utf-8")
        # S2 returns empty for both domain-specific queries
        return b'{"data": []}'

    queries = [
        CandidateQuery(
            title="Intraday Lead-Lag Relations in Index Futures",
            year_hint=2023,
            doi_hint="10.1007/s10614-022-10268-0",
        ),
        CandidateQuery(title="A Survey on Hypergraph Mining", year_hint=2025),
    ]
    metrics = ablate_citation_sources(queries, http_get=mock_http)
    assert metrics.multisource_recall == 1.0
    assert metrics.s2_only_recall == 0.0
    assert metrics.recall_lift_abs == 1.0


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_ablation_2_and_3_full_suite_on_pilot_rc_fihgnn(tmp_path: Path) -> None:
    gate_ablation = ablate_deterministic_gates(PILOT_DIR)
    assert gate_ablation.clean_bundle_false_positives == 0
    assert gate_ablation.defect_catch_rate == 1.0
    assert all(gate_ablation.per_defect_caught.values())

    exp_log = (PILOT_DIR / "contract" / "experimental_log.md").read_text(encoding="utf-8")
    plot_ablation = ablate_plot_safety_and_fidelity(exp_log, tmp_path)
    assert plot_ablation["unsafe_network_import_blocked"] is True
    assert plot_ablation["plot_data_drift_caught"] is True

    full = run_full_ablation_suite(
        PILOT_DIR,
        citation_queries=[],
    )
    assert full["ablation_2_deterministic_gates"]["defect_catch_rate"] == 1.0
