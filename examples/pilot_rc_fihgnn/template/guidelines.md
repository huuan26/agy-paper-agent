# Generic Single-Column Academic Article Guidelines

- **Format**: Single-column A4 (`11pt`, 1-inch margins), suitable for arXiv preprints, Applied Mathematics, Quantitative Finance, and Scientific ML technical papers.
- **Page Target**: 10-16 pages for main text (excluding bibliography and optional appendix), unless overridden by user constraints.
- **Tables**: Strictly use `booktabs` (`\toprule`, `\midrule`, `\bottomrule`); never use vertical lines `|` or `\hline`.
- **Figures**: Reference vector `.pdf` files from `figures/rendered/` via `\includegraphics[width=0.85\linewidth]{...}`; captions appear below figures and above tables, without manual "Figure X:" prefixes.
- **Citations**: Use `natbib` (`\citet{...}` for textual citations, `\citep{...}` for parenthetical citations) backed by `references.bib`.
- **Cross-References**: Preserve `\usepackage[capitalize]{cleveref}` and use `\cref{...}` / `\Cref{...}` consistently.
