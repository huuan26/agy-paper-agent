"""AGY Lifecycle Hook entrypoint (camelCase JSON over stdin/stdout).

Implements two runtime guardrails per AGY `docs/hooks.md`:
1. `PreToolUse`: Denies `invoke_subagent` calls targeting `image-generator` (enforcing D-05).
2. `Stop`: When finishing a turn inside an active `paper_bundle/` (`continuationActive == false`
   and `terminationReason == "NO_TOOL_CALL"`), runs the 4 deterministic gates on `main.tex`
   and returns `{"decision": "continue", "reason": ...}` if any gate fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from agy_paper_agent.contracts import CitationRegistry, SymbolTable
from agy_paper_agent.verifiers import run_all_gates


def _find_active_paper_bundle(payload: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        candidates.append(Path(cwd))
        candidates.append(Path(cwd) / "paper_bundle")
    for wp in payload.get("workspacePaths") or []:
        if isinstance(wp, str) and wp:
            candidates.append(Path(wp))
            candidates.append(Path(wp) / "paper_bundle")

    for root in candidates:
        if (
            (root / "contract" / "experimental_log.md").is_file()
            and (root / "contract" / "symbol_table.json").is_file()
            and (root / "state" / "citation_registry.json").is_file()
            and (root / "manuscript" / "main.tex").is_file()
        ):
            return root
    return None


def handle_hook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Process a single AGY hook stdin JSON payload and return the stdout JSON response."""
    event = payload.get("hookEventName", "")

    if event == "PreToolUse":
        tool_call = payload.get("toolCall") or {}
        tool_name = str(tool_call.get("name", "")).lower()
        args = tool_call.get("args") or {}
        if tool_name == "invoke_subagent":
            sub_type = str(args.get("TypeName", "")).strip().lower()
            if sub_type == "image-generator":
                return {
                    "decision": "deny",
                    "reason": (
                        "Blocked by agy-paper-agent (D-05): raster 'image-generator' is forbidden "
                        "for scientific visuals. Generate reproducible Matplotlib or TikZ code."
                    ),
                }
        return {"decision": "allow"}

    if event == "Stop":
        # Never loop infinitely if a Stop hook already forced continuation in this turn
        if payload.get("continuationActive", False):
            return {"decision": "allow"}
        if payload.get("terminationReason") != "NO_TOOL_CALL":
            return {"decision": "allow"}

        bundle_dir = _find_active_paper_bundle(payload)
        if bundle_dir is None:
            return {"decision": "allow"}

        try:
            exp_log = (bundle_dir / "contract" / "experimental_log.md").read_text(encoding="utf-8")
            idea_path = bundle_dir / "contract" / "idea.md"
            idea_txt = idea_path.read_text(encoding="utf-8") if idea_path.is_file() else ""
            sym_table = SymbolTable.model_validate_json(
                (bundle_dir / "contract" / "symbol_table.json").read_text(encoding="utf-8")
            )
            cit_reg = CitationRegistry.model_validate_json(
                (bundle_dir / "state" / "citation_registry.json").read_text(encoding="utf-8")
            )
            bib_path = bundle_dir / "manuscript" / "references.bib"
            bib_txt = bib_path.read_text(encoding="utf-8") if bib_path.is_file() else ""
            main_tex = (bundle_dir / "manuscript" / "main.tex").read_text(encoding="utf-8")

            suite = run_all_gates(
                target_artifact="manuscript/main.tex",
                source_texts=[exp_log, idea_txt],
                ordered_sections=[("main.tex", main_tex)],
                bib_text=bib_txt,
                citation_registry=cit_reg,
                symbol_table=sym_table,
                latex_source_dir=bundle_dir / "manuscript",
                tex_filename="main.tex",
            )
        except Exception as exc:
            return {
                "decision": "continue",
                "reason": f"Paper bundle contract validation error: {exc}",
            }

        if not suite.all_passed:
            failed_msgs = [
                f"{g.gate}: {'; '.join(g.errors[:3])}" for g in suite.gates if not g.passed
            ]
            return {
                "decision": "continue",
                "reason": (
                    "Deterministic verification gates failed on manuscript/main.tex. "
                    "Fix before stopping: " + " | ".join(failed_msgs)
                ),
            }
        return {"decision": "allow"}

    return {}


def main() -> int:
    raw_in = sys.stdin.read().strip()
    payload = json.loads(raw_in) if raw_in else {}
    result = handle_hook_payload(payload)
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
