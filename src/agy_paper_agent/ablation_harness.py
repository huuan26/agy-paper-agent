"""Reproducible ablation benchmark harness comparing AGY Paper Co-Author vs. baselines.

Implements the 4 quantitative ablations specified in Milestone 4:
1. Multi-Source Citation Cascade (Crossref + OpenAlex + arXiv + S2) vs. Semantic-Scholar-Only.
2. 4-Gate Deterministic Guardrail Suite vs. Unchecked Prompt-Only Baseline on adversarial defects.
3. Sandboxed Code-Vector AST + Numeric Check vs. Unchecked Plot Execution.
4. Token, Thinking-Token, and Latency Telemetry Aggregation across model tiers.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agy_paper_agent.bundle import verify_paper_bundle
from agy_paper_agent.sdk_adapter import RunTelemetryReport
from agy_paper_agent.tools import (
    CandidateQuery,
    MultiSourceCitationVerifier,
    audit_plot_script_ast,
)
from agy_paper_agent.tools.citation_verifier import HttpGetter
from agy_paper_agent.verifiers import verify_numeric_fidelity


@dataclass(frozen=True)
class CitationAblationMetrics:
    total_queries: int
    multisource_verified: int
    multisource_recall: float
    multisource_abstract_rate: float
    s2_only_verified: int
    s2_only_recall: float
    s2_only_abstract_rate: float
    recall_lift_abs: float


class _S2OnlyVerifier(MultiSourceCitationVerifier):
    """Baseline verifier restricted solely to Semantic Scholar (mirroring PaperOrchestra)."""

    def verify_candidate(self, query: CandidateQuery, existing_keys: set[str]) -> Any:
        hit = self._try_semantic_scholar(query)
        if hit is None:
            return None
        allowed, is_conc = self._check_cutoff(hit["publication_date"], hit["year"])
        if not allowed:
            return None
        from agy_paper_agent.contracts import VerifiedPaper
        from agy_paper_agent.tools.bib_helpers import build_cite_key, render_bibtex_entry

        cite_key = build_cite_key(hit["authors"], hit["year"], hit["title"], existing_keys)
        ext = hit["external_ids"]
        bib = render_bibtex_entry(
            cite_key=cite_key,
            title=hit["title"],
            authors=hit["authors"],
            year=hit["year"],
            venue=hit["venue"],
            doi=ext.doi,
            arxiv_id=ext.arxiv_id,
        )
        return VerifiedPaper(
            cite_key=cite_key,
            title=hit["title"],
            authors=hit["authors"],
            year=hit["year"],
            publication_date=hit["publication_date"],
            venue=hit["venue"],
            abstract=hit["abstract"],
            priority=query.priority,
            verified_by="semantic_scholar",
            is_concurrent_only=is_conc,
            external_ids=ext,
            bibtex_entry=bib,
        )


def ablate_citation_sources(
    queries: list[CandidateQuery],
    *,
    cutoff_date: str | None = None,
    http_get: HttpGetter | None = None,
) -> CitationAblationMetrics:
    """Compare Multi-Source Cascade vs. Semantic-Scholar-Only verification coverage."""
    n = len(queries)
    if n == 0:
        return CitationAblationMetrics(0, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)

    multi = MultiSourceCitationVerifier(cutoff_date=cutoff_date, http_get=http_get)
    s2_only = _S2OnlyVerifier(cutoff_date=cutoff_date, http_get=http_get)

    reg_multi = multi.build_registry(queries)
    reg_s2 = s2_only.build_registry(queries)

    m_cnt = len(reg_multi.papers)
    s_cnt = len(reg_s2.papers)
    m_abs = sum(1 for p in reg_multi.papers if p.abstract) / m_cnt if m_cnt else 0.0
    s_abs = sum(1 for p in reg_s2.papers if p.abstract) / s_cnt if s_cnt else 0.0

    m_rec = m_cnt / n
    s_rec = s_cnt / n
    return CitationAblationMetrics(
        total_queries=n,
        multisource_verified=m_cnt,
        multisource_recall=round(m_rec, 4),
        multisource_abstract_rate=round(m_abs, 4),
        s2_only_verified=s_cnt,
        s2_only_recall=round(s_rec, 4),
        s2_only_abstract_rate=round(s_abs, 4),
        recall_lift_abs=round(m_rec - s_rec, 4),
    )


@dataclass(frozen=True)
class GateAblationMetrics:
    clean_bundle_false_positives: int
    injected_defects_total: int
    defects_caught_by_gates: int
    defect_catch_rate: float
    per_defect_caught: dict[str, bool]


def ablate_deterministic_gates(clean_bundle_dir: Path) -> GateAblationMetrics:
    """Measure false positives on a clean bundle and catch rate across 4 adversarial mutations."""
    baseline_suite = verify_paper_bundle(clean_bundle_dir, enforce_citation_utilization=True)
    fp = sum(0 if g.passed else 1 for g in baseline_suite.gates)

    def _mutate_and_check(mutator: Any) -> bool:
        with tempfile.TemporaryDirectory(prefix="agy_ablate_") as tmp:
            work = Path(tmp) / "bundle"
            shutil.copytree(clean_bundle_dir, work)
            mutator(work)
            suite = verify_paper_bundle(work, enforce_citation_utilization=True)
            return not suite.all_passed

    def _inject_hallucinated_number(b: Path) -> None:
        exp_sec = b / "manuscript" / "sections" / "04_experiments.tex"
        target = exp_sec if exp_sec.is_file() else (b / "manuscript" / "main.tex")
        txt = target.read_text(encoding="utf-8")
        target.write_text(txt + "\nOur model achieves $98.76\\%$ accuracy.\n", encoding="utf-8")

    def _inject_ghost_citation(b: Path) -> None:
        intro_sec = b / "manuscript" / "sections" / "01_introduction.tex"
        target = intro_sec if intro_sec.is_file() else (b / "manuscript" / "main.tex")
        txt = target.read_text(encoding="utf-8")
        target.write_text(txt + "\nSee \\citep{nonexistent2099ghost}.\n", encoding="utf-8")

    def _inject_symbol_domain_conflict(b: Path) -> None:
        exp_sec = b / "manuscript" / "sections" / "04_experiments.tex"
        target = exp_sec if exp_sec.is_file() else (b / "manuscript" / "main.tex")
        txt = target.read_text(encoding="utf-8")
        target.write_text(
            txt + "\nHere $\\mathbf{S}_n \\in \\mathbb{R}^{1}$ conflicts.\n", encoding="utf-8"
        )

    def _inject_undefined_latex_ref(b: Path) -> None:
        conc_sec = b / "manuscript" / "sections" / "05_conclusion.tex"
        target = conc_sec if conc_sec.is_file() else (b / "manuscript" / "main.tex")
        txt = target.read_text(encoding="utf-8")
        target.write_text(txt + "\nAs proven in Theorem~\\ref{thm:missing}.\n", encoding="utf-8")

    cases = {
        "hallucinated_metric_number": _inject_hallucinated_number,
        "hallucinated_citation_key": _inject_ghost_citation,
        "conflicting_symbol_domain": _inject_symbol_domain_conflict,
        "undefined_latex_reference": _inject_undefined_latex_ref,
    }
    caught_map = {name: _mutate_and_check(fn) for name, fn in cases.items()}
    caught_cnt = sum(1 for v in caught_map.values() if v)
    return GateAblationMetrics(
        clean_bundle_false_positives=fp,
        injected_defects_total=len(cases),
        defects_caught_by_gates=caught_cnt,
        defect_catch_rate=round(caught_cnt / len(cases), 4),
        per_defect_caught=caught_map,
    )


def ablate_plot_safety_and_fidelity(source_log_text: str, tmp_dir: Path) -> dict[str, bool]:
    """Verify AST safety block and Gate 1 plot-literal drift detection."""
    unsafe_code = "import socket\nimport matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])\n"
    ast_blocked = len(audit_plot_script_ast(unsafe_code)) > 0

    drifted_script = tmp_dir / "drifted_plot.py"
    drifted_script.write_text("series = [0.90107, 0.99999]\n", encoding="utf-8")
    g1 = verify_numeric_fidelity(
        source_texts=[source_log_text],
        tex_files={},
        plot_scripts=[drifted_script],
    )
    return {
        "unsafe_network_import_blocked": ast_blocked,
        "plot_data_drift_caught": not g1.passed,
    }


def run_full_ablation_suite(
    clean_bundle_dir: Path,
    *,
    citation_queries: list[CandidateQuery],
    http_get: HttpGetter | None = None,
    telemetry: RunTelemetryReport | None = None,
) -> dict[str, Any]:
    """Run all 4 Milestone 4 ablations and return a structured JSON-serializable report."""
    cit_metrics = ablate_citation_sources(citation_queries, http_get=http_get)
    gate_metrics = ablate_deterministic_gates(clean_bundle_dir)
    exp_log = (clean_bundle_dir / "contract" / "experimental_log.md").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="agy_plot_ablate_") as tmp_s:
        plot_metrics = ablate_plot_safety_and_fidelity(exp_log, Path(tmp_s))

    return {
        "ablation_1_citation_sources": asdict(cit_metrics),
        "ablation_2_deterministic_gates": asdict(gate_metrics),
        "ablation_3_vector_plot_guardrails": plot_metrics,
        "ablation_4_telemetry": telemetry.to_dict() if telemetry else None,
    }
