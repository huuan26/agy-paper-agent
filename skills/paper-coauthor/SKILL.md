---
name: paper-coauthor
description: >-
  Orchestrates the 6-stage Interactive Co-Author workflow for authoring rigorous
  LaTeX research manuscripts with multi-source citation verification, 100% vector
  code visuals (Matplotlib/TikZ), 4 deterministic verification gates, and a
  3-reviewer adversarial refinement loop. Activate when structuring, drafting,
  verifying, or refining academic papers from raw research workspaces or
  canonical paper bundles.
---

# AGY Paper Co-Author Skill

## Overview
This skill coordinates the 6-stage Interactive Co-Author pipeline defined by the JSON contracts in `schemas/` and enforced by the rules in `rules/AGENTS.md`:

1. **Stage 0 - Optional Ingestion Adapter**: Normalizes raw project workspaces into a canonical `paper_bundle/` (`contract/idea.md`, `contract/experimental_log.md`, `contract/provenance_map.json`, `contract/symbol_table.json`), or bypasses directly if the canonical files already exist.
2. **Stage 1 - Outline & Citation Strategy**: Produces `state/outline.json` conforming strictly to `schemas/outline.schema.json` (separating Macro Introduction queries from Micro Related Work methodology clusters, enforcing non-orphaned subsections, and planning vector-only visuals).
3. **Stage 2 - Multi-Source Literature Review**: Merges `seed_references.bib` with web-discovered candidates (`flash` tier) and verifies sequentially across OpenAlex, Crossref/DOI, arXiv, and Semantic Scholar into `state/citation_registry.json` (`schemas/citation_registry.schema.json`).
4. **Stage 3 - Pure Code-Vector Visuals**: Generates reproducible `figures/scripts/*.py` (Matplotlib in subprocess sandbox) and `figures/tikz/*.tex` (TikZ/PGFPlots), compiles to vector PDF + PNG, and runs VLM layout critique.
5. **Stage 4 - Section-by-Section Grounded Drafting**: Drafts individual sections with multimodal figure inspection; runs all 4 deterministic gates (`numeric_fidelity`, `citation_integrity`, `latex_build`, `symbol_table`) before each HITL checkpoint.
6. **Stage 5 - Adversarial Multi-Angle Refinement**: Runs 3 parallel specialist critics (`math_methodology`, `empirical_evidence`, `vlm_venue_layout`), merges user HITL feedback, edits on an isolated branch, and validates via `schemas/review_panel.schema.json` (rejecting/rolling back if any deterministic gate fails).

## Canonical Schemas
- `schemas/symbol_table.schema.json`
- `schemas/outline.schema.json`
- `schemas/citation_registry.schema.json`
- `schemas/verification_report.schema.json`
- `schemas/review_panel.schema.json`
