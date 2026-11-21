---
name: paper-lit-verify
description: >-
  Executes Stage 2 Multi-Source Literature Discovery, API Authentication, and
  Introduction/Related Work synthesis. Use when building a verified citation
  registry from seed BibTeX and web search across Crossref, OpenAlex, arXiv, and
  Semantic Scholar, or when drafting grounded literature review sections.
---

# Stage 2: Multi-Source Literature Review & Citation Verification

## Procedure (D-04)
1. **Macro vs. Micro Scope Separation**: Read `<bundle_path>/state/outline.json` (`intro_related_work_plan`):
   - **Macro Introduction**: Broad problem urgency, surveys, and foundational papers (`priority="P1"` or `"P0"`).
   - **Micro Related Work**: 2-5 competing methodology clusters, SOTA baselines from `experimental_log.md`, and documented failure modes (`priority="P0"`).
2. **Parallel Candidate Discovery (`flash` tier)**: Pool candidate papers into `<bundle_path>/state/raw_candidates.json` as an array of `{"title", "year_hint", "doi_hint", "arxiv_hint", "priority"}`. Never invent DOIs or arXiv IDs; leave hints `null` when uncertain.
3. **Deterministic Multi-API Verification**: Run the cascading verifier (`seed_references.bib` -> Crossref -> OpenAlex -> arXiv -> Semantic Scholar with SQLite cache):
   ```powershell
   .\.venv\Scripts\python.exe -m agy_paper_agent verify-citations `
     --candidates-json <bundle_path>/state/raw_candidates.json `
     --output-registry <bundle_path>/state/citation_registry.json `
     --output-bib <bundle_path>/manuscript/references.bib `
     --cache-db <bundle_path>/state/citations_cache.sqlite `
     --cutoff <YYYY-MM>
   ```
4. **Grounded Synthesis (`pro` tier)**:
   - Cite **only** `cite_key`s present in `state/citation_registry.json`.
   - Integrate at least `min_utilization_ratio` (default 85%) of non-concurrent verified papers across `01_introduction.tex` and `02_related_work.tex`.
   - Never claim empirical superiority over a cited paper unless that exact baseline is evaluated in `contract/experimental_log.md`.
5. **Gate 2 Validation & HITL Gate 2**: Verify zero missing/misframed citations before presenting the citation registry and drafted sections to the user.
