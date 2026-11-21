"""Unit and integration tests for Milestone 1B (Citation Verifier, Sandbox Runner, AGY Hooks)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agy_paper_agent.hooks_entry import handle_hook_payload
from agy_paper_agent.tools import (
    CandidateQuery,
    MultiSourceCitationVerifier,
    audit_plot_script_ast,
    compile_tikz_diagram,
    reconstruct_openalex_abstract,
    run_matplotlib_script,
)

# ---------------------------------------------------------------------------
# 1. Multi-Source Citation Verifier & SQLite Cache Tests (Offline Deterministic)
# ---------------------------------------------------------------------------


def test_openalex_inverted_index_reconstruction() -> None:
    inv = {"Hypergraph": [0], "neural": [1], "networks": [2], "capture": [3], "higher-order": [4]}
    assert reconstruct_openalex_abstract(inv) == "Hypergraph neural networks capture higher-order"
    assert reconstruct_openalex_abstract(None) is None


def test_multisource_cascade_dedup_seed_bib_cache_and_cutoff(tmp_path: Path) -> None:
    call_counter = {"count": 0}

    def fake_http_get(url: str, headers: dict[str, str]) -> bytes:
        call_counter["count"] += 1
        if "api.crossref.org" in url:
            if "raissi2019" in url:
                return json.dumps(
                    {
                        "message": {
                            "DOI": "10.1000/raissi2019",
                            "title": ["Physics-informed neural networks"],
                            "published-print": {"date-parts": [[2019, 2, 1]]},
                            "author": [{"given": "Maziar", "family": "Raissi"}],
                            "container-title": ["Journal of Computational Physics"],
                            "abstract": "<jats:p>Deep learning for nonlinear PDEs.</jats:p>",
                        }
                    }
                ).encode("utf-8")
            return json.dumps({"message": {"items": []}}).encode("utf-8")

        if "api.openalex.org" in url and "hypergraph+neural+networks" in url.lower():
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W2912345",
                            "doi": "https://doi.org/10.1609/aaai.v33i01",
                            "title": "Hypergraph Neural Networks",
                            "publication_year": 2019,
                            "publication_date": "2019-01-27",
                            "authorships": [{"author": {"display_name": "Yifan Feng"}}],
                            "primary_location": {"source": {"display_name": "AAAI"}},
                            "abstract_inverted_index": {"Hypergraph": [0], "learning": [1]},
                        }
                    ]
                }
            ).encode("utf-8")

        if "export.arxiv.org" in url and "2506.99999" in url:
            xml = """<?xml version="1.0" encoding="UTF-8"?>
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <id>http://arxiv.org/abs/2506.99999v1</id>
                <published>2025-06-15T00:00:00Z</published>
                <title>Future Post-Cutoff Model</title>
                <summary>Post cutoff summary.</summary>
                <author><name>Jane Doe</name></author>
              </entry>
            </feed>"""
            return xml.encode("utf-8")

        return b"{}"

    seed_bib = (
        "@article{black1973pricing,\n"
        "  title = {The Pricing of Options and Corporate Liabilities},\n"
        "  author = {Black, Fischer and Scholes, Myron},\n"
        "  journal = {Journal of Political Economy},\n"
        "  year = {1973}\n}"
    )

    cache_db = tmp_path / "citations.sqlite"
    verifier = MultiSourceCitationVerifier(
        cache_path=cache_db,
        cutoff_date="2025-01",
        allow_concurrent_tagging=False,
        http_get=fake_http_get,
    )

    queries = [
        CandidateQuery(
            title="Physics-informed neural networks",
            year_hint=2019,
            doi_hint="10.1000/raissi2019",
            priority="P0",
        ),
        CandidateQuery(title="Hypergraph Neural Networks", year_hint=2019, priority="P0"),
        # Duplicate of the OpenAlex paper above -> must deduplicate cleanly
        CandidateQuery(title="Hypergraph Neural Networks", year_hint=2019, priority="P1"),
        # Post-cutoff arXiv paper -> must be filtered out when allow_concurrent_tagging=False
        CandidateQuery(title="Future Post-Cutoff Model", year_hint=2025, arxiv_hint="2506.99999"),
    ]

    reg = verifier.build_registry(queries, seed_bib_text=seed_bib)
    assert len(reg.papers) == 3
    sources = {p.cite_key: p.verified_by for p in reg.papers}
    assert sources["black1973pricing"] == "seed_bib"
    assert "crossref" in sources.values()
    assert "openalex" in sources.values()

    # Re-running with the same SQLite cache should make zero new HTTP calls for cached hits
    calls_before = call_counter["count"]
    reg_cached = verifier.build_registry(queries[:2], seed_bib_text=seed_bib)
    assert len(reg_cached.papers) == 3
    assert call_counter["count"] == calls_before


# ---------------------------------------------------------------------------
# 2. Sandboxed Vector Plot & TikZ Runner Tests (AST Guard + Secret Scrubbing)
# ---------------------------------------------------------------------------


def test_ast_guard_blocks_unsafe_imports_and_exec() -> None:
    bad_src = "import subprocess\nimport urllib.request\nexec('print(1)')\n"
    errs = audit_plot_script_ast(bad_src)
    assert len(errs) == 3
    assert any("subprocess" in e for e in errs)
    assert any("urllib" in e for e in errs)
    assert any("exec()" in e for e in errs)


def test_sandbox_matplotlib_scrubs_secrets_and_outputs_vector_pdf_and_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "super_secret_do_not_leak")
    script = tmp_path / "plot_scores.py"
    script.write_text(
        "import os\n"
        "import matplotlib.pyplot as plt\n"
        "assert 'GEMINI_API_KEY' not in os.environ, 'Secret leaked into plot child env!'\n"
        "fig, ax = plt.subplots(figsize=(4, 3))\n"
        "ax.plot([1, 2, 3], [0.34, 0.41, 0.43])\n"
        "ax.set_title('Validation Curve')\n",
        encoding="utf-8",
    )
    out_pdf = tmp_path / "rendered" / "fig_curve.pdf"
    out_png = tmp_path / "rendered" / "fig_curve.png"
    res = run_matplotlib_script(script_path=script, output_pdf=out_pdf, output_png=out_png)
    assert res.succeeded is True, f"Plot runner failed: {res.errors}"
    assert out_pdf.is_file() and out_pdf.stat().st_size > 500
    assert out_png.is_file() and out_png.stat().st_size > 500


@pytest.mark.skipif(
    shutil.which("pdflatex") is None
    or (shutil.which("pdftoppm") is None and shutil.which("mgs") is None),
    reason="pdflatex + pdftoppm/mgs required",
)
def test_compile_tikz_diagram_produces_vector_pdf_and_300dpi_png(tmp_path: Path) -> None:
    tikz_file = tmp_path / "arch.tex"
    tikz_file.write_text(
        r"""
        \begin{tikzpicture}[node distance=1.5cm, >=Latex]
          \node[draw, rounded corners] (in) {Input $\mathcal{H}_t$};
          \node[draw, rounded corners, right=of in] (out) {Output $\hat{y}_t$};
          \draw[->] (in) -- (out);
        \end{tikzpicture}
        """,
        encoding="utf-8",
    )
    out_pdf = tmp_path / "rendered" / "fig_arch.pdf"
    out_png = tmp_path / "rendered" / "fig_arch.png"
    res = compile_tikz_diagram(tikz_tex_path=tikz_file, output_pdf=out_pdf, output_png=out_png)
    assert res.succeeded is True, f"TikZ runner failed: {res.errors}"
    assert out_pdf.is_file() and out_pdf.stat().st_size > 500
    assert out_png.is_file() and out_png.stat().st_size > 500


# ---------------------------------------------------------------------------
# 3. AGY Lifecycle Hooks Contract Tests (`PreToolUse` & `Stop`)
# ---------------------------------------------------------------------------


def test_hooks_pre_tool_use_blocks_raster_image_generator_only() -> None:
    deny_resp = handle_hook_payload(
        {
            "hookEventName": "PreToolUse",
            "toolCall": {
                "id": "t1",
                "name": "invoke_subagent",
                "args": {"TypeName": "image-generator", "Prompt": "Draw neural net"},
            },
        }
    )
    assert deny_resp["decision"] == "deny"
    assert "D-05" in deny_resp["reason"]

    allow_resp = handle_hook_payload(
        {
            "hookEventName": "PreToolUse",
            "toolCall": {
                "id": "t2",
                "name": "invoke_subagent",
                "args": {"TypeName": "research", "Prompt": "Audit papers"},
            },
        }
    )
    assert allow_resp == {"decision": "allow"}


def test_hooks_stop_prevents_loop_when_continuation_active_and_checks_bundle(
    tmp_path: Path,
) -> None:
    # 1. Continuation active -> always allow stop to prevent infinite loop
    assert handle_hook_payload(
        {
            "hookEventName": "Stop",
            "terminationReason": "NO_TOOL_CALL",
            "continuationActive": True,
            "cwd": str(tmp_path),
        }
    ) == {"decision": "allow"}

    # 2. Bundle with a fabricated table number -> Stop hook forces continuation with reason
    bundle = tmp_path / "paper_bundle"
    (bundle / "contract").mkdir(parents=True)
    (bundle / "state").mkdir(parents=True)
    (bundle / "manuscript").mkdir(parents=True)

    (bundle / "contract" / "experimental_log.md").write_text("Sharpe = 2.15\n", encoding="utf-8")
    (bundle / "contract" / "symbol_table.json").write_text(
        json.dumps({"bundle_id": "b1", "entries": []}), encoding="utf-8"
    )
    (bundle / "state" / "citation_registry.json").write_text(
        json.dumps({"papers": []}), encoding="utf-8"
    )
    (bundle / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{booktabs}\n\\begin{document}\n"
        "\\begin{tabular}{lc}\\toprule Model & Sharpe \\\\ "
        "\\midrule Ours & 9.99 \\\\ \\bottomrule\\end{tabular}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    stop_resp = handle_hook_payload(
        {
            "hookEventName": "Stop",
            "terminationReason": "NO_TOOL_CALL",
            "continuationActive": False,
            "cwd": str(bundle),
        }
    )
    assert stop_resp["decision"] == "continue"
    assert "numeric_fidelity" in stop_resp["reason"]
    assert "9.99" in stop_resp["reason"]
