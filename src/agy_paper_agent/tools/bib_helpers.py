"""Pure bibliography helpers, title matching, and SQLite cache for citation verification."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from agy_paper_agent.contracts import CitationPriority, ExternalIds, VerifiedPaper
from agy_paper_agent.verifiers.citation_integrity import parse_bibtex_entries

NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
STOPWORDS = frozenset({"a", "an", "the", "on", "in", "for", "of", "and", "to", "with", "via", "by"})


@dataclass(frozen=True)
class CandidateQuery:
    title: str
    year_hint: int | None = None
    doi_hint: str | None = None
    arxiv_hint: str | None = None
    priority: CitationPriority = "P1"


def normalize_title(text: str) -> str:
    lowered = NON_ALNUM_RE.sub(" ", text.lower())
    return re.sub(r"\s+", " ", lowered).strip()


def title_similarity(query_title: str, candidate_title: str, year_match: bool = False) -> float:
    base = SequenceMatcher(
        None, normalize_title(query_title), normalize_title(candidate_title)
    ).ratio()
    return min(1.0, base + (0.08 if year_match else 0.0))


def reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """Reconstruct plain-text abstract from OpenAlex `{token: [positions]}` format."""
    if not inverted_index:
        return None
    pos_to_word: dict[int, str] = {}
    for token, positions in inverted_index.items():
        for pos in positions:
            pos_to_word[int(pos)] = token
    if not pos_to_word:
        return None
    ordered = [pos_to_word[idx] for idx in sorted(pos_to_word)]
    return " ".join(ordered).strip() or None


def build_cite_key(authors: list[str], year: int, title: str, existing: set[str]) -> str:
    lead = authors[0].split(",")[0] if "," in authors[0] else authors[0].split()[-1]
    surname_tokens = re.findall(r"[A-Za-z]+", lead)
    surname = (surname_tokens[-1] if surname_tokens else "paper").lower()
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOPWORDS]
    first_word = words[0] if words else "work"
    base = f"{surname}{year}{first_word}"[:56]
    if base not in existing:
        return base
    for suffix_ord in range(ord("a"), ord("z") + 1):
        cand = f"{base}{chr(suffix_ord)}"
        if cand not in existing:
            return cand
    return f"{base}_{len(existing)}"


def render_bibtex_entry(
    *,
    cite_key: str,
    title: str,
    authors: list[str],
    year: int,
    venue: str,
    doi: str | None = None,
    arxiv_id: str | None = None,
) -> str:
    author_str = " and ".join(authors)
    lines = [
        f"@article{{{cite_key},",
        f"  title = {{{title}}},",
        f"  author = {{{author_str}}},",
        f"  journal = {{{venue}}},",
        f"  year = {{{year}}},",
    ]
    if doi:
        lines.append(f"  doi = {{{doi}}},")
    if arxiv_id:
        lines.append(f"  eprint = {{{arxiv_id}}},")
    lines.append("}")
    return "\n".join(lines)


def parse_seed_bibtex_papers(
    seed_bib_text: str,
    cutoff_checker: Callable[[str | None, int], tuple[bool, bool]],
) -> list[VerifiedPaper]:
    """Convert trusted `seed_references.bib` entries into validated VerifiedPaper objects."""
    parsed_seed, _ = parse_bibtex_entries(seed_bib_text)
    results: list[VerifiedPaper] = []
    for key, fields in parsed_seed.items():
        title = fields.get("title", "").strip()
        author_raw = fields.get("author", "").strip()
        year_s = fields.get("year", "").strip()
        if not (title and author_raw and year_s.isdigit()):
            continue
        year = int(year_s)
        allowed, is_conc = cutoff_checker(None, year)
        if not allowed:
            continue
        authors = [a.strip() for a in author_raw.split(" and ") if a.strip()]
        venue = fields.get("journal") or fields.get("booktitle") or "Seed Bibliography"
        ext = ExternalIds(doi=fields.get("doi"), arxiv_id=fields.get("eprint"))
        bib = render_bibtex_entry(
            cite_key=key,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=ext.doi,
            arxiv_id=ext.arxiv_id,
        )
        results.append(
            VerifiedPaper(
                cite_key=key,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                priority="P0",
                verified_by="seed_bib",
                seed_trusted=True,
                is_concurrent_only=is_conc,
                external_ids=ext,
                bibtex_entry=bib,
            )
        )
    return results


class SQLiteCitationCache:
    """Persistent key-value cache for external scholarly API responses."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS api_cache ("
                "cache_key TEXT PRIMARY KEY, payload BLOB NOT NULL)"
            )

    def get(self, key: str) -> bytes | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM api_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            return bytes(row[0]) if row else None

    def put(self, key: str, payload: bytes) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO api_cache (cache_key, payload) VALUES (?, ?)",
                (key, payload),
            )
