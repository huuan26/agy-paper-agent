"""Unified CLI for AGY Paper Co-Author schemas, bundle management, citations, visuals, and gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agy_paper_agent.ablation_harness import ablate_deterministic_gates
from agy_paper_agent.bundle import (
    audit_bundle_prose,
    init_paper_bundle,
    inspect_bundle,
    verify_paper_bundle,
)
from agy_paper_agent.contracts import export_all_schemas
from agy_paper_agent.tools import (
    CandidateQuery,
    MultiSourceCitationVerifier,
    compile_tikz_diagram,
    run_matplotlib_script,
)

DEFAULT_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AGY Paper Co-Author deterministic CLI.")
    parser.add_argument("--schemas-dir", type=Path, default=DEFAULT_SCHEMAS_DIR)
    parser.add_argument("--check", action="store_true", help="Verify JSON schemas match contracts.")

    sub = parser.add_subparsers(dest="subcommand")

    p_init = sub.add_parser("init-bundle", help="Initialize a canonical paper_bundle directory.")
    p_init.add_argument("--bundle-dir", type=Path, required=True)
    p_init.add_argument("--template", default="generic_article")
    p_init.add_argument("--bundle-id", default=None)

    p_stat = sub.add_parser("inspect-bundle", help="Inspect Stage-0 bypass and contract status.")
    p_stat.add_argument("--bundle-dir", type=Path, required=True)

    p_vcit = sub.add_parser("verify-citations", help="Verify candidates across scholarly APIs.")
    p_vcit.add_argument("--candidates-json", type=Path, required=True)
    p_vcit.add_argument("--output-registry", type=Path, required=True)
    p_vcit.add_argument("--output-bib", type=Path, required=True)
    p_vcit.add_argument("--seed-bib", type=Path, default=None)
    p_vcit.add_argument("--cache-db", type=Path, default=None)
    p_vcit.add_argument("--cutoff", default=None)
    p_vcit.add_argument("--allow-concurrent", action="store_true")

    p_viz = sub.add_parser("build-visual", help="Compile Matplotlib or TikZ source in sandbox.")
    p_viz.add_argument("--kind", choices=["matplotlib", "tikz"], required=True)
    p_viz.add_argument("--source", type=Path, required=True)
    p_viz.add_argument("--pdf", type=Path, required=True)
    p_viz.add_argument("--png", type=Path, default=None)

    p_gate = sub.add_parser("verify-bundle", help="Run all 4 deterministic gates on paper_bundle.")
    p_gate.add_argument("--bundle-dir", type=Path, required=True)
    p_gate.add_argument("--tex-filename", default="main.tex")
    p_gate.add_argument("--max-pages", type=int, default=None)
    p_gate.add_argument("--enforce-utilization", action="store_true")
    p_gate.add_argument("--report-out", type=Path, default=None)
    p_gate.add_argument("--output-pdf", type=Path, default=None)

    p_abl = sub.add_parser("run-ablations", help="Run deterministic guardrails ablation on bundle.")
    p_abl.add_argument("--bundle-dir", type=Path, required=True)
    p_abl.add_argument("--report-out", type=Path, default=None)

    p_prose = sub.add_parser(
        "audit-prose", help="Audit LaTeX prose for AI-writing patterns via avoid-ai-writing."
    )
    p_prose.add_argument("--bundle-dir", type=Path, required=True)
    p_prose.add_argument("--tex-filename", default="main.tex")
    p_prose.add_argument("--max-issues-per-file", type=int, default=None)
    p_prose.add_argument("--max-sentence-words", type=int, default=85)
    p_prose.add_argument("--report-out", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.subcommand is None:
        export_all_schemas(args.schemas_dir, check_only=args.check)
        return 0

    if args.subcommand == "init-bundle":
        out = init_paper_bundle(
            args.bundle_dir, bundle_id=args.bundle_id, template_name=args.template
        )
        sys.stdout.write(json.dumps({"bundle_dir": str(out), "status": "initialized"}) + "\n")
        return 0

    if args.subcommand == "inspect-bundle":
        st = inspect_bundle(args.bundle_dir)
        sys.stdout.write(
            json.dumps(
                {
                    "bundle_dir": str(st.bundle_dir),
                    "has_canonical_contract": st.has_canonical_contract,
                    "needs_stage0_ingestion": st.needs_stage0_ingestion,
                    "has_symbol_table": st.has_symbol_table,
                    "has_outline": st.has_outline,
                    "has_citation_registry": st.has_citation_registry,
                    "has_main_tex": st.has_main_tex,
                },
                indent=2,
            )
            + "\n"
        )
        return 0

    if args.subcommand == "verify-citations":
        raw_cands = json.loads(args.candidates_json.read_text(encoding="utf-8"))
        queries = [CandidateQuery(**item) for item in raw_cands]
        seed_txt = args.seed_bib.read_text(encoding="utf-8") if args.seed_bib else None
        verifier = MultiSourceCitationVerifier(
            cache_path=args.cache_db,
            cutoff_date=args.cutoff,
            allow_concurrent_tagging=args.allow_concurrent,
        )
        reg = verifier.build_registry(queries, seed_bib_text=seed_txt)
        args.output_registry.parent.mkdir(parents=True, exist_ok=True)
        args.output_registry.write_text(
            json.dumps(reg.model_dump(), indent=2) + "\n", encoding="utf-8"
        )
        args.output_bib.parent.mkdir(parents=True, exist_ok=True)
        bib_body = "\n\n".join(p.bibtex_entry for p in reg.papers)
        args.output_bib.write_text((bib_body + "\n") if bib_body else "", encoding="utf-8")
        sys.stdout.write(json.dumps({"verified_papers": len(reg.papers)}) + "\n")
        return 0

    if args.subcommand == "build-visual":
        if args.kind == "matplotlib":
            res = run_matplotlib_script(
                script_path=args.source, output_pdf=args.pdf, output_png=args.png
            )
        else:
            res = compile_tikz_diagram(
                tikz_tex_path=args.source, output_pdf=args.pdf, output_png=args.png
            )
        sys.stdout.write(
            json.dumps(
                {
                    "succeeded": res.succeeded,
                    "pdf_path": str(res.pdf_path) if res.pdf_path else None,
                    "png_path": str(res.png_path) if res.png_path else None,
                    "errors": res.errors,
                },
                indent=2,
            )
            + "\n"
        )
        return 0 if res.succeeded else 1

    if args.subcommand == "verify-bundle":
        suite = verify_paper_bundle(
            args.bundle_dir,
            tex_filename=args.tex_filename,
            max_pages=args.max_pages,
            enforce_citation_utilization=args.enforce_utilization,
            report_out=args.report_out,
            output_pdf_path=args.output_pdf,
        )
        sys.stdout.write(json.dumps(suite.model_dump(), indent=2) + "\n")
        return 0 if suite.all_passed else 1

    if args.subcommand == "run-ablations":
        metrics = ablate_deterministic_gates(args.bundle_dir)
        payload = {
            "clean_bundle_false_positives": metrics.clean_bundle_false_positives,
            "injected_defects_total": metrics.injected_defects_total,
            "defects_caught_by_gates": metrics.defects_caught_by_gates,
            "defect_catch_rate": metrics.defect_catch_rate,
            "per_defect_caught": metrics.per_defect_caught,
        }
        rendered = json.dumps(payload, indent=2) + "\n"
        if args.report_out:
            args.report_out.parent.mkdir(parents=True, exist_ok=True)
            args.report_out.write_text(rendered, encoding="utf-8")
        sys.stdout.write(rendered)
        return 0 if metrics.defect_catch_rate == 1.0 else 1

    if args.subcommand == "audit-prose":
        report = audit_bundle_prose(
            args.bundle_dir,
            tex_filename=args.tex_filename,
            max_issues_per_file=args.max_issues_per_file,
            max_sentence_words=args.max_sentence_words,
            report_out=args.report_out,
        )
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
        return 0 if report.passed else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
