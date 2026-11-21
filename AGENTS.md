# Repository Engineering Rules (`agy-paper-agent`)

## 1. Anti-Bloat & Code Quality
- Keep each Python module single-responsibility and lean (target 120-300 lines; hard ceiling 400 lines).
- Single source of truth for data contracts: define schemas once as strict `pydantic` v2 models (`extra="forbid"`) in `src/agy_paper_agent/contracts.py` and export `schemas/*.schema.json` deterministically via `python -m agy_paper_agent`.
- Include explicit type annotations on all function and method signatures.
- Always pass `encoding="utf-8"` when reading or writing text files.
- No emojis or decorative icons in source code, docstrings, schemas, or Markdown files; use ASCII hyphens `-`.

## 2. Environment & Verification Commands
- Always use the repository virtual environment `.\.venv\Scripts\python.exe`; never run global `pip install`.
- Before completing any milestone, all checks below must pass with zero errors from repo root:
  ```powershell
  Set-Location C:\Users\ADMIN\Documents\agy-paper-agent
  .\.venv\Scripts\python.exe -m agy_paper_agent --check
  .\.venv\Scripts\python.exe -m pytest
  .\.venv\Scripts\python.exe -m ruff check .
  .\.venv\Scripts\python.exe -m ruff format --check .
  ```

## 3. Plugin Domain Rules
Plugin runtime rules for manuscript authoring live at @[Plugin Rules](rules/AGENTS.md).
