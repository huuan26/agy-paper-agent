---
name: paper-coauthor
description: >-
  Orchestrates the 6-stage Interactive Co-Author workflow for authoring rigorous
  LaTeX scientific manuscripts on AGY. Use this skill when initializing a
  paper_bundle, running stage-gated manuscript authoring, checking deterministic
  verification gates, or coordinating specialized ingestion, literature, vector
  visual, and adversarial refinement skills.
---

# AGY Paper Co-Author Orchestrator

## Stage-Gated Protocol (D-03 Interactive Co-Author)

Always initialize or inspect the target `paper_bundle/` first, then execute **one stage at a time**, presenting artifacts and verification reports to the user at each HITL checkpoint before proceeding:

1. **Initialize / Inspect Bundle**:
   ```powershell
   .\.venv\Scripts\python.exe -m agy_paper_agent init-bundle --bundle-dir <bundle_path> --template generic_article
   .\.venv\Scripts\python.exe -m agy_paper_agent inspect-bundle --bundle-dir <bundle_path>
   ```
2. **Stage 0 - Ingestion Adapter** (`paper-ingestion`): Run only when `needs_stage0_ingestion == true`; bypass directly to Stage 1 when `contract/idea.md` and `contract/experimental_log.md` already exist. Pause for HITL Gate 0.
3. **Stage 1 - Outline & Citation Strategy**: Run `workflows/paper_pipeline.py` with `stage="stage1_outline"` (or generate `state/outline.json` validated against `schemas/outline.schema.json`). Pause for HITL Gate 1.
4. **Stage 2 - Multi-Source Literature Review** (`paper-lit-verify`): Discover candidates (`flash`), authenticate via `verify-citations` CLI, and draft Introduction + Related Work (`pro`). Pause for HITL Gate 2.
5. **Stage 3 - Pure Code-Vector Visuals** (`paper-vector-viz`): Build Matplotlib/TikZ sources via `build-visual` CLI (`D-05` zero raster) and audit rendered PNGs. Pause for HITL Gate 3.
6. **Stage 4 - Section-by-Section Drafting**: Draft remaining sections grounded in `contract/symbol_table.json` and `contract/experimental_log.md`; run `verify-bundle` after each section. Pause for HITL Gate 4.
7. **Stage 5 - Adversarial Refinement** (`paper-refinement`): Run the 3-critic panel + isolated branch revision + automatic 4-gate rollback check. Pause for HITL Gate 5.

## Workflow Invocation
To delegate a single stage via AGY `run_workflow`:
- `ScriptPath`: `workflows/paper_pipeline.py`
- `Args`: `{"bundle_dir": "<abs_path>", "stage": "stage1_outline", "cutoff_date": "2025-10"}`
