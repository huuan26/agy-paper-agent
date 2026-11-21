"""Multi-source scholarly citation verifier with local SQLite cache (D-04).

Cascades deterministically across:
1. Seed BibTeX (`seed_references.bib`)
2. Crossref REST API (DOI & bibliographic search)
3. OpenAlex REST API (reconstructing inverted-index abstracts)
4. arXiv Atom API (exact arXiv ID & title search)
5. Semantic Scholar Graph API (optional API key read from env, never logged)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from pathlib import Path

from agy_paper_agent.contracts import (
    CitationRegistry,
    CitationSource,
    ExternalIds,
    VerifiedPaper,
    _parse_cutoff_boundary,
)
from agy_paper_agent.tools.bib_helpers import (
    CandidateQuery,
    SQLiteCitationCache,
    build_cite_key,
    normalize_title,
    parse_seed_bibtex_papers,
    reconstruct_openalex_abstract,
    render_bibtex_entry,
    title_similarity,
)

HttpGetter = Callable[[str, dict[str, str]], bytes]
JATS_TAG_RE = re.compile(r"<[^>]+>")


def _default_http_get(url: str, headers: dict[str, str], timeout_sec: float = 10.0) -> bytes:
    req_headers = {"User-Agent": "agy-paper-agent/0.1 (mailto:research@local)", **headers}
    backoff = 1.0
    for attempt in range(3):
        req = urllib.request.Request(url, headers=req_headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(backoff)
                backoff *= 2.0
                continue
            raise
    raise RuntimeError(f"Exhausted retries for URL: {url}")


def _safe_json(raw: bytes | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _identity_tokens(p: VerifiedPaper) -> set[str]:
    toks = {f"title:{normalize_title(p.title)}:{p.year}"}
    if p.external_ids.doi:
        toks.add(f"doi:{p.external_ids.doi.lower()}")
    if p.external_ids.openalex_id:
        toks.add(f"oa:{p.external_ids.openalex_id.lower()}")
    if p.external_ids.arxiv_id:
        toks.add(f"arxiv:{p.external_ids.arxiv_id.lower()}")
    if p.external_ids.s2_id:
        toks.add(f"s2:{p.external_ids.s2_id.lower()}")
    return toks


class MultiSourceCitationVerifier:
    """Cascading multi-API citation authenticator with cutoff enforcement and deduplication."""

    def __init__(
        self,
        *,
        cache_path: Path | None = None,
        cutoff_date: str | None = None,
        allow_concurrent_tagging: bool = False,
        min_title_similarity: float = 0.78,
        http_get: HttpGetter | None = None,
    ) -> None:
        self.cache = SQLiteCitationCache(cache_path) if cache_path else None
        self.cutoff_date = cutoff_date
        self.cutoff_dt = _parse_cutoff_boundary(cutoff_date) if cutoff_date else None
        self.allow_concurrent_tagging = allow_concurrent_tagging
        self.min_title_similarity = min_title_similarity
        self._http_get = http_get or _default_http_get

    def _fetch(
        self, cache_key: str, url: str, headers: dict[str, str] | None = None
    ) -> bytes | None:
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        try:
            raw = self._http_get(url, headers or {})
        except Exception:
            return None
        if self.cache and raw:
            self.cache.put(cache_key, raw)
        return raw

    def _check_cutoff(self, pub_date: str | None, year: int) -> tuple[bool, bool]:
        if self.cutoff_dt is None:
            return True, False
        violates = False
        if pub_date:
            violates = date.fromisoformat(pub_date) >= self.cutoff_dt
        elif year > self.cutoff_dt.year or (
            year == self.cutoff_dt.year and self.cutoff_dt.month == 1 and self.cutoff_dt.day == 1
        ):
            violates = True
        if not violates:
            return True, False
        return (True, True) if self.allow_concurrent_tagging else (False, False)

    def _try_crossref(self, q: CandidateQuery) -> dict | None:
        if q.doi_hint:
            doi_clean = q.doi_hint.strip()
            url = f"https://api.crossref.org/works/{urllib.parse.quote(doi_clean, safe='')}"
            msg = _safe_json(self._fetch(f"crossref:doi:{doi_clean.lower()}", url)).get("message")
            items = [msg] if isinstance(msg, dict) else []
        else:
            params = urllib.parse.urlencode({"query.bibliographic": q.title, "rows": 3})
            raw = self._fetch(
                f"crossref:q:{normalize_title(q.title)}", f"https://api.crossref.org/works?{params}"
            )
            items = (_safe_json(raw).get("message") or {}).get("items") or []

        for item in items:
            cand_title = (item.get("title") or [""])[0]
            date_parts = (
                (item.get("published-print") or {}).get("date-parts")
                or (item.get("published-online") or {}).get("date-parts")
                or (item.get("issued") or {}).get("date-parts")
                or [[None]]
            )[0]
            year = int(date_parts[0]) if date_parts and date_parts[0] else None
            if not cand_title or not year:
                continue
            sim = 1.0 if q.doi_hint else title_similarity(q.title, cand_title, q.year_hint == year)
            if sim < self.min_title_similarity:
                continue
            pub_date = (
                f"{int(date_parts[0]):04d}-{int(date_parts[1]):02d}-{int(date_parts[2]):02d}"
                if len(date_parts) >= 3 and all(date_parts[:3])
                else None
            )
            authors = [
                f"{a.get('given', '').strip()} {a.get('family', '').strip()}".strip()
                for a in item.get("author", [])
                if a.get("family") or a.get("given")
            ]
            if not authors:
                continue
            containers = item.get("container-title") or []
            abs_raw = item.get("abstract")
            return {
                "title": cand_title,
                "authors": authors,
                "year": year,
                "publication_date": pub_date,
                "venue": containers[0] if containers else "Crossref",
                "abstract": JATS_TAG_RE.sub("", abs_raw).strip() if abs_raw else None,
                "verified_by": "crossref",
                "external_ids": ExternalIds(doi=item.get("DOI")),
            }
        return None

    def _try_openalex(self, q: CandidateQuery) -> dict | None:
        params = urllib.parse.urlencode({"search": q.title, "per-page": 3})
        raw = self._fetch(
            f"openalex:q:{normalize_title(q.title)}", f"https://api.openalex.org/works?{params}"
        )
        for item in _safe_json(raw).get("results") or []:
            cand_title = item.get("title") or ""
            year = item.get("publication_year")
            if not cand_title or not year:
                continue
            if (
                title_similarity(q.title, cand_title, q.year_hint == int(year))
                < self.min_title_similarity
            ):
                continue
            authors = [
                (a.get("author") or {}).get("display_name", "").strip()
                for a in item.get("authorships", [])
                if (a.get("author") or {}).get("display_name")
            ]
            if not authors:
                continue
            doi = (item.get("doi") or "").replace("https://doi.org/", "").strip() or None
            loc = ((item.get("primary_location") or {}).get("source")) or {}
            return {
                "title": cand_title,
                "authors": authors,
                "year": int(year),
                "publication_date": item.get("publication_date"),
                "venue": loc.get("display_name") or "OpenAlex",
                "abstract": reconstruct_openalex_abstract(item.get("abstract_inverted_index")),
                "verified_by": "openalex",
                "external_ids": ExternalIds(doi=doi, openalex_id=item.get("id")),
            }
        return None

    def _try_arxiv(self, q: CandidateQuery) -> dict | None:
        if q.arxiv_hint:
            aid = q.arxiv_hint.replace("arXiv:", "").strip()
            params = urllib.parse.urlencode({"id_list": aid, "max_results": 1})
            cache_k = f"arxiv:id:{aid}"
        else:
            params = urllib.parse.urlencode({"search_query": f'ti:"{q.title}"', "max_results": 3})
            cache_k = f"arxiv:q:{normalize_title(q.title)}"
        raw = self._fetch(cache_k, f"https://export.arxiv.org/api/query?{params}")
        if not raw:
            return None
        try:
            root = ET.fromstring(raw.decode("utf-8", errors="replace"))
        except ET.ParseError:
            return None
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            cand_title = re.sub(r"\s+", " ", (entry.findtext("atom:title", "", ns) or "")).strip()
            published = (entry.findtext("atom:published", "", ns) or "")[:10]
            if not cand_title or len(published) < 4:
                continue
            year = int(published[:4])
            sim = (
                1.0 if q.arxiv_hint else title_similarity(q.title, cand_title, q.year_hint == year)
            )
            if sim < self.min_title_similarity:
                continue
            authors = [
                (a.findtext("atom:name", "", ns) or "").strip()
                for a in entry.findall("atom:author", ns)
                if (a.findtext("atom:name", "", ns) or "").strip()
            ]
            if not authors:
                continue
            id_url = (entry.findtext("atom:id", "", ns) or "").strip()
            arxiv_id = (
                id_url.rsplit("/abs/", maxsplit=1)[-1].split("v")[0]
                if "/abs/" in id_url
                else q.arxiv_hint
            )
            summary = re.sub(r"\s+", " ", (entry.findtext("atom:summary", "", ns) or "")).strip()
            return {
                "title": cand_title,
                "authors": authors,
                "year": year,
                "publication_date": published if len(published) == 10 else None,
                "venue": "arXiv preprint",
                "abstract": summary or None,
                "verified_by": "arxiv",
                "external_ids": ExternalIds(arxiv_id=arxiv_id),
            }
        return None

    def _try_semantic_scholar(self, q: CandidateQuery) -> dict | None:
        s2_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        headers = {"X-API-KEY": s2_key} if s2_key else {}
        params = urllib.parse.urlencode(
            {
                "query": q.title,
                "limit": 3,
                "fields": "paperId,title,authors,venue,year,abstract,publicationDate,externalIds",
            }
        )
        raw = self._fetch(
            f"s2:q:{normalize_title(q.title)}",
            f"https://api.semanticscholar.org/graph/v1/paper/search?{params}",
            headers=headers,
        )
        for item in _safe_json(raw).get("data") or []:
            cand_title = item.get("title") or ""
            year = item.get("year")
            if not cand_title or not year:
                continue
            if (
                title_similarity(q.title, cand_title, q.year_hint == int(year))
                < self.min_title_similarity
            ):
                continue
            authors = [a.get("name", "").strip() for a in item.get("authors", []) if a.get("name")]
            if not authors:
                continue
            ext = item.get("externalIds") or {}
            return {
                "title": cand_title,
                "authors": authors,
                "year": int(year),
                "publication_date": item.get("publicationDate"),
                "venue": item.get("venue") or "Semantic Scholar",
                "abstract": item.get("abstract"),
                "verified_by": "semantic_scholar",
                "external_ids": ExternalIds(
                    doi=ext.get("DOI"), arxiv_id=ext.get("ArXiv"), s2_id=item.get("paperId")
                ),
            }
        return None

    def verify_candidate(
        self, query: CandidateQuery, existing_keys: set[str]
    ) -> VerifiedPaper | None:
        """Cascade Crossref -> OpenAlex -> arXiv -> Semantic Scholar for one candidate."""
        for resolver in (
            self._try_crossref,
            self._try_openalex,
            self._try_arxiv,
            self._try_semantic_scholar,
        ):
            hit = resolver(query)
            if hit is None:
                continue
            allowed, is_conc = self._check_cutoff(hit["publication_date"], hit["year"])
            if not allowed:
                return None
            cite_key = build_cite_key(hit["authors"], hit["year"], hit["title"], existing_keys)
            ext: ExternalIds = hit["external_ids"]
            bib = render_bibtex_entry(
                cite_key=cite_key,
                title=hit["title"],
                authors=hit["authors"],
                year=hit["year"],
                venue=hit["venue"],
                doi=ext.doi,
                arxiv_id=ext.arxiv_id,
            )
            source: CitationSource = hit["verified_by"]
            return VerifiedPaper(
                cite_key=cite_key,
                title=hit["title"],
                authors=hit["authors"],
                year=hit["year"],
                publication_date=hit["publication_date"],
                venue=hit["venue"],
                abstract=hit["abstract"],
                priority=query.priority,
                verified_by=source,
                is_concurrent_only=is_conc,
                external_ids=ext,
                bibtex_entry=bib,
            )
        return None

    def build_registry(
        self,
        candidates: list[CandidateQuery],
        *,
        seed_bib_text: str | None = None,
        min_utilization_ratio: float = 0.85,
    ) -> CitationRegistry:
        """Merge seed BibTeX entries with verified candidates, deduplicating by ID and title."""
        papers: list[VerifiedPaper] = []
        used_keys: set[str] = set()
        seen_ids: set[str] = set()

        if seed_bib_text:
            for vp in parse_seed_bibtex_papers(seed_bib_text, self._check_cutoff):
                toks = _identity_tokens(vp)
                if not (toks & seen_ids):
                    papers.append(vp)
                    used_keys.add(vp.cite_key)
                    seen_ids.update(toks)

        for cand in candidates:
            vp = self.verify_candidate(cand, used_keys)
            if vp is None:
                continue
            toks = _identity_tokens(vp)
            if toks & seen_ids:
                continue
            papers.append(vp)
            used_keys.add(vp.cite_key)
            seen_ids.update(toks)

        return CitationRegistry(
            cutoff_date=self.cutoff_date,
            min_utilization_ratio=min_utilization_ratio,
            papers=papers,
        )
