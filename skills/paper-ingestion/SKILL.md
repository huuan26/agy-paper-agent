---
name: paper-ingestion
description: >-
  Executes Stage 0 Optional Ingestion Adapter to normalize raw research project
  workspaces (code, JSON logs, LaTeX drafts, Markdown notes) into a canonical
  paper_bundle contract with provenance mapping and mathematical symbol tables.
  Use when starting a paper from an unstructured research folder lacking
  canonical idea.md and experimental_log.md files.
---

# Stage 0: Optional Ingestion Adapter

## Bypass Rule (D-02)
1. Run `inspect-bundle` first:
   ```powershell
   .\.venv\Scripts\python.exe -m agy_paper_agent inspect-bundle --bundle-dir <bundle_path>
   ```
2. If `has_canonical_contract` is `true` and the user did not request forced re-extraction, **skip Stage 0** and proceed directly to Stage 1.

## Extraction Procedure (When `needs_stage0_ingestion == true`)
1. Survey the raw workspace (read `.md` blueprints, `.tex` math notes, `.json`/`.csv` experiment outputs, and training/evaluation configs; never fabricate unexecuted results).
2. Write three canonical files into `<bundle_path>/contract/`:
   - `idea.md`: Problem statement, core hypothesis, formal mathematical formulation (preserving exact LaTeX equations and variable definitions), and expected contributions.
   - `experimental_log.md`: Self-contained empirical record (datasets, splits, baselines, hyperparameters, exact raw numeric tables, and factual qualitative observations). Strip narrative cross-references like "see Figure 2".
   - `provenance_map.json`: JSON dictionary mapping each extracted table/metric/equation to its exact source file path and JSON key or line range.
3. Populate `<bundle_path>/contract/symbol_table.json` conforming strictly to `schemas/symbol_table.schema.json` (zero duplicate symbols or alias collisions).
4. If the workspace contains a curated `.bib` file, copy it to `<bundle_path>/contract/seed_references.bib`.
5. **HITL Gate 0**: Present `idea.md`, `experimental_log.md`, and `symbol_table.json` to the user and wait for approval before Stage 1.
