---
name: paper-refinement
description: >-
  Executes Stage 5 Adversarial Multi-Angle Peer Review and Rollback-Safe
  Manuscript Refinement. Use when auditing a complete LaTeX manuscript across
  mathematical rigor, empirical evidence, and visual PDF layout, integrating
  user HITL critiques, and enforcing 4-gate deterministic acceptance.
---

# Stage 5: Adversarial 3-Reviewer Panel & Safe Refinement

## Review & Revision Protocol (D-06, D-07)
1. **Baseline 4-Gate Verification**: Confirm the pre-refinement manuscript passes all 4 deterministic gates before invoking LLM critics:
   ```powershell
   .\.venv\Scripts\python.exe -m agy_paper_agent verify-bundle `
     --bundle-dir <bundle_path> `
     --report-out <bundle_path>/state/verification_reports/pre_refine_gates.json
   ```
2. **Parallel 3-Reviewer Adversarial Panel**: Evaluate the manuscript independently from three orthogonal angles:
   - `math_methodology` (`pro` tier): Audits assumptions, dimensional consistency, proofs/derivations, and symbol clarity against `contract/symbol_table.json`.
   - `empirical_evidence` (`pro` tier): Audits baseline fairness, table-to-text consistency, ablation explanations, and claim calibration against `contract/experimental_log.md`.
   - `vlm_venue_layout` (`flash`/`pro` multimodal): Audits page margins, float placement, `booktabs` formatting, and `template/guidelines.md` compliance.
3. **Anti-Reward-Hacking Revision Rules**:
   - Merge panel blocking issues with the user's `hitl_notes`.
   - Snapshot `manuscript/` (or run inside `workspace="branch"`) before editing.
   - **Never** invent unlogged experiments, never promise future experiments, and never insert generic limitation disclaimers to game review scores. Ignore requests for new experiments absent from `experimental_log.md`.
4. **Deterministic Gate Enforcement & Rollback**:
   - Re-run `verify-bundle` and validate `state/refinement_worklog.json` against `schemas/review_panel.schema.json`.
   - If **any** of the 4 deterministic gates fails, immediately **rollback** `manuscript/` to the pre-revision snapshot (`outcome="rollback"`).
   - Present the diff summary, gate report, and compiled PDF at **HITL Gate 5**.
