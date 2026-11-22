# AGY Paper Co-Author (`agy-paper-agent`)

An Interactive Co-Author multi-agent plugin and Python SDK framework for authoring rigorous LaTeX scientific manuscripts on Google Antigravity (AGY).

Inspired by the multi-agent decomposition of PaperOrchestra (arXiv:2604.05018), `agy-paper-agent` replaces prompt-only instructions and raster diagram generation with deterministic programmatic verification gates, multi-source scholarly authentication, pure code-vector visuals, and rollback-safe adversarial refinement.

## Core Architectural Guarantees

1. **Dual-Surface Execution (`D-01`)**:
   - **AGY Native Plugin**: Ships `plugin.json`, `rules/AGENTS.md`, `hooks.json`, 5 specialized `SKILL.md` runbooks, and dynamic `workflows/paper_pipeline.py` (`run_workflow`).
   - **Google Antigravity Python SDK (`google.antigravity`)**: Reuses 100% of core contracts, verifiers, and skills via `GoogleAntigravityBackend` and `SDKPaperCoAuthorRunner` (`AgentBehavior.INTERACTIVE` for Co-Author mode, `AgentBehavior.AUTONOMOUS` for batch benchmarking).
2. **Optional Stage-0 Ingestion Adapter (`D-02`)**:
   - Accepts a canonical `paper_bundle/` (`contract/idea.md`, `contract/experimental_log.md`, `contract/symbol_table.json`). Automatically bypasses Stage 0 when canonical files are present, or extracts them with `provenance_map.json` from raw research workspaces.
3. **Stage-Gated Interactive Co-Author (`D-03`)**:
   - Enforces Human-in-the-Loop (HITL) approval checkpoints across all 6 stages (`stage0_ingest` through `stage5_refinement`) unless `auto_approve=True` is explicitly set for batch ablation runs.
4. **Multi-Source Citation Cascade with Local Cache (`D-04`)**:
   - Merges curated `seed_references.bib` entries with candidate queries authenticated sequentially across **Crossref REST API -> OpenAlex -> arXiv Atom API -> Semantic Scholar**, backed by a local SQLite cache and strict `cutoff_date` filtering.
5. **100% Pure Code-Vector Visuals (`D-05`)**:
   - Blocks raster `image-generator` calls via both AGY `PreToolUse` lifecycle hooks and SDK `policy.deny` predicates.
   - Executes empirical Matplotlib scripts (`.py`) inside a secret-scrubbed subprocess after static AST security checks, and compiles standalone TikZ/PGFPlots diagrams (`.tex`) with `-no-shell-escape` to vector `.pdf` and 300-DPI `.png`.
6. **Four Deterministic Verification Gates (`D-06`)**:
   - `numeric_fidelity`: Precision-aware decimal rounding verification across LaTeX tables, quantitative prose claims, and AST-parsed Matplotlib data series against `experimental_log.md`.
   - `citation_integrity`: Balanced-brace BibTeX verification, registry synchronization, pool utilization ratio, and post-cutoff superiority-claim blocking.
   - `latex_build`: Hermetic `pdflatex`/`xelatex` + `bibtex`/`biber` build check catching undefined references/citations (`natbib`/`biblatex`), page-limit violations, and severe `Overfull \hbox` margin overflows.
   - `symbol_table`: Cross-section mathematical symbol consistency checking (use-before-definition, macro overrides, and domain/shape conflicts).
7. **Adversarial 3-Reviewer Panel & Automatic Rollback (`D-07`)**:
   - Evaluates drafts across three specialist lenses (`math_methodology`, `empirical_evidence`, `vlm_venue_layout`), integrates user `hitl_notes`, revises in an isolated branch/snapshot, and automatically rolls back `manuscript/` if any deterministic gate fails.

## Repository Layout

```text
agy-paper-agent/
|-- plugin.json                     # AGY Native Plugin manifest
|-- hooks.json                      # AGY PreToolUse & Stop runtime guardrails
|-- scripts/run_hook.py             # Cross-platform .venv hook launcher (fail-open)
|-- rules/AGENTS.md                 # Authoring invariants loaded when plugin is active
|-- skills/                         # 5 progressive-disclosure AGY skills
|   |-- paper-coauthor/SKILL.md
|   |-- paper-ingestion/SKILL.md
|   |-- paper-lit-verify/SKILL.md
|   |-- paper-vector-viz/SKILL.md
|   `-- paper-refinement/SKILL.md
|-- workflows/                      # Dynamic AGY run_workflow script & schema
|   |-- paper_pipeline.py
|   `-- workflow.json
|-- schemas/                        # Deterministic JSON Schemas exported from contracts.py
|-- templates/                      # Clean single-column & two-column LaTeX templates
|-- src/agy_paper_agent/            # Lean Python core (all modules <= 400 lines)
|   |-- contracts.py                # Pydantic v2 single source of truth
|   |-- bundle.py                   # paper_bundle lifecycle & 4-gate runner
|   |-- hooks_entry.py              # AGY camelCase stdin/stdout hook handler
|   |-- sdk_tools.py                # SDK telemetry & custom tool wrappers
|   |-- sdk_adapter.py              # google.antigravity Agent & LocalAgentConfig runner
|   |-- ablation_harness.py         # 4 quantitative ablation benchmarks
|   |-- verifiers/                  # Gates 1-4 (numeric, citation, latex, symbols)
|   `-- tools/                      # Multi-API citation verifier & vector sandbox
|-- examples/pilot_rc_fihgnn/       # Verified 5-page end-to-end RC-FIHGNN pilot bundle
`-- tests/                          # Full unit, MiKTeX integration, and ablation test suite
```

## Installation & Setup

Create an isolated virtual environment inside the repository root:

```powershell
Set-Location C:\Users\ADMIN\Documents\agy-paper-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Optional Google Antigravity Python SDK dependency for standalone batch runs:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[sdk]"
```

To register as a global AGY plugin without copying files, add the parent path to `~/.gemini/config/plugins.json`:

```json
{
  "entries": [
    {
      "path": "C:/Users/ADMIN/Documents",
      "include_only": ["agy-paper-agent"]
    }
  ]
}
```

## CLI Usage

```powershell
# Verify JSON schemas in schemas/ match Pydantic models in contracts.py
.\.venv\Scripts\python.exe -m agy_paper_agent --check

# Initialize and inspect a canonical paper_bundle
.\.venv\Scripts\python.exe -m agy_paper_agent init-bundle --bundle-dir ./my_paper --template generic_article
.\.venv\Scripts\python.exe -m agy_paper_agent inspect-bundle --bundle-dir ./my_paper

# Authenticate candidate citations across Crossref, OpenAlex, arXiv, and Semantic Scholar
.\.venv\Scripts\python.exe -m agy_paper_agent verify-citations `
  --candidates-json ./my_paper/state/raw_candidates.json `
  --output-registry ./my_paper/state/citation_registry.json `
  --output-bib ./my_paper/manuscript/references.bib `
  --seed-bib ./my_paper/contract/seed_references.bib `
  --cache-db ./my_paper/state/citations_cache.sqlite `
  --cutoff 2026-06

# Build pure code-vector Matplotlib or standalone TikZ visuals in an isolated sandbox
.\.venv\Scripts\python.exe -m agy_paper_agent build-visual `
  --kind tikz `
  --source ./my_paper/figures/tikz/fig_arch.tex `
  --pdf ./my_paper/figures/rendered/fig_arch.pdf `
  --png ./my_paper/figures/rendered/fig_arch.png

# Run all 4 deterministic gates and export compiled PDF
.\.venv\Scripts\python.exe -m agy_paper_agent verify-bundle `
  --bundle-dir ./examples/pilot_rc_fihgnn `
  --enforce-utilization `
  --output-pdf ./examples/pilot_rc_fihgnn/manuscript/main.pdf

# Run adversarial guardrail ablations on a clean bundle
.\.venv\Scripts\python.exe -m agy_paper_agent run-ablations `
  --bundle-dir ./examples/pilot_rc_fihgnn
```

## Verification Suite

```powershell
Set-Location C:\Users\ADMIN\Documents\agy-paper-agent
.\.venv\Scripts\python.exe -m agy_paper_agent --check
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## License

Apache-2.0
