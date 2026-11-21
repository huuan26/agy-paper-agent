"""External verification and sandboxed vector-rendering tools for AGY Paper Co-Author."""

from agy_paper_agent.tools.bib_helpers import (
    CandidateQuery,
    SQLiteCitationCache,
    build_cite_key,
    reconstruct_openalex_abstract,
    render_bibtex_entry,
    title_similarity,
)
from agy_paper_agent.tools.citation_verifier import MultiSourceCitationVerifier
from agy_paper_agent.tools.sandbox_plot_runner import (
    VisualBuildResult,
    audit_plot_script_ast,
    compile_tikz_diagram,
    rasterize_pdf_to_png,
    run_matplotlib_script,
)

__all__ = [
    "CandidateQuery",
    "MultiSourceCitationVerifier",
    "SQLiteCitationCache",
    "VisualBuildResult",
    "audit_plot_script_ast",
    "build_cite_key",
    "compile_tikz_diagram",
    "rasterize_pdf_to_png",
    "reconstruct_openalex_abstract",
    "render_bibtex_entry",
    "run_matplotlib_script",
    "title_similarity",
]
