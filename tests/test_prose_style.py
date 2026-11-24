"""Unit and integration tests for `avoid-ai-writing` LaTeX prose style auditing."""

from __future__ import annotations

import json
from pathlib import Path

from agy_paper_agent.__main__ import main as cli_main
from agy_paper_agent.bundle import init_paper_bundle
from agy_paper_agent.verifiers import audit_manuscript_prose, extract_latex_prose


def test_extract_latex_prose_strips_tables_math_and_maps_paragraphs_to_headings() -> None:
    raw_tex = r"""
    % Ignore comment line with delve and ---
    \section{Empirical Results}\label{sec:exp}
    \paragraph{Baseline Protocol.}
    We evaluate $h^*_{n,k} = 1 - \phi_k(p)$ across \citet{Epps1979} and \citep{Johansen1991}.
    \begin{table}[t]
      \begin{tabular}{lc}
        \toprule
        Model & BVR \\
        \midrule
        Ours & 0.00 \\
        \bottomrule
      \end{tabular}
    \end{table}
    \begin{equation}
      z_n = \ln F_n - \ln S_n
    \end{equation}
    """
    prose = extract_latex_prose(raw_tex)
    assert "delve" not in prose
    assert "tabular" not in prose
    assert "#### Baseline Protocol." in prose
    assert "**Baseline Protocol.**" not in prose
    assert "Author (2020)" in prose


def test_audit_manuscript_prose_flags_ai_tells_and_respects_clean_academic_text() -> None:
    clean_academic = {
        "03_method.tex": (
            r"\section{Methodology}"
            "\n"
            r"The estimator remains statistically significant across volatility regimes "
            r"and preserves cost-of-carry basis dynamics under $T+1$ settlement."
        )
    }
    clean_rep = audit_manuscript_prose(clean_academic, max_issues_per_file=0)
    assert clean_rep.passed is True
    assert clean_rep.total_issues == 0

    noisy_tex = {
        "01_intro.tex": (
            r"\section{Introduction}"
            "\n"
            r"As of my last knowledge update, we delve into this tapestry---a watershed moment. "
            r"Crucially, our model improves accuracy, lifting recall by 10\%, ranking first "
            r"across benchmarks, and outperforming every baseline."
        )
    }
    bad_rep = audit_manuscript_prose(noisy_tex, max_issues_per_file=0)
    assert bad_rep.passed is False
    found_types = {iss.issue_type for f in bad_rep.files for iss in f.issues}
    assert "self_labeling_adverbial" in found_types
    assert "participial_tail_stack" in found_types
    assert "non_ascii_or_em_dash" in found_types
    assert any(t in found_types for t in ("tier1", "cutoff-disclaimer", "chatbot_or_placeholder"))


def test_cli_audit_prose_writes_json_report(tmp_path: Path) -> None:
    bundle = init_paper_bundle(tmp_path / "prose_bundle")
    (bundle / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\section{Introduction}\n"
        "We derive closed-form minimum-variance hedge ratios under staggered trading.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    out_json = bundle / "state" / "verification_reports" / "prose_audit.json"
    rc = cli_main(
        [
            "audit-prose",
            "--bundle-dir",
            str(bundle),
            "--max-issues-per-file",
            "0",
            "--report-out",
            str(out_json),
        ]
    )
    assert rc == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["total_issues"] == 0
