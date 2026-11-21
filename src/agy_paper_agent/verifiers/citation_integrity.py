"""Gate 2: Deterministic citation, BibTeX, cutoff, and concurrent-work framing verifier."""

from __future__ import annotations

import re

from agy_paper_agent.contracts import CitationRegistry, GateResult
from agy_paper_agent.verifiers.numeric_fidelity import strip_latex_comments

CITE_CMD_RE = re.compile(
    r"\\(?:cite|citep|citet|citealt|citealp|citeauthor|citeyear|autocite|parencite)\*?"
    r"(?:\s*\[[^\]]*\])*\s*\{([^\}]+)\}"
)
BIB_ENTRY_START_RE = re.compile(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,")
SUPERIORITY_CLAIM_RE = re.compile(
    r"\b(outperforms?|surpass(?:es|ed)?|beats?|exceeds?|superior\s+to)\b",
    re.IGNORECASE,
)


def extract_cited_keys_with_sentences(tex: str) -> tuple[set[str], dict[str, list[str]]]:
    """Return unique cited keys and the sentences in which each key appears."""
    clean = strip_latex_comments(tex)
    sentences = re.split(r"(?<=[.!?])\s+|\n\s*\n", clean)
    all_keys: set[str] = set()
    key_sentences: dict[str, list[str]] = {}
    for sent in sentences:
        for m in CITE_CMD_RE.finditer(sent):
            raw_keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
            for k in raw_keys:
                all_keys.add(k)
                key_sentences.setdefault(k, []).append(sent.strip())
    return all_keys, key_sentences


def parse_bibtex_entries(bib_text: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Parse BibTeX entries with balanced braces; return (entries_by_key, parse_errors)."""
    entries: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    pos = 0
    n = len(bib_text)

    while True:
        m = BIB_ENTRY_START_RE.search(bib_text, pos)
        if not m:
            break
        entry_type = m.group(1).lower()
        key = m.group(2).strip()
        if entry_type in {"comment", "preamble", "string"}:
            pos = m.end()
            continue

        # Walk balanced braces starting from '{' of '@type{'
        brace_start = bib_text.find("{", m.start())
        depth = 0
        end_idx = brace_start
        while end_idx < n:
            ch = bib_text[end_idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            end_idx += 1

        if depth != 0:
            errors.append(f"Unclosed braces in BibTeX entry '{key}'.")
            break

        if key in entries:
            errors.append(f"Duplicate BibTeX entry key '{key}' in references.bib.")

        body = bib_text[m.end() : end_idx]
        fields: dict[str, str] = {"_type": entry_type}
        for fm in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(?:\{([^\}]*)\}|\"([^\"]*)\"|(\d+))", body
        ):
            fname = fm.group(1).lower()
            fval = (
                fm.group(2)
                if fm.group(2) is not None
                else (fm.group(3) if fm.group(3) is not None else fm.group(4) or "")
            )
            fields[fname] = fval.strip()

        entries[key] = fields
        pos = end_idx + 1

    return entries, errors


def verify_citation_integrity(
    *,
    tex_files: dict[str, str],
    bib_text: str,
    registry: CitationRegistry,
    enforce_utilization: bool = False,
    forbid_unused_bib: bool = False,
) -> GateResult:
    """Run Gate 2 across LaTeX files, references.bib, and CitationRegistry."""
    errors: list[str] = []
    warnings: list[str] = []

    bib_entries, bib_parse_errors = parse_bibtex_entries(bib_text)
    errors.extend(bib_parse_errors)

    reg_by_key = {p.cite_key: p for p in registry.papers}

    cited_keys: set[str] = set()
    sentences_by_key: dict[str, list[str]] = {}
    for label, content in tex_files.items():
        f_keys, f_sents = extract_cited_keys_with_sentences(content)
        cited_keys.update(f_keys)
        for k, sents in f_sents.items():
            sentences_by_key.setdefault(k, []).extend(f"[{label}] {s}" for s in sents)

    # 1. Every cited key in .tex must exist in BOTH references.bib and CitationRegistry
    for key in sorted(cited_keys):
        if key not in bib_entries:
            errors.append(f"Cited key '{key}' is missing from references.bib.")
        if key not in reg_by_key:
            errors.append(f"Cited key '{key}' is not registered in verified CitationRegistry.")
            continue

        paper = reg_by_key[key]
        if key in bib_entries:
            bib_fields = bib_entries[key]
            for req_field in ("title", "author", "year"):
                if not bib_fields.get(req_field):
                    errors.append(f"BibTeX entry '{key}' is missing required field '{req_field}'.")
            if bib_fields.get("year") and str(paper.year) != bib_fields["year"]:
                errors.append(
                    f"Year mismatch for '{key}': registry has {paper.year}, "
                    f"references.bib has {bib_fields['year']}."
                )

        # Concurrent-only framing check (cannot claim direct SOTA superiority over post-cutoff work)
        if paper.is_concurrent_only:
            for sent in sentences_by_key.get(key, []):
                if SUPERIORITY_CLAIM_RE.search(sent):
                    errors.append(
                        f"Post-cutoff concurrent paper '{key}' is framed with a "
                        f"superiority claim: {sent}"
                    )

    # 2. Unused entries in references.bib
    unused_bib = sorted(set(bib_entries) - cited_keys)
    if unused_bib:
        msg = f"Unused BibTeX entries in references.bib: {unused_bib}."
        if forbid_unused_bib:
            errors.append(msg)
        else:
            warnings.append(msg)

    # 3. Utilization ratio check on non-concurrent verified pool
    eligible_keys = {p.cite_key for p in registry.papers if not p.is_concurrent_only}
    utilization = (len(cited_keys & eligible_keys) / len(eligible_keys)) if eligible_keys else 1.0
    if eligible_keys and utilization < registry.min_utilization_ratio:
        msg = (
            f"Citation pool utilization {utilization:.2%} is below target "
            f"{registry.min_utilization_ratio:.2%} "
            f"({len(cited_keys & eligible_keys)}/{len(eligible_keys)})."
        )
        if enforce_utilization:
            errors.append(msg)
        else:
            warnings.append(msg)

    return GateResult(
        gate="citation_integrity",
        passed=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
        metrics={
            "cited_keys_count": len(cited_keys),
            "bib_entries_count": len(bib_entries),
            "registry_papers_count": len(registry.papers),
            "pool_utilization": round(utilization, 4),
        },
    )
