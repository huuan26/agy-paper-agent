---
name: paper-prose-audit
description: >-
  Audits and surgically refines academic LaTeX manuscripts to eliminate AI
  writing patterns using `avoid-ai-writing` and deterministic LaTeX prose
  rules while preserving 100% of numbers, citations, equations, and symbols.
---

# Academic LaTeX De-AI Prose Audit (`avoid-ai-writing` Bridge)

## Deterministic Audit & Surgical Edit Protocol
1. **Run Baseline Prose Audit**:
   ```powershell
   .\.venv\Scripts\python.exe -m agy_paper_agent audit-prose `
     --bundle-dir <bundle_path> `
     --report-out <bundle_path>/state/verification_reports/pre_prose_audit.json
   ```
2. **Consult `avoid-ai-writing` Catalog with Academic Carve-Outs**:
   - Load `avoid-ai-writing` rules (`SKILL.md` and `references/patterns.md`) in `technical` context.
   - **Protected LaTeX Regions (Never Mutate)**: Equations, inline math `$...$`, `tabular` cells, `\cite*`, `\ref`/`\Cref`/`\eqref`, `\label`, registered tokens in `contract/symbol_table.json`, and every grounded number from `contract/experimental_log.md`.
   - **Legitimate Domain Vocabulary (Keep)**: Statistical `significant`/`significance`, `dynamics`, `regime`, `robust`, `cointegration`, `asymptotic`, `equilibrium`, and `proposition`.
   - **High-Value Academic Targets (Fix Surgically)**:
     - Remove Tier-1A AI vocabulary (`delve`, `tapestry`, `testament to`, `pivotal`, `underscores`, `intricate`, `realm`, `ever-evolving`).
     - Cut self-labeling sentence openers (`Crucially,`, `Importantly,`, `Notably,`, `Remarkably,`) and repetitive transition openers (`Moreover,`, `Furthermore,`).
     - Break stacked trailing `-ing` participial chains (`, lifting ..., ranking ..., and beating ...`) into finite active clauses.
     - Split clause-stuffed sentences exceeding 85 prose words to raise syntactic entropy (`fnword-trigram-entropy`).
     - Enforce ASCII hyphens `-` in prose (zero Unicode em/en dashes or `---`).
3. **Snapshot & Dual Verification**:
   - Snapshot `manuscript/` before editing, apply minimal span-level surgical edits, and leave already-clean human paragraphs untouched.
   - Re-run both `verify-bundle` (all 4 deterministic gates must pass) and `audit-prose` (`post_prose_audit.json`) to confirm residual reduction and zero preservation regressions.
