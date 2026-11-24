# AGY Paper Co-Author Plugin Rules

These invariants govern every stage of scientific manuscript authoring when the `agy-paper-agent` plugin is active.

## 1. Epistemic & Scientific Integrity (Zero Hallucination)
- **Strict Grounding**: Every numerical claim, metric, hyperparameter, dataset size, and ablation outcome in the manuscript or plotting scripts MUST trace directly to `contract/experimental_log.md` or `contract/provenance_map.json`. Never extrapolate, interpolate, or invent numbers.
- **Closed Verified Bibliography**: Every `\cite{...}` command MUST reference a `cite_key` registered in `state/citation_registry.json` and `manuscript/references.bib`. Never fabricate citation keys, authors, venues, or DOIs.
- **Temporal Cutoff Discipline**: When `cutoff_date` is set on a bundle, papers published strictly on or after the cutoff boundary MUST NOT be treated as prior baselines to beat; frame them only as concurrent work if explicitly marked `is_concurrent_only=true`.
- **Anti-Reward-Hacking**: During peer-review refinement, NEVER fabricate additional experiments, never promise future experiments to appease a reviewer, and never pad superficial "limitations" sections to game evaluation rubrics. Address critiques strictly by clarifying logic, mathematical exposition, and empirical presentation supported by existing logs.

## 2. Pure Code-Vector Visuals (Zero Raster Image Generation)
- **Forbidden Tooling**: NEVER invoke raster image generation models (`image-generator` or pixel diffusion/autoregressive image APIs) for scientific plots or conceptual architecture diagrams.
- **Allowed Visual Modalities**:
  1. `provided_asset`: Pre-existing empirical figures supplied by the author.
  2. `matplotlib_plot`: Reproducible Python scripts (`figures/scripts/*.py`) reading exact values from logged data, executed in an isolated subprocess, exported as vector `.pdf` and 300-DPI `.png`.
  3. `tikz_diagram`: Standalone LaTeX TikZ/PGFPlots source (`figures/tikz/*.tex`) compiled to vector `.pdf` and rendered to `.png` for VLM layout inspection.

## 3. Interactive Co-Author & Deterministic Gate Protocol
- **Mandatory HITL Checkpoints**: Unless `auto_approve=true` is explicitly configured for batch benchmarking, stop and request explicit user approval after each stage:
  - Stage 0: Ingestion & Provenance Bundle (`idea.md`, `experimental_log.md`, `symbol_table.json`)
  - Stage 1: Outline & Citation Strategy (`state/outline.json`)
  - Stage 2: Verified Citation Pool + Introduction & Related Work
  - Stage 3: Vector Figures & Captions
  - Stage 4: Individual Core Sections (Methodology, Experiments, Conclusion, Abstract)
  - Stage 5: Adversarial 4-Reviewer Panel (`math_methodology`, `empirical_evidence`, `vlm_venue_layout`, `prose_style`) & Isolated Revision
- **4-Gate Pre-Condition**: Never mark a drafted section or revised manuscript as accepted (`outcome="accept"`) unless all four deterministic verifiers pass (`numeric_fidelity`, `citation_integrity`, `latex_build`, `symbol_table`) and `audit-prose` reports zero critical P0 AI-writing artifacts.

## 4. LaTeX, Prose Quality & Typography Standards
- Use `booktabs` (`\toprule`, `\midrule`, `\bottomrule`) for tables; never use vertical rules.
- Preserve template preambles and package options (never mutate `\usepackage[capitalize]{cleveref}`).
- Maintain strict mathematical symbol consistency against `contract/symbol_table.json`; never redefine a global symbol with conflicting semantics across sections.
- Use standard short ASCII hyphens `-` in prose and comments; never include Unicode em/en dashes, LaTeX `---` splices, decorative icons, or emojis in manuscripts, captions, or technical logs.
- Obey `avoid-ai-writing` / `paper-prose-audit` editorial discipline: avoid Tier-1A AI clichés (`delve`, `tapestry`, `testament to`, `pivotal`, `underscores`, `intricate`), cut self-labeling openers (`Crucially,`, `Importantly,`, `Notably,`) and stacked transition openers (`Moreover,`, `Furthermore,`), replace chained trailing `-ing` participial clauses with finite verbs, and keep prose sentences concise (typically <= 85 words).
