"""Telemetry models, backend protocol, and custom Python tools for the AGY Python SDK."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from agy_paper_agent.bundle import inspect_bundle, verify_paper_bundle
from agy_paper_agent.tools import (
    CandidateQuery,
    MultiSourceCitationVerifier,
    compile_tikz_diagram,
    run_matplotlib_script,
)


@dataclass(frozen=True)
class SDKBudgetSettings:
    max_model_calls: int = 25
    max_tool_calls: int = 60
    max_input_tokens: int = 400_000
    max_output_tokens: int = 80_000
    max_total_tokens: int = 480_000


@dataclass
class StageTelemetry:
    stage: str
    wall_clock_sec: float = 0.0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    candidates_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    stop_reason: str = "UNSPECIFIED"


@dataclass
class RunTelemetryReport:
    bundle_dir: str
    auto_approve: bool
    stages: list[StageTelemetry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_dir": self.bundle_dir,
            "auto_approve": self.auto_approve,
            "totals": {
                "wall_clock_sec": round(sum(s.wall_clock_sec for s in self.stages), 3),
                "prompt_tokens": sum(s.prompt_tokens for s in self.stages),
                "cached_tokens": sum(s.cached_tokens for s in self.stages),
                "candidates_tokens": sum(s.candidates_tokens for s in self.stages),
                "thoughts_tokens": sum(s.thoughts_tokens for s in self.stages),
                "total_tokens": sum(s.total_tokens for s in self.stages),
            },
            "stages": [asdict(s) for s in self.stages],
        }


class SDKBackendProtocol(Protocol):
    """Protocol decoupling orchestration from transport so SDK runs are offline-testable."""

    async def run_turn(
        self,
        prompt: str,
        *,
        stage_name: str,
        bundle_dir: Path,
        auto_approve: bool,
        response_schema: type[BaseModel] | None = None,
        model: str | None = None,
    ) -> tuple[Any, StageTelemetry]: ...


def build_sdk_custom_tools(
    bundle_dir: Path, *, cutoff_date: str | None = None
) -> list[Callable[..., str]]:
    """Build typed Python tool functions registered into `LocalAgentConfig(tools=...)`."""

    def inspect_paper_bundle_tool() -> str:
        """Inspect the active paper_bundle directory and report contract readiness."""
        st = inspect_bundle(bundle_dir)
        return json.dumps(asdict(st), default=str)

    def verify_citations_tool(candidates_json_path: str) -> str:
        """Verify candidate papers across Crossref, OpenAlex, arXiv, and Semantic Scholar.

        Args:
            candidates_json_path: Path to JSON array of candidate queries.
        """
        raw = json.loads(Path(candidates_json_path).read_text(encoding="utf-8"))
        queries = [CandidateQuery(**item) for item in raw]
        seed_path = bundle_dir / "contract" / "seed_references.bib"
        seed_txt = seed_path.read_text(encoding="utf-8") if seed_path.is_file() else None
        verifier = MultiSourceCitationVerifier(
            cache_path=bundle_dir / "state" / "citations_cache.sqlite",
            cutoff_date=cutoff_date,
        )
        reg = verifier.build_registry(queries, seed_bib_text=seed_txt)
        (bundle_dir / "state" / "citation_registry.json").write_text(
            json.dumps(reg.model_dump(), indent=2) + "\n", encoding="utf-8"
        )
        bib_body = "\n\n".join(p.bibtex_entry for p in reg.papers)
        (bundle_dir / "manuscript" / "references.bib").write_text(
            (bib_body + "\n") if bib_body else "", encoding="utf-8"
        )
        return json.dumps({"verified_papers": len(reg.papers)})

    def build_vector_visual_tool(kind: str, source_path: str, figure_id: str) -> str:
        """Compile a Matplotlib (.py) or TikZ (.tex) vector visual in an isolated sandbox.

        Args:
            kind: Either 'matplotlib' or 'tikz'.
            source_path: Path to the .py or .tex source file.
            figure_id: Canonical figure identifier (e.g. 'fig_convergence').
        """
        pdf_out = bundle_dir / "figures" / "rendered" / f"{figure_id}.pdf"
        png_out = bundle_dir / "figures" / "rendered" / f"{figure_id}.png"
        src = Path(source_path)
        if kind == "matplotlib":
            res = run_matplotlib_script(script_path=src, output_pdf=pdf_out, output_png=png_out)
        else:
            res = compile_tikz_diagram(tikz_tex_path=src, output_pdf=pdf_out, output_png=png_out)
        return json.dumps(
            {
                "succeeded": res.succeeded,
                "pdf_path": str(res.pdf_path) if res.pdf_path else None,
                "png_path": str(res.png_path) if res.png_path else None,
                "errors": res.errors,
            }
        )

    def run_deterministic_gates_tool(enforce_utilization: bool = False) -> str:
        """Execute all 4 deterministic gates (numeric, citation, LaTeX build, symbol table).

        Args:
            enforce_utilization: Require cited pool utilization >= min_utilization_ratio.
        """
        suite = verify_paper_bundle(bundle_dir, enforce_citation_utilization=enforce_utilization)
        return json.dumps(suite.model_dump())

    return [
        inspect_paper_bundle_tool,
        verify_citations_tool,
        build_vector_visual_tool,
        run_deterministic_gates_tool,
    ]
