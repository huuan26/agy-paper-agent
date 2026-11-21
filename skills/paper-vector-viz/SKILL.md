---
name: paper-vector-viz
description: >-
  Executes Stage 3 Pure Code-Vector Visual Generation using sandboxed Python
  Matplotlib scripts for empirical plots and standalone LaTeX TikZ/PGFPlots for
  conceptual diagrams. Use when creating, compiling, or auditing publication
  figures without raster image generation.
---

# Stage 3: Pure Code-Vector Visuals (Zero Raster)

## Strict Modality Rules (D-05)
- **Forbidden**: Never call `image-generator` or any raster pixel generation model.
- **Empirical Data Plots (`matplotlib_plot`)**:
  1. Write clean, deterministic Python script to `<bundle_path>/figures/scripts/<figure_id>.py`.
  2. Every plotted data series must match `contract/experimental_log.md` (enforced by Gate 1 AST numeric check). Do not import network, shell, or `subprocess` modules (blocked by `audit_plot_script_ast`).
  3. Execute inside the secret-scrubbed sandbox:
     ```powershell
     .\.venv\Scripts\python.exe -m agy_paper_agent build-visual `
       --kind matplotlib `
       --source <bundle_path>/figures/scripts/<figure_id>.py `
       --pdf <bundle_path>/figures/rendered/<figure_id>.pdf `
       --png <bundle_path>/figures/rendered/<figure_id>.png
     ```
- **Conceptual & Architecture Diagrams (`tikz_diagram`)**:
  1. Write standalone LaTeX TikZ/PGFPlots code to `<bundle_path>/figures/tikz/<figure_id>.tex` using relative node positioning (`right=of`, `below=of`) and exact math symbols from `contract/symbol_table.json`.
  2. Compile with `-no-shell-escape` and rasterize to 300-DPI PNG:
     ```powershell
     .\.venv\Scripts\python.exe -m agy_paper_agent build-visual `
       --kind tikz `
       --source <bundle_path>/figures/tikz/<figure_id>.tex `
       --pdf <bundle_path>/figures/rendered/<figure_id>.pdf `
       --png <bundle_path>/figures/rendered/<figure_id>.png
     ```

## VLM Layout Critique & HITL Gate 3
1. Read `<bundle_path>/figures/rendered/<figure_id>.png` directly using `read_file` to check for overlapping labels, clipped axes, illegible font sizes, or broken arrows (revise up to 3 rounds if defects appear).
2. Draft a plain-text academic caption (without `"Figure X:"` prefix) and pause at **HITL Gate 3** for user approval.
