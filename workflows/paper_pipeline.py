"""Dynamic AGY `run_workflow` orchestrator for the 6-stage Interactive Co-Author pipeline.

Compatible with AGY `run_workflow` runtime rules (`run-workflow/SKILL.md`):
- Uses only Python standard library at top level (no local package imports required).
- Invokes deterministic verifiers, multi-API citation checks, and vector sandboxes via subprocess
  against the plugin's isolated `.venv` Python interpreter.
- Exposes `execute_pipeline(...)` with injectable workflow primitives (`phase`, `log`, `agent`,
  `parallel`) so offline `pytest` tests can verify every stage, model tier, and rollback path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = PLUGIN_ROOT / "schemas"


def _resolve_venv_python(plugin_root: Path) -> str:
    win_py = plugin_root / ".venv" / "Scripts" / "python.exe"
    posix_py = plugin_root / ".venv" / "bin" / "python"
    if win_py.is_file():
        return str(win_py)
    if posix_py.is_file():
        return str(posix_py)
    return sys.executable


def _run_plugin_cli(plugin_root: Path, cli_args: list[str]) -> tuple[int, str, str]:
    py_exe = _resolve_venv_python(plugin_root)
    proc = subprocess.run(
        [py_exe, "-m", "agy_paper_agent", *cli_args],
        cwd=plugin_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


async def execute_pipeline(
    run_args: dict[str, Any],
    *,
    phase_fn: Callable[[str], Any],
    log_fn: Callable[..., Any],
    agent_fn: Callable[..., Awaitable[Any]],
    parallel_fn: Callable[[list[Any], Callable[[Any], Awaitable[Any]]], Awaitable[list[Any]]],
    plugin_root: Path = PLUGIN_ROOT,
) -> dict[str, Any]:
    """Execute one stage (Interactive Co-Author default) or all stages (`auto_approve=True`)."""
    bundle_dir = Path(run_args["bundle_dir"]).resolve()
    stage = str(run_args.get("stage", "stage1_outline"))
    auto_approve = bool(run_args.get("auto_approve", False))
    force_ingest = bool(run_args.get("force_ingest", False))
    cutoff_date = run_args.get("cutoff_date")
    hitl_notes: list[str] = list(run_args.get("hitl_notes") or [])

    if stage == "all" and not auto_approve:
        raise ValueError(
            "D-03 Interactive Co-Author violation: stage='all' requires auto_approve=True. "
            "Run individual stages so the user can approve each HITL gate."
        )

    stages_to_run = (
        [
            "stage0_ingest",
            "stage1_outline",
            "stage2_literature",
            "stage3_visuals",
            "stage4_sections",
            "stage5_refinement",
        ]
        if stage == "all"
        else [stage]
    )
    summary: dict[str, Any] = {"bundle_dir": str(bundle_dir), "completed_stages": []}

    # --- Stage 0: Optional Ingestion Adapter (D-02) ---
    if "stage0_ingest" in stages_to_run:
        phase_fn("Stage 0 - Ingestion Adapter")
        rc, out, err = _run_plugin_cli(
            plugin_root, ["inspect-bundle", "--bundle-dir", str(bundle_dir)]
        )
        if rc != 0:
            raise RuntimeError(f"inspect-bundle failed: {err}")
        status = json.loads(out)
        if status["has_canonical_contract"] and not force_ingest:
            log_fn("Canonical contract detected; bypassing Stage 0 ingestion.")
            summary["stage0"] = {"bypassed": True}
        else:
            raw_ws = run_args.get("raw_workspace_dir") or str(bundle_dir)
            sym_schema = _load_schema("symbol_table.schema.json")
            sym_data = await agent_fn(
                (
                    f"Read research workspace '{raw_ws}', write canonical 'contract/idea.md', "
                    f"'contract/experimental_log.md', and 'contract/provenance_map.json' inside "
                    f"'{bundle_dir}', and return the canonical SymbolTable JSON."
                ),
                schema=sym_schema,
                role="Stage 0 Ingestion Adapter",
                model="pro",
            )
            (bundle_dir / "contract" / "symbol_table.json").write_text(
                json.dumps(sym_data, indent=2) + "\n", encoding="utf-8"
            )
            summary["stage0"] = {"bypassed": False, "symbols": len(sym_data.get("entries", []))}
        summary["completed_stages"].append("stage0_ingest")

    # --- Stage 1: Outline & Citation Strategy (D-01, D-05) ---
    if "stage1_outline" in stages_to_run:
        phase_fn("Stage 1 - Outline & Citation Strategy")
        outline_schema = _load_schema("outline.schema.json")
        outline_obj = await agent_fn(
            (
                f"Synthesize '{bundle_dir}/contract/idea.md', 'contract/experimental_log.md', "
                f"'template/template.tex', and 'template/guidelines.md' into a strict "
                f"OutlineContract (cutoff_date={cutoff_date!r}). Use ONLY vector visual kinds "
                f"('matplotlib_plot', 'tikz_diagram', or 'provided_asset')."
            ),
            schema=outline_schema,
            role="Outline Architect",
            model="pro",
        )
        (bundle_dir / "state" / "outline.json").write_text(
            json.dumps(outline_obj, indent=2) + "\n", encoding="utf-8"
        )
        summary["stage1"] = {"figures_planned": len(outline_obj.get("plotting_plan", []))}
        summary["completed_stages"].append("stage1_outline")

    # --- Stage 2: Multi-Source Literature Discovery & Verification (D-04) ---
    if "stage2_literature" in stages_to_run:
        phase_fn("Stage 2 - Multi-Source Literature Review")
        outline = json.loads((bundle_dir / "state" / "outline.json").read_text(encoding="utf-8"))
        irw = outline["intro_related_work_plan"]
        search_clusters: list[dict[str, Any]] = [
            {"label": "Macro Introduction", "queries": irw["macro_intro_queries"], "priority": "P1"}
        ]
        for cl in irw["micro_rw_clusters"]:
            search_clusters.append(
                {
                    "label": cl["subsection_title"],
                    "queries": [*cl["sota_search_queries"], *cl["limitation_search_queries"]],
                    "priority": "P0",
                }
            )

        cand_item_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "priority"],
                "properties": {
                    "title": {"type": "string"},
                    "year_hint": {"type": ["integer", "null"]},
                    "doi_hint": {"type": ["string", "null"]},
                    "arxiv_hint": {"type": ["string", "null"]},
                    "priority": {"type": "string", "enum": ["P0", "P1"]},
                },
            },
        }
        discovered_batches = await parallel_fn(
            search_clusters,
            lambda item: agent_fn(
                (
                    f"Search academic literature for cluster '{item['label']}' using queries "
                    f"{item['queries']} (cutoff={cutoff_date!r}, priority={item['priority']}). "
                    "Return candidate papers with exact titles and DOI/arXiv hints when known."
                ),
                schema=cand_item_schema,
                role=f"Lit Scout: {item['label'][:28]}",
                model="flash",
            ),
        )
        pooled_candidates = [c for batch in discovered_batches for c in batch]
        cands_path = bundle_dir / "state" / "raw_candidates.json"
        cands_path.write_text(json.dumps(pooled_candidates, indent=2) + "\n", encoding="utf-8")

        reg_path = bundle_dir / "state" / "citation_registry.json"
        bib_path = bundle_dir / "manuscript" / "references.bib"
        seed_bib = bundle_dir / "contract" / "seed_references.bib"
        cli_cmd = [
            "verify-citations",
            "--candidates-json",
            str(cands_path),
            "--output-registry",
            str(reg_path),
            "--output-bib",
            str(bib_path),
            "--cache-db",
            str(bundle_dir / "state" / "citations_cache.sqlite"),
        ]
        if seed_bib.is_file():
            cli_cmd.extend(["--seed-bib", str(seed_bib)])
        if cutoff_date:
            cli_cmd.extend(["--cutoff", str(cutoff_date)])
        rc, out, err = _run_plugin_cli(plugin_root, cli_cmd)
        if rc != 0:
            raise RuntimeError(f"Citation verification CLI failed: {err}")

        await agent_fn(
            (
                f"Draft 'manuscript/sections/01_introduction.tex' and "
                f"'manuscript/sections/02_related_work.tex' in '{bundle_dir}' using ONLY verified "
                f"keys in 'state/citation_registry.json' and 'state/outline.json'."
            ),
            schema={"type": "string"},
            role="Literature Synthesis Writer",
            model="pro",
        )
        summary["stage2"] = json.loads(out)
        summary["completed_stages"].append("stage2_literature")

    # --- Stage 3: Pure Code-Vector Visuals (D-05) ---
    if "stage3_visuals" in stages_to_run:
        phase_fn("Stage 3 - Pure Code-Vector Visuals")
        outline = json.loads((bundle_dir / "state" / "outline.json").read_text(encoding="utf-8"))
        plans = [
            p for p in outline.get("plotting_plan", []) if p["visual_kind"] != "provided_asset"
        ]

        async def _generate_and_compile_fig(fig: dict[str, Any]) -> dict[str, Any]:
            fid = fig["figure_id"]
            is_plot = fig["visual_kind"] == "matplotlib_plot"
            src_path = (
                bundle_dir / "figures" / "scripts" / f"{fid}.py"
                if is_plot
                else bundle_dir / "figures" / "tikz" / f"{fid}.tex"
            )
            pdf_out = bundle_dir / "figures" / "rendered" / f"{fid}.pdf"
            png_out = bundle_dir / "figures" / "rendered" / f"{fid}.png"

            await agent_fn(
                (
                    f"Write reproducible {'Matplotlib Python' if is_plot else 'standalone TikZ'} "
                    f"code to '{src_path}' for spec {json.dumps(fig)}, grounded strictly in "
                    f"'{bundle_dir}/contract/experimental_log.md' and 'contract/idea.md'."
                ),
                schema={"type": "string"},
                role=f"Vector Author: {fid[:24]}",
                model="pro",
            )
            kind_arg = "matplotlib" if is_plot else "tikz"
            rc, out, err = _run_plugin_cli(
                plugin_root,
                [
                    "build-visual",
                    "--kind",
                    kind_arg,
                    "--source",
                    str(src_path),
                    "--pdf",
                    str(pdf_out),
                    "--png",
                    str(png_out),
                ],
            )
            if rc != 0:
                raise RuntimeError(f"Sandbox visual build failed for '{fid}': {out or err}")
            caption = await agent_fn(
                (
                    f"Inspect rendered PNG '{png_out}' for overlap/clipping and return a concise "
                    f"plain-text academic LaTeX caption (without 'Figure X:' prefix) for '{fid}'."
                ),
                schema={"type": "string"},
                role=f"VLM Layout Critic: {fid[:22]}",
                model="flash",
            )
            return {"figure_id": fid, "pdf": str(pdf_out), "png": str(png_out), "caption": caption}

        built_figs = await parallel_fn(plans, _generate_and_compile_fig) if plans else []
        (bundle_dir / "state" / "figures_manifest.json").write_text(
            json.dumps(built_figs, indent=2) + "\n", encoding="utf-8"
        )
        summary["stage3"] = {"figures_built": len(built_figs)}
        summary["completed_stages"].append("stage3_visuals")

    # --- Stage 4: Grounded Section Drafting + 4-Gate Check (D-06) ---
    if "stage4_sections" in stages_to_run:
        phase_fn("Stage 4 - Section Drafting & 4-Gate Check")
        await agent_fn(
            (
                f"Complete remaining sections and assemble '{bundle_dir}/manuscript/main.tex' "
                f"preserving existing Introduction/Related Work, inspecting rendered figures in "
                f"'figures/rendered/', and obeying 'contract/symbol_table.json' and "
                f"'contract/experimental_log.md'."
            ),
            schema={"type": "string"},
            role="Section Writing Author",
            model="pro",
        )
        rep_path = bundle_dir / "state" / "verification_reports" / "stage4_gates.json"
        rc, out, err = _run_plugin_cli(
            plugin_root,
            ["verify-bundle", "--bundle-dir", str(bundle_dir), "--report-out", str(rep_path)],
        )
        gate_suite = json.loads(out) if out else {"all_passed": False, "error": err}
        if rc != 0 or not gate_suite.get("all_passed", False):
            raise RuntimeError(f"Stage 4 failed deterministic gates: {out or err}")
        summary["stage4"] = {"gates_all_passed": True}
        summary["completed_stages"].append("stage4_sections")

    # --- Stage 5: Adversarial 3-Reviewer Panel & Rollback-Safe Revision (D-07) ---
    if "stage5_refinement" in stages_to_run:
        phase_fn("Stage 5 - Adversarial Panel & Safe Revision")
        reviewer_roles = [
            ("math_methodology", "pro"),
            ("empirical_evidence", "pro"),
            ("vlm_venue_layout", "flash"),
        ]
        critique_schema = _load_schema("review_panel.schema.json")["$defs"]["ReviewerCritique"]
        reviews = await parallel_fn(
            reviewer_roles,
            lambda rm: agent_fn(
                (
                    f"Act as '{rm[0]}' critic on '{bundle_dir}/manuscript/main.tex' against "
                    f"'contract/experimental_log.md' and 'template/guidelines.md'. "
                    "Never request new unlogged experiments."
                ),
                schema=critique_schema,
                role=f"Critic: {rm[0]}",
                model=rm[1],
            ),
        )

        # Snapshot manuscript before revision so failed gates trigger deterministic rollback
        manuscript_dir = bundle_dir / "manuscript"
        backup_dir = bundle_dir / "state" / "_manuscript_rollback_snapshot"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(manuscript_dir, backup_dir)

        addressed = await agent_fn(
            (
                f"Revise '{manuscript_dir}/main.tex' to address blocking issues from "
                f"reviews={json.dumps(reviews)} and hitl_notes={json.dumps(hitl_notes)}. "
                "Strictly obey anti-reward-hacking rules: never fabricate experiments or pad "
                "generic limitation disclaimers. Return list of addressed issues."
            ),
            schema={"type": "array", "items": {"type": "string"}},
            role="Revision Author",
            model="pro",
            workspace="branch",
        )

        rep_path = bundle_dir / "state" / "verification_reports" / "stage5_gates.json"
        rc, out, _ = _run_plugin_cli(
            plugin_root,
            ["verify-bundle", "--bundle-dir", str(bundle_dir), "--report-out", str(rep_path)],
        )
        gates_obj = json.loads(out)
        if rc == 0 and gates_obj.get("all_passed", False):
            outcome = "accept" if auto_approve else "await_hitl"
        else:
            log_fn("Stage 5 revision violated deterministic gates; rolling back manuscript.")
            shutil.rmtree(manuscript_dir)
            shutil.copytree(backup_dir, manuscript_dir)
            outcome = "rollback"

        decision_record = {
            "iteration": 1,
            "gates": gates_obj,
            "reviews": reviews,
            "hitl_notes": hitl_notes,
            "addressed_issues": addressed,
            "outcome": outcome,
        }
        (bundle_dir / "state" / "refinement_worklog.json").write_text(
            json.dumps(decision_record, indent=2) + "\n", encoding="utf-8"
        )
        summary["stage5"] = {"outcome": outcome, "gates_all_passed": gates_obj.get("all_passed")}
        summary["completed_stages"].append("stage5_refinement")

    return summary


# Top-level entry when invoked directly by AGY `run_workflow`
if "agent" in globals() and "phase" in globals():
    _wf_res = await execute_pipeline(  # type: ignore[top-level-await]  # noqa: F704
        args,  # type: ignore[name-defined]  # noqa: F821
        phase_fn=phase,  # type: ignore[name-defined]  # noqa: F821
        log_fn=log,  # type: ignore[name-defined]  # noqa: F821
        agent_fn=agent,  # type: ignore[name-defined]  # noqa: F821
        parallel_fn=parallel,  # type: ignore[name-defined]  # noqa: F821
    )
    print(json.dumps(_wf_res, indent=2))
