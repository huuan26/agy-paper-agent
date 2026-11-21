"""Unit and integration tests for Milestone 2 (Skills, Bundle CLI, Templates, and Workflow)."""

from __future__ import annotations

import ast
import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from agy_paper_agent.__main__ import main as cli_main
from agy_paper_agent.bundle import init_paper_bundle, inspect_bundle, verify_paper_bundle
from agy_paper_agent.contracts import RevisionDecision

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SKILLS = (
    "paper-coauthor",
    "paper-ingestion",
    "paper-lit-verify",
    "paper-vector-viz",
    "paper-refinement",
)


def _load_workflow_executor() -> Any:
    """Compile `workflows/paper_pipeline.py` with top-level-await flag (matching `run_workflow`)."""
    wf_path = REPO_ROOT / "workflows" / "paper_pipeline.py"
    src = wf_path.read_text(encoding="utf-8")
    code = compile(src, str(wf_path), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    ns: dict[str, Any] = {"__file__": str(wf_path), "__name__": "paper_pipeline_test"}
    coro = eval(code, ns)  # noqa: S307
    if coro is not None:
        asyncio.run(coro)
    return ns["execute_pipeline"]


def test_all_five_agy_skills_and_workflow_manifest_are_valid() -> None:
    for skill_name in EXPECTED_SKILLS:
        skill_md = REPO_ROOT / "skills" / skill_name / "SKILL.md"
        assert skill_md.is_file(), f"Missing skill file: {skill_md}"
        content = skill_md.read_text(encoding="utf-8")
        assert content.startswith(f"---\nname: {skill_name}\n")
        assert "description:" in content
        assert len(content.splitlines()) <= 80, f"Skill {skill_name} exceeds concise line budget"

    wf_json = json.loads((REPO_ROOT / "workflows" / "workflow.json").read_text(encoding="utf-8"))
    assert wf_json["entry"] == "paper_pipeline.py"
    assert "bundle_dir" in wf_json["argsSchema"]["required"]


def test_bundle_init_stage0_bypass_detection_and_template_compile(tmp_path: Path) -> None:
    bundle = tmp_path / "demo_bundle"
    rc = cli_main(["init-bundle", "--bundle-dir", str(bundle), "--template", "two_column_conf"])
    assert rc == 0

    # Initially lacks idea.md and experimental_log.md -> needs Stage 0 ingestion
    st_before = inspect_bundle(bundle)
    assert st_before.has_canonical_contract is False
    assert st_before.needs_stage0_ingestion is True

    # Populate canonical contract -> automatically bypasses Stage 0 (D-02)
    (bundle / "contract" / "idea.md").write_text(
        "# Core Idea\nWe propose a regime-conditioned hypergraph operator.", encoding="utf-8"
    )
    (bundle / "contract" / "experimental_log.md").write_text(
        "# Experimental Log\n- Validation RMSE: 0.142\n", encoding="utf-8"
    )
    st_after = inspect_bundle(bundle)
    assert st_after.has_canonical_contract is True
    assert st_after.needs_stage0_ingestion is False

    if shutil.which("pdflatex") is not None:
        suite = verify_paper_bundle(bundle)
        assert suite.all_passed is True


def test_workflow_enforces_hitl_gate_stage0_bypass_model_tiers_and_stage5_rollback(
    tmp_path: Path,
) -> None:
    execute_pipeline = _load_workflow_executor()
    bundle = init_paper_bundle(tmp_path / "wf_bundle", template_name="generic_article")
    (bundle / "contract" / "idea.md").write_text(
        "# Idea\nDense mathematical formulation with $M = 4$ blocks.", encoding="utf-8"
    )
    (bundle / "contract" / "experimental_log.md").write_text(
        "# Experimental Log\n- Test Sharpe = 2.40\n", encoding="utf-8"
    )

    phases_logged: list[str] = []
    agent_calls: list[dict[str, Any]] = []

    async def fake_parallel(items: list[Any], fn: Any) -> list[Any]:
        return [await fn(it) for it in items]

    # 1. Running stage="all" with auto_approve=False MUST fail (enforcing D-03 HITL)
    with pytest.raises(ValueError, match="D-03 Interactive Co-Author violation"):
        asyncio.run(
            execute_pipeline(
                {"bundle_dir": str(bundle), "stage": "all", "auto_approve": False},
                phase_fn=phases_logged.append,
                log_fn=lambda *a: None,
                agent_fn=lambda *a, **k: asyncio.sleep(0),
                parallel_fn=fake_parallel,
            )
        )

    # 2. Stage 0 bypasses automatically when canonical contract exists
    res0 = asyncio.run(
        execute_pipeline(
            {"bundle_dir": str(bundle), "stage": "stage0_ingest"},
            phase_fn=phases_logged.append,
            log_fn=lambda *a: None,
            agent_fn=lambda *a, **k: asyncio.sleep(0),
            parallel_fn=fake_parallel,
        )
    )
    assert res0["stage0"]["bypassed"] is True

    # 3. Stage 5 runs 3-critic panel (pro/pro/flash) + rolls back when revision breaks Gate 1
    clean_tex = (
        "\\documentclass{article}\n\\usepackage{booktabs}\n\\begin{document}\n"
        "\\section{Results}\n"
        "\\begin{tabular}{lc}\\toprule Model & Sharpe \\\\ "
        "\\midrule Ours & 2.40 \\\\ \\bottomrule\\end{tabular}\n"
        "\\end{document}\n"
    )
    (bundle / "manuscript" / "main.tex").write_text(clean_tex, encoding="utf-8")

    async def fake_stage5_agent(prompt: str, **kwargs: Any) -> Any:
        agent_calls.append(
            {
                "role": kwargs.get("role"),
                "model": kwargs.get("model"),
                "ws": kwargs.get("workspace"),
            }
        )
        role = kwargs.get("role", "")
        if role.startswith("Critic: "):
            r_name = role.split(": ", 1)[1]
            return {
                "reviewer_role": r_name,
                "score_1_to_10": 7.5,
                "blocking_issues": ["Clarify table"],
            }
        if role == "Revision Author":
            # Simulate an ungrounded hallucinated edit (9.99 not in experimental_log.md!)
            corrupted = clean_tex.replace("2.40", "9.99")
            (bundle / "manuscript" / "main.tex").write_text(corrupted, encoding="utf-8")
            return ["Attempted table edit"]
        return "ok"

    if shutil.which("pdflatex") is not None:
        res5 = asyncio.run(
            execute_pipeline(
                {
                    "bundle_dir": str(bundle),
                    "stage": "stage5_refinement",
                    "hitl_notes": ["Keep table concise"],
                },
                phase_fn=phases_logged.append,
                log_fn=lambda *a: None,
                agent_fn=fake_stage5_agent,
                parallel_fn=fake_parallel,
            )
        )
        assert res5["stage5"]["outcome"] == "rollback"
        # Verify manuscript was restored to clean 2.40 version!
        restored = (bundle / "manuscript" / "main.tex").read_text(encoding="utf-8")
        assert "2.40" in restored and "9.99" not in restored

        # Verify model routing & branch isolation on recorded calls
        models_by_role = {c["role"]: c["model"] for c in agent_calls}
        assert models_by_role["Critic: math_methodology"] == "pro"
        assert models_by_role["Critic: empirical_evidence"] == "pro"
        assert models_by_role["Critic: vlm_venue_layout"] == "flash"
        rev_call = next(c for c in agent_calls if c["role"] == "Revision Author")
        assert rev_call["ws"] == "branch"

        # Verify written refinement_worklog.json conforms to RevisionDecision schema!
        worklog = json.loads(
            (bundle / "state" / "refinement_worklog.json").read_text(encoding="utf-8")
        )
        validated = RevisionDecision.model_validate(worklog)
        assert validated.outcome == "rollback"
