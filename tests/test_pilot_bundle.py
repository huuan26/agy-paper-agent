"""End-to-end regression test for Milestone 3 Pilot (`examples/pilot_rc_fihgnn`)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agy_paper_agent.bundle import inspect_bundle, verify_paper_bundle
from agy_paper_agent.contracts import (
    CitationRegistry,
    OutlineContract,
    RevisionDecision,
    SymbolTable,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = REPO_ROOT / "examples" / "pilot_rc_fihgnn"


def test_pilot_rc_fihgnn_contracts_and_four_deterministic_gates() -> None:
    status = inspect_bundle(PILOT_DIR)
    assert status.has_canonical_contract is True
    assert status.needs_stage0_ingestion is False

    sym = SymbolTable.model_validate_json(
        (PILOT_DIR / "contract" / "symbol_table.json").read_text(encoding="utf-8")
    )
    assert len(sym.entries) == 8

    outline = OutlineContract.model_validate_json(
        (PILOT_DIR / "state" / "outline.json").read_text(encoding="utf-8")
    )
    assert len(outline.plotting_plan) == 2

    reg = CitationRegistry.model_validate_json(
        (PILOT_DIR / "state" / "citation_registry.json").read_text(encoding="utf-8")
    )
    assert len(reg.papers) >= 8
    sources = {p.verified_by for p in reg.papers}
    assert "seed_bib" in sources
    assert len(sources - {"seed_bib"}) >= 1

    worklog_path = PILOT_DIR / "state" / "refinement_worklog.json"
    assert worklog_path.is_file()
    decision = RevisionDecision.model_validate(json.loads(worklog_path.read_text(encoding="utf-8")))
    assert decision.gates.all_passed is True

    if shutil.which("pdflatex") is None:
        pytest.skip("pdflatex not installed")

    suite = verify_paper_bundle(PILOT_DIR, enforce_citation_utilization=True, max_pages=10)
    assert suite.all_passed is True, f"Pilot failed gates: {suite.model_dump()}"
