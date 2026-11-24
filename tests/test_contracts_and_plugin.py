"""Unit tests for Milestone 0 data contracts, invariants, and AGY plugin layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agy_paper_agent.contracts import (
    SCHEMA_REGISTRY,
    CitationRegistry,
    DeterministicGateSuite,
    GateResult,
    OutlineContract,
    RevisionDecision,
    SymbolTable,
    export_all_schemas,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _valid_gate_suite(all_pass: bool = True) -> dict:
    gates = [
        {"gate": "numeric_fidelity", "passed": True},
        {"gate": "citation_integrity", "passed": True},
        {"gate": "latex_build", "passed": True},
        {
            "gate": "symbol_table",
            "passed": all_pass,
            "errors": [] if all_pass else ["Symbol X_t redefined in Section 4"],
        },
    ]
    return {"target_artifact": "manuscript/main.tex", "gates": gates, "all_passed": all_pass}


def test_symbol_table_rejects_duplicate_or_alias_collision() -> None:
    st = SymbolTable.model_validate(
        {
            "bundle_id": "rc_fihgnn_vn30f",
            "entries": [
                {
                    "symbol": r"\mathcal{H}_t",
                    "meaning": "Time-indexed hypergraph at bar t",
                    "domain_or_shape": "Tuple (V, E_t, W_t)",
                    "defined_in_section": "sec_method",
                    "aliases": [r"\Hgraph_t"],
                }
            ],
        }
    )
    assert len(st.entries) == 1

    with pytest.raises(ValidationError, match="Duplicate or colliding"):
        SymbolTable.model_validate(
            {
                "bundle_id": "rc_fihgnn_vn30f",
                "entries": [
                    {
                        "symbol": r"\mathcal{H}_t",
                        "meaning": "Hypergraph",
                        "domain_or_shape": "Graph",
                        "defined_in_section": "sec_3",
                        "aliases": [r"\H_t"],
                    },
                    {
                        "symbol": r"\H_t",
                        "meaning": "Hidden state matrix",
                        "domain_or_shape": "R^{Nxd}",
                        "defined_in_section": "sec_4",
                    },
                ],
            }
        )


def test_outline_contract_enforces_vector_only_hierarchy_and_figure_refs() -> None:
    base_outline = {
        "title_working": "Regime-Conditioned Hypergraph Networks for Index Futures",
        "target_venue": "ICLR",
        "cutoff_date": "2025-10",
        "plotting_plan": [
            {
                "figure_id": "fig_architecture_overview",
                "title": "System Architecture",
                "visual_kind": "tikz_diagram",
                "data_source": "idea.md",
                "objective": "Show regime gate feeding hypergraph convolution.",
                "aspect_ratio": "16:9",
            }
        ],
        "intro_related_work_plan": {
            "hook_hypothesis": "Intraday index futures exhibit abrupt regime shifts.",
            "problem_gap_hypothesis": "Pairwise graphs miss higher-order sector co-movements.",
            "macro_intro_queries": [
                "intraday futures microstructure",
                "hypergraph learning survey",
            ],
            "micro_rw_clusters": [
                {
                    "cluster_id": "c1",
                    "subsection_title": "2.1 Spatio-Temporal Graph Forecasting",
                    "methodology_cluster": "Pairwise GNNs",
                    "sota_search_queries": ["spatio-temporal GNN financial series"],
                    "limitation_hypothesis": "Restricted to dyadic edges.",
                    "limitation_search_queries": ["dyadic limitation graph neural network finance"],
                    "bridge_to_our_method": "Hyperedges capture multi-asset synchronous jumps.",
                },
                {
                    "cluster_id": "c2",
                    "subsection_title": "2.2 Physics- and Finance-Informed Neural Networks",
                    "methodology_cluster": "Domain-constrained neural architectures",
                    "sota_search_queries": ["finance-informed neural networks no-arbitrage"],
                    "limitation_hypothesis": "Lack cross-sectional structural priors.",
                    "limitation_search_queries": ["PINN cross-sectional asset pricing limitation"],
                    "bridge_to_our_method": (
                        "Couples structural hypergraphs with regime constraints."
                    ),
                },
            ],
        },
        "section_plan": [
            {"section_id": "abs", "section_title": "Abstract", "content_bullets": ["Summary"]},
            {
                "section_id": "method",
                "section_title": "3. Methodology",
                "subsections": [
                    {
                        "subsection_id": "3.1",
                        "subsection_title": "3.1 Problem Setup",
                        "content_bullets": ["Formalize inputs"],
                    },
                    {
                        "subsection_id": "3.2",
                        "subsection_title": "3.2 Architecture",
                        "content_bullets": ["Detail hypergraph message passing"],
                        "required_figures": ["fig_architecture_overview"],
                    },
                ],
            },
            {"section_id": "exp", "section_title": "4. Experiments", "content_bullets": ["Setup"]},
        ],
    }
    parsed = OutlineContract.model_validate(base_outline)
    assert parsed.plotting_plan[0].visual_kind == "tikz_diagram"

    # Reject raster visual_kind (D-05)
    bad_raster = json.loads(json.dumps(base_outline))
    bad_raster["plotting_plan"][0]["visual_kind"] = "raster_image_gen"
    with pytest.raises(ValidationError):
        OutlineContract.model_validate(bad_raster)

    # Reject orphaned single subsection
    bad_orphan = json.loads(json.dumps(base_outline))
    bad_orphan["section_plan"][1]["subsections"] = [bad_orphan["section_plan"][1]["subsections"][0]]
    with pytest.raises(ValidationError, match="orphaned single subsection"):
        OutlineContract.model_validate(bad_orphan)

    # Reject undeclared figure reference
    bad_fig_ref = json.loads(json.dumps(base_outline))
    bad_fig_ref["section_plan"][2]["required_figures"] = ["fig_nonexistent_ablation"]
    with pytest.raises(ValidationError, match="undeclared figure_id"):
        OutlineContract.model_validate(bad_fig_ref)


def test_citation_registry_enforces_external_id_bib_key_and_cutoff() -> None:
    valid_paper = {
        "cite_key": "feng2019hypergraph",
        "title": "Hypergraph Neural Networks",
        "authors": ["Yifan Feng", "Haoxuan You"],
        "year": 2019,
        "publication_date": "2019-01-27",
        "venue": "AAAI",
        "priority": "P0",
        "verified_by": "openalex",
        "external_ids": {"doi": "10.1609/aaai.v33i01.33013558"},
        "bibtex_entry": (
            "@inproceedings{feng2019hypergraph,\n"
            "  title={Hypergraph Neural Networks},\n"
            "  year={2019}\n}"
        ),
    }
    reg = CitationRegistry.model_validate({"cutoff_date": "2024-11", "papers": [valid_paper]})
    assert len(reg.papers) == 1

    # Reject unverified paper without external IDs
    unverified = {**valid_paper, "external_ids": {}}
    with pytest.raises(ValidationError, match="lacks verified external_ids"):
        CitationRegistry.model_validate({"papers": [unverified]})

    # Reject mismatched BibTeX header key
    mismatch = {
        **valid_paper,
        "bibtex_entry": "@inproceedings{wrong_key,\n  title={Hypergraph Neural Networks}\n}",
    }
    with pytest.raises(ValidationError, match="does not match cite_key"):
        CitationRegistry.model_validate({"papers": [mismatch]})

    # Reject post-cutoff paper unless marked is_concurrent_only=True
    post_cutoff = {**valid_paper, "year": 2025, "publication_date": "2025-02-10"}
    with pytest.raises(ValidationError, match="violates cutoff"):
        CitationRegistry.model_validate({"cutoff_date": "2024-11", "papers": [post_cutoff]})

    concurrent_ok = {**post_cutoff, "is_concurrent_only": True}
    reg2 = CitationRegistry.model_validate({"cutoff_date": "2024-11", "papers": [concurrent_ok]})
    assert reg2.papers[0].is_concurrent_only is True


def test_gate_suite_and_revision_decision_prevent_invalid_accept() -> None:
    with pytest.raises(ValidationError, match="cannot have passed=True with non-empty errors"):
        GateResult(gate="latex_build", passed=True, errors=["Undefined control sequence"])

    # Cannot spoof all_passed=True when a gate failed
    spoofed = _valid_gate_suite(all_pass=False)
    spoofed["all_passed"] = True
    with pytest.raises(ValidationError, match="contradicts individual gate statuses"):
        DeterministicGateSuite.model_validate(spoofed)

    reviews = [
        {"reviewer_role": "math_methodology", "score_1_to_10": 7.5},
        {"reviewer_role": "empirical_evidence", "score_1_to_10": 7.0},
        {"reviewer_role": "vlm_venue_layout", "score_1_to_10": 8.0},
    ]
    # Cannot accept revision if any deterministic gate failed
    with pytest.raises(ValidationError, match="Cannot set outcome='accept'"):
        RevisionDecision.model_validate(
            {
                "iteration": 1,
                "gates": _valid_gate_suite(all_pass=False),
                "reviews": reviews,
                "outcome": "accept",
            }
        )

    # Valid accept for legacy 3-reviewer worklogs (backward compatibility)
    decision_legacy = RevisionDecision.model_validate(
        {
            "iteration": 1,
            "gates": _valid_gate_suite(all_pass=True),
            "reviews": reviews,
            "outcome": "accept",
        }
    )
    assert decision_legacy.outcome == "accept"

    # Valid accept for full 4-reviewer panel including prose_style + prose_audit summary
    reviews_4 = [
        *reviews,
        {"reviewer_role": "prose_style", "score_1_to_10": 8.5},
    ]
    decision_4 = RevisionDecision.model_validate(
        {
            "iteration": 1,
            "gates": _valid_gate_suite(all_pass=True),
            "reviews": reviews_4,
            "prose_audit": {"pre_issues": 4, "post_issues": 0, "passed": True},
            "outcome": "accept",
        }
    )
    assert decision_4.outcome == "accept"
    assert len(decision_4.reviews) == 4

    # Reject duplicate reviewer roles or incomplete custom combinations
    with pytest.raises(ValidationError, match="Duplicate reviewer_role"):
        RevisionDecision.model_validate(
            {
                "iteration": 1,
                "gates": _valid_gate_suite(all_pass=True),
                "reviews": [reviews[0], reviews[0], reviews[1]],
                "outcome": "accept",
            }
        )
    with pytest.raises(ValidationError, match="requires all 4 reviewer roles"):
        RevisionDecision.model_validate(
            {
                "iteration": 1,
                "gates": _valid_gate_suite(all_pass=True),
                "reviews": [
                    reviews[0],
                    reviews[1],
                    {"reviewer_role": "prose_style", "score_1_to_10": 8.0},
                ],
                "outcome": "accept",
            }
        )


def test_exported_schemas_and_agy_plugin_manifest_are_valid() -> None:
    schemas_dir = REPO_ROOT / "schemas"
    export_all_schemas(schemas_dir, check_only=True)
    for filename in SCHEMA_REGISTRY:
        schema_path = schemas_dir / filename
        assert schema_path.is_file()
        loaded = json.loads(schema_path.read_text(encoding="utf-8"))
        assert "properties" in loaded

    plugin_manifest = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
    assert plugin_manifest["name"] == "agy-paper-agent"

    hooks_manifest = json.loads((REPO_ROOT / "hooks.json").read_text(encoding="utf-8"))
    assert "paper-deterministic-guardrails" in hooks_manifest

    rules_file = REPO_ROOT / "rules" / "AGENTS.md"
    assert rules_file.is_file()
    assert rules_file.stat().st_size < 24_000
    assert not rules_file.read_text(encoding="utf-8").startswith("---")

    skill_file = REPO_ROOT / "skills" / "paper-coauthor" / "SKILL.md"
    skill_text = skill_file.read_text(encoding="utf-8")
    assert skill_text.startswith("---\nname: paper-coauthor\n")
