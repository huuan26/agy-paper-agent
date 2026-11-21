"""Unified 4-gate deterministic verification suite for AGY Paper Co-Author."""

from __future__ import annotations

from pathlib import Path

from agy_paper_agent.contracts import (
    CitationRegistry,
    DeterministicGateSuite,
    SymbolTable,
)
from agy_paper_agent.verifiers.citation_integrity import verify_citation_integrity
from agy_paper_agent.verifiers.latex_build import LatexEngine, verify_latex_build
from agy_paper_agent.verifiers.numeric_fidelity import (
    SourceNumberPool,
    extract_source_number_pool,
    verify_numeric_fidelity,
)
from agy_paper_agent.verifiers.symbol_table import verify_symbol_consistency


def run_all_gates(
    *,
    target_artifact: str,
    source_texts: list[str],
    ordered_sections: list[tuple[str, str]],
    bib_text: str,
    citation_registry: CitationRegistry,
    symbol_table: SymbolTable,
    latex_source_dir: Path,
    tex_filename: str = "main.tex",
    latex_engine: LatexEngine = "pdflatex",
    plot_scripts: list[Path] | None = None,
    max_pages: int | None = None,
    enforce_citation_utilization: bool = False,
    allow_intro_symbol_preview: bool = False,
) -> DeterministicGateSuite:
    """Execute all 4 deterministic gates and assemble a validated DeterministicGateSuite."""
    tex_files = dict(ordered_sections)

    g1 = verify_numeric_fidelity(
        source_texts=source_texts,
        tex_files=tex_files,
        plot_scripts=plot_scripts,
    )
    g2 = verify_citation_integrity(
        tex_files=tex_files,
        bib_text=bib_text,
        registry=citation_registry,
        enforce_utilization=enforce_citation_utilization,
    )
    g3 = verify_latex_build(
        source_dir=latex_source_dir,
        tex_filename=tex_filename,
        engine=latex_engine,
        max_pages=max_pages,
    )
    g4 = verify_symbol_consistency(
        symbol_table=symbol_table,
        ordered_sections=ordered_sections,
        allow_intro_preview=allow_intro_symbol_preview,
    )

    gates = [g1, g2, g3, g4]
    return DeterministicGateSuite(
        target_artifact=target_artifact,
        gates=gates,
        all_passed=all(g.passed for g in gates),
    )


__all__ = [
    "SourceNumberPool",
    "extract_source_number_pool",
    "run_all_gates",
    "verify_citation_integrity",
    "verify_latex_build",
    "verify_numeric_fidelity",
    "verify_symbol_consistency",
]
