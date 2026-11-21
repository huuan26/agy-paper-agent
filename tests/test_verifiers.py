"""Unit and integration tests for Milestone 1A (4 Deterministic Verification Gates)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agy_paper_agent.contracts import CitationRegistry, SymbolTable
from agy_paper_agent.verifiers import (
    run_all_gates,
    verify_citation_integrity,
    verify_latex_build,
    verify_numeric_fidelity,
    verify_symbol_consistency,
)

EXP_LOG_SAMPLE = """
# Experimental Log
- Dataset splits: 2,908 train, 276 val, 818 test.
- Learning rate: $1 \\cdot 10^{-4}$, blocks $M = 4$.
- Baseline EEMC: Seen J = 0.3420, Unseen J = 0.4954.
- Proposed RC-FIHGNN: Seen J = 0.43432, Unseen J = 0.54581, gain +9.23% +/- 0.42%.
"""


# ---------------------------------------------------------------------------
# Gate 1: Numeric Fidelity Tests
# ---------------------------------------------------------------------------


def test_gate1_accepts_grounded_and_properly_rounded_numbers(tmp_path: Path) -> None:
    tex = r"""
    Our method improves Seen Jaccard by $9.23\% \pm 0.42\%$.
    \begin{table}[t]
    \begin{tabular}{lcc}
    \toprule
    Method & Seen J (\%) & Unseen J \\
    \midrule
    (1) EEMC & 34.20 & 0.495 \\
    (2) Ours & \textbf{43.43} & \textbf{0.546} \\
    \bottomrule
    \end{tabular}
    \end{table}
    """
    plot_py = tmp_path / "fig_bar.py"
    plot_py.write_text(
        "import matplotlib.pyplot as plt\n"
        "figsize = (8, 4)\n"
        "scores = [34.20, 43.43]\n"
        "plt.figure(figsize=figsize, dpi=300)\n",
        encoding="utf-8",
    )
    res = verify_numeric_fidelity(
        source_texts=[EXP_LOG_SAMPLE],
        tex_files={"sec_exp.tex": tex},
        plot_scripts=[plot_py],
    )
    assert res.passed is True
    assert res.errors == []


def test_gate1_rejects_fabricated_table_number_excess_precision_and_plot_drift(
    tmp_path: Path,
) -> None:
    # 0.49549 has fabricated 5th decimal (source is 0.4954); 99.10 is completely invented
    bad_tex = r"""
    We achieve $99.10\%$ accuracy.
    \begin{tabular}{lc}
    \toprule
    Model & Unseen J \\
    \midrule
    EEMC & 0.49549 \\
    \bottomrule
    \end{tabular}
    """
    bad_plot = tmp_path / "bad_plot.py"
    bad_plot.write_text("vals = [0.3420, 0.7777]\n", encoding="utf-8")

    res = verify_numeric_fidelity(
        source_texts=[EXP_LOG_SAMPLE],
        tex_files={"sec_exp.tex": bad_tex},
        plot_scripts=[bad_plot],
    )
    assert res.passed is False
    assert any("0.49549" in e for e in res.errors)
    assert any("99.10" in e for e in res.errors)
    assert any("0.7777" in e for e in res.errors)


# ---------------------------------------------------------------------------
# Gate 2: Citation & BibTeX Integrity Tests
# ---------------------------------------------------------------------------


def _sample_registry() -> CitationRegistry:
    return CitationRegistry.model_validate(
        {
            "cutoff_date": "2025-01",
            "min_utilization_ratio": 0.80,
            "papers": [
                {
                    "cite_key": "feng2019hypergraph",
                    "title": "Hypergraph Neural Networks",
                    "authors": ["Yifan Feng"],
                    "year": 2019,
                    "publication_date": "2019-01-27",
                    "venue": "AAAI",
                    "priority": "P0",
                    "verified_by": "openalex",
                    "external_ids": {"doi": "10.1609/aaai.v33i01.33013558"},
                    "bibtex_entry": (
                        "@inproceedings{feng2019hypergraph,\n"
                        "  title={Hypergraph Neural Networks},\n"
                        "  author={Feng, Yifan},\n"
                        "  year={2019}\n}"
                    ),
                },
                {
                    "cite_key": "concurrent2025graph",
                    "title": "Concurrent Graph Futures",
                    "authors": ["Alice Smith"],
                    "year": 2025,
                    "publication_date": "2025-03-01",
                    "venue": "arXiv",
                    "priority": "P1",
                    "verified_by": "arxiv",
                    "is_concurrent_only": True,
                    "external_ids": {"arxiv_id": "2503.00001"},
                    "bibtex_entry": (
                        "@article{concurrent2025graph,\n"
                        "  title={Concurrent Graph Futures},\n"
                        "  author={Smith, Alice},\n"
                        "  year={2025}\n}"
                    ),
                },
            ],
        }
    )


def test_gate2_passes_valid_citations_and_catches_hallucinated_or_misframed_keys() -> None:
    reg = _sample_registry()
    bib = "\n\n".join(p.bibtex_entry for p in reg.papers)

    good_tex = (
        r"Prior work builds on hypergraphs \citep[see][]{feng2019hypergraph}. "
        r"Concurrent work explores alternative futures graphs \cite{concurrent2025graph}."
    )
    ok = verify_citation_integrity(
        tex_files={"intro.tex": good_tex},
        bib_text=bib,
        registry=reg,
        enforce_utilization=True,
    )
    assert ok.passed is True

    # Hallucinated key + forbidden superiority claim over concurrent paper
    bad_tex = (
        r"We build on \cite{ghost2024hallucinated}. "
        r"Our model significantly outperforms \cite{concurrent2025graph} on all splits."
    )
    bad = verify_citation_integrity(
        tex_files={"intro.tex": bad_tex},
        bib_text=bib,
        registry=reg,
        enforce_utilization=True,
    )
    assert bad.passed is False
    assert any("ghost2024hallucinated" in e for e in bad.errors)
    assert any("superiority claim" in e for e in bad.errors)


# ---------------------------------------------------------------------------
# Gate 4: Symbol Table Consistency Tests
# ---------------------------------------------------------------------------


def test_gate4_detects_use_before_definition_macro_override_and_domain_conflict() -> None:
    st = SymbolTable.model_validate(
        {
            "bundle_id": "test_sym",
            "entries": [
                {
                    "symbol": r"\mathcal{H}_t",
                    "meaning": "Dynamic hypergraph",
                    "domain_or_shape": r"\mathbb{R}^{N \times M}",
                    "defined_in_section": "sec_method",
                    "aliases": [r"\Hdyn"],
                }
            ],
        }
    )

    # Valid ordered usage
    ok = verify_symbol_consistency(
        symbol_table=st,
        ordered_sections=[
            ("sec_intro", "We study dynamic multi-asset interactions."),
            ("sec_method", r"Let $\mathcal{H}_t \in \mathbb{R}^{N \times M}$ denote incidence."),
            ("sec_exp", r"We ablate $\mathcal{H}_t$ across horizons."),
        ],
    )
    assert ok.passed is True

    # Invalid: used in intro (without preview), redefined macro in exp, wrong space R^{d}
    bad = verify_symbol_consistency(
        symbol_table=st,
        ordered_sections=[
            ("sec_intro", r"We directly optimize $\mathcal{H}_t$ here."),
            ("sec_method", r"Define $\mathcal{H}_t \in \mathbb{R}^{N \times M}$."),
            (
                "sec_exp",
                r"\renewcommand{\Hdyn}{H} Suppose $\mathcal{H}_t \in \mathbb{R}^{T}$.",
            ),
        ],
    )
    assert bad.passed is False
    assert any("used before its defining section" in e for e in bad.errors)
    assert any("redefined outside its defining section" in e for e in bad.errors)
    assert any("Domain conflict" in e for e in bad.errors)


# ---------------------------------------------------------------------------
# Gate 3 & Full 4-Gate Integration Test (Real MiKTeX pdflatex + bibtex)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_gate3_and_run_all_gates_with_miktex(tmp_path: Path) -> None:
    reg = _sample_registry()
    st = SymbolTable.model_validate(
        {
            "bundle_id": "e2e_gate_test",
            "entries": [
                {
                    "symbol": "M",
                    "meaning": "Number of temporal hypergraph blocks",
                    "domain_or_shape": r"\mathbb{N}",
                    "defined_in_section": "main.tex",
                }
            ],
        }
    )
    bib_text = "\n\n".join(p.bibtex_entry for p in reg.papers)
    (tmp_path / "references.bib").write_text(bib_text, encoding="utf-8")

    valid_main = r"""\documentclass{article}
\usepackage{booktabs}
\usepackage{amsmath,amssymb}
\begin{document}
\section{Method and Results}
We use $M \in \mathbb{N}$ blocks ($M = 4$) building on \cite{feng2019hypergraph},
yielding $9.23\%$ improvement.

\begin{tabular}{lc}
\toprule
Method & Seen J (\%) \\
\midrule
EEMC & 34.20 \\
Ours & 43.43 \\
\bottomrule
\end{tabular}

\bibliographystyle{plain}
\bibliography{references}
\end{document}
"""
    (tmp_path / "main.tex").write_text(valid_main, encoding="utf-8")

    suite = run_all_gates(
        target_artifact="main.tex",
        source_texts=[EXP_LOG_SAMPLE],
        ordered_sections=[("main.tex", valid_main)],
        bib_text=bib_text,
        citation_registry=reg,
        symbol_table=st,
        latex_source_dir=tmp_path,
        tex_filename="main.tex",
        max_pages=5,
        enforce_citation_utilization=True,
    )
    assert suite.all_passed is True
    assert all(g.passed for g in suite.gates)

    # Now introduce an undefined reference \ref{sec:missing} and verify Gate 3 catches it
    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    (broken_dir / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "See Section~\\ref{sec:missing}.\n\\end{document}\n",
        encoding="utf-8",
    )
    g3_bad = verify_latex_build(source_dir=broken_dir, tex_filename="main.tex")
    assert g3_bad.passed is False
    assert any("sec:missing" in e or "undefined references" in e for e in g3_bad.errors)
