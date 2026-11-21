"""Strict Pydantic v2 contracts and JSON Schema exporter for AGY Paper Co-Author.

Enforces architectural decisions D-01 through D-07 at the data-contract boundary:
- Zero raster image generation (VisualKind restricted to vector code or provided assets).
- Non-orphaned subsection hierarchy and referential integrity in OutlineContract.
- Multi-source citation verification and strict temporal cutoff in CitationRegistry.
- Un-bypassable 4-gate deterministic verification before accepting any revision.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CUTOFF_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
CITE_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]{1,63}$")
FIG_ID_PATTERN = re.compile(r"^fig_[a-z0-9_]{2,60}$")
BIB_HEADER_PATTERN = re.compile(r"^@[A-Za-z]+\s*\{\s*([^,\s]+)\s*,", re.DOTALL)

VisualKind = Literal["matplotlib_plot", "tikz_diagram", "provided_asset"]
DataSourceKind = Literal["idea.md", "experimental_log.md", "both", "provided"]
AspectRatio = Literal[
    "1:1", "1:4", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"
]
CitationSource = Literal["seed_bib", "openalex", "crossref", "arxiv", "semantic_scholar"]
CitationPriority = Literal["P0", "P1"]
GateName = Literal["numeric_fidelity", "citation_integrity", "latex_build", "symbol_table"]
ALL_GATES: tuple[GateName, ...] = (
    "numeric_fidelity",
    "citation_integrity",
    "latex_build",
    "symbol_table",
)
ReviewerRole = Literal["math_methodology", "empirical_evidence", "vlm_venue_layout"]
ALL_REVIEWER_ROLES: tuple[ReviewerRole, ...] = (
    "math_methodology",
    "empirical_evidence",
    "vlm_venue_layout",
)
ReviewDecisionOutcome = Literal["accept", "rollback", "await_hitl"]


def _parse_cutoff_boundary(cutoff_str: str) -> date:
    """Return strict exclusive upper-bound date (first day of month when YYYY-MM)."""
    if not CUTOFF_PATTERN.match(cutoff_str):
        raise ValueError(f"Invalid cutoff_date '{cutoff_str}'; expected YYYY-MM or YYYY-MM-DD.")
    parts = [int(p) for p in cutoff_str.split("-")]
    if len(parts) == 2:
        return date(parts[0], parts[1], 1)
    return date(parts[0], parts[1], parts[2])


class StrictContractModel(BaseModel):
    """Base contract forbidding undeclared fields and stripping accidental whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# 1. Symbol Table Contract (D-06 Gate 4)
# ---------------------------------------------------------------------------


class SymbolEntry(StrictContractModel):
    symbol: str = Field(..., min_length=1, description="Canonical LaTeX math token, e.g. X_t.")
    meaning: str = Field(..., min_length=3, description="Precise mathematical or domain meaning.")
    domain_or_shape: str = Field(
        ..., min_length=1, description="Set/space/tensor shape, e.g. R^{Nxd}."
    )
    defined_in_section: str = Field(
        ..., min_length=1, description="Section ID where first defined."
    )
    aliases: list[str] = Field(default_factory=list, description="Permitted macro aliases, if any.")


class SymbolTable(StrictContractModel):
    bundle_id: str = Field(..., min_length=1)
    entries: list[SymbolEntry] = Field(default_factory=list)
    reserved_index_tokens: list[str] = Field(
        default_factory=lambda: ["i", "j", "k", "t", "n", "m"],
        description="Local loop/index variables exempt from global redefinition errors.",
    )

    @model_validator(mode="after")
    def _validate_unique_symbols(self) -> SymbolTable:
        seen: set[str] = set()
        for entry in self.entries:
            tokens = [entry.symbol, *entry.aliases]
            for tok in tokens:
                if not tok:
                    raise ValueError("Empty symbol or alias token is not allowed.")
                if tok in seen:
                    raise ValueError(f"Duplicate or colliding mathematical symbol token: '{tok}'.")
                seen.add(tok)
        return self


# ---------------------------------------------------------------------------
# 2. Outline Contract (D-01, D-05)
# ---------------------------------------------------------------------------


class VisualSpec(StrictContractModel):
    figure_id: str = Field(..., pattern=FIG_ID_PATTERN.pattern)
    title: str = Field(..., min_length=3)
    visual_kind: VisualKind
    data_source: DataSourceKind
    objective: str = Field(..., min_length=10)
    aspect_ratio: AspectRatio = "16:9"

    @model_validator(mode="after")
    def _forbid_redundant_figure_word_in_id(self) -> VisualSpec:
        if "figure" in self.figure_id.lower():
            raise ValueError(
                f"figure_id '{self.figure_id}' must use 'fig_' prefix without 'figure'."
            )
        return self


class RelatedWorkCluster(StrictContractModel):
    cluster_id: str = Field(..., min_length=2)
    subsection_title: str = Field(..., min_length=3)
    methodology_cluster: str = Field(..., min_length=3)
    sota_search_queries: list[str] = Field(..., min_length=1)
    limitation_hypothesis: str = Field(..., min_length=10)
    limitation_search_queries: list[str] = Field(..., min_length=1)
    bridge_to_our_method: str = Field(..., min_length=10)


class IntroRelatedWorkPlan(StrictContractModel):
    hook_hypothesis: str = Field(..., min_length=10)
    problem_gap_hypothesis: str = Field(..., min_length=10)
    macro_intro_queries: list[str] = Field(..., min_length=2, max_length=8)
    micro_rw_clusters: list[RelatedWorkCluster] = Field(..., min_length=2, max_length=6)


class SubsectionPlan(StrictContractModel):
    subsection_id: str = Field(..., min_length=2)
    subsection_title: str = Field(..., min_length=3)
    content_bullets: list[str] = Field(..., min_length=1)
    citation_hints: list[str] = Field(default_factory=list)
    required_symbols: list[str] = Field(default_factory=list)
    required_figures: list[str] = Field(default_factory=list)


class SectionPlan(StrictContractModel):
    section_id: str = Field(..., min_length=1)
    section_title: str = Field(..., min_length=2)
    content_bullets: list[str] = Field(default_factory=list)
    citation_hints: list[str] = Field(default_factory=list)
    required_figures: list[str] = Field(default_factory=list)
    subsections: list[SubsectionPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_hierarchy(self) -> SectionPlan:
        if len(self.subsections) == 1:
            raise ValueError(
                f"Section '{self.section_title}' has an orphaned single subsection; "
                "use 0 subsections or at least 2 subsections."
            )
        if not self.subsections and not self.content_bullets:
            raise ValueError(
                f"Leaf section '{self.section_title}' must specify non-empty content_bullets."
            )
        return self


class OutlineContract(StrictContractModel):
    title_working: str = Field(..., min_length=5)
    target_venue: str = Field(..., min_length=2)
    cutoff_date: str | None = Field(default=None)
    plotting_plan: list[VisualSpec] = Field(default_factory=list)
    intro_related_work_plan: IntroRelatedWorkPlan
    section_plan: list[SectionPlan] = Field(..., min_length=3)

    @model_validator(mode="after")
    def _validate_cross_references(self) -> OutlineContract:
        if self.cutoff_date is not None:
            _parse_cutoff_boundary(self.cutoff_date)
        declared_figs = [v.figure_id for v in self.plotting_plan]
        if len(declared_figs) != len(set(declared_figs)):
            raise ValueError("Duplicate figure_id detected in plotting_plan.")
        fig_set = set(declared_figs)
        for sec in self.section_plan:
            refs = [*sec.required_figures]
            for sub in sec.subsections:
                refs.extend(sub.required_figures)
            for ref in refs:
                if ref not in fig_set:
                    raise ValueError(
                        f"Section '{sec.section_title}' references undeclared figure_id '{ref}'."
                    )
        return self


# ---------------------------------------------------------------------------
# 3. Citation Registry Contract (D-04, D-06 Gate 2)
# ---------------------------------------------------------------------------


class ExternalIds(StrictContractModel):
    doi: str | None = None
    openalex_id: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None

    def has_any(self) -> bool:
        return any(bool(v) for v in (self.doi, self.openalex_id, self.arxiv_id, self.s2_id))


class VerifiedPaper(StrictContractModel):
    cite_key: str = Field(..., pattern=CITE_KEY_PATTERN.pattern)
    title: str = Field(..., min_length=3)
    authors: list[str] = Field(..., min_length=1)
    year: int = Field(..., ge=1800, le=2100)
    publication_date: str | None = Field(default=None)
    venue: str = Field(..., min_length=1)
    abstract: str | None = None
    priority: CitationPriority = "P1"
    verified_by: CitationSource
    seed_trusted: bool = False
    is_concurrent_only: bool = False
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    bibtex_entry: str = Field(..., min_length=20)

    @model_validator(mode="after")
    def _validate_paper_integrity(self) -> VerifiedPaper:
        if self.publication_date is not None:
            if not ISO_DATE_PATTERN.match(self.publication_date):
                raise ValueError(
                    f"Invalid publication_date '{self.publication_date}'; expected YYYY-MM-DD."
                )
            date.fromisoformat(self.publication_date)
        if not self.external_ids.has_any() and not (
            self.verified_by == "seed_bib" and self.seed_trusted
        ):
            raise ValueError(
                f"Paper '{self.cite_key}' lacks verified external_ids (doi/openalex/arxiv/s2)."
            )
        match = BIB_HEADER_PATTERN.match(self.bibtex_entry)
        if not match:
            raise ValueError(f"Paper '{self.cite_key}' has malformed BibTeX entry header.")
        bib_key = match.group(1)
        if bib_key != self.cite_key:
            raise ValueError(
                f"BibTeX header key '{bib_key}' does not match cite_key '{self.cite_key}'."
            )
        return self


class CitationRegistry(StrictContractModel):
    cutoff_date: str | None = None
    min_utilization_ratio: float = Field(default=0.85, ge=0.0, le=1.0)
    papers: list[VerifiedPaper] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_registry_cutoff_and_uniqueness(self) -> CitationRegistry:
        seen_keys: set[str] = set()
        cutoff_dt = _parse_cutoff_boundary(self.cutoff_date) if self.cutoff_date else None
        for p in self.papers:
            if p.cite_key in seen_keys:
                raise ValueError(f"Duplicate cite_key '{p.cite_key}' in CitationRegistry.")
            seen_keys.add(p.cite_key)
            if cutoff_dt and not p.is_concurrent_only:
                if p.publication_date is not None:
                    pub_dt = date.fromisoformat(p.publication_date)
                    if pub_dt >= cutoff_dt:
                        raise ValueError(
                            f"Paper '{p.cite_key}' ({p.publication_date}) violates cutoff "
                            f"'{self.cutoff_date}' without is_concurrent_only=True."
                        )
                elif p.year > cutoff_dt.year or (
                    p.year == cutoff_dt.year and cutoff_dt.month == 1 and cutoff_dt.day == 1
                ):
                    raise ValueError(
                        f"Paper '{p.cite_key}' (year={p.year}) violates "
                        f"cutoff '{self.cutoff_date}'."
                    )
        return self


# ---------------------------------------------------------------------------
# 4. Deterministic Gate Suite & Adversarial Review Panel (D-06, D-07)
# ---------------------------------------------------------------------------


class GateResult(StrictContractModel):
    gate: GateName
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _errors_imply_failed(self) -> GateResult:
        if self.passed and self.errors:
            raise ValueError(f"Gate '{self.gate}' cannot have passed=True with non-empty errors.")
        if not self.passed and not self.errors:
            raise ValueError(f"Failed gate '{self.gate}' must record at least one error reason.")
        return self


class DeterministicGateSuite(StrictContractModel):
    target_artifact: str = Field(..., min_length=1)
    gates: list[GateResult] = Field(..., min_length=4, max_length=4)
    all_passed: bool

    @model_validator(mode="after")
    def _validate_complete_four_gates(self) -> DeterministicGateSuite:
        present = tuple(g.gate for g in self.gates)
        if set(present) != set(ALL_GATES):
            raise ValueError(f"Gate suite must contain exactly {ALL_GATES}, got {present}.")
        expected_pass = all(g.passed for g in self.gates)
        if self.all_passed != expected_pass:
            raise ValueError(
                f"all_passed={self.all_passed} contradicts "
                f"individual gate statuses ({expected_pass})."
            )
        return self


class ReviewerCritique(StrictContractModel):
    reviewer_role: ReviewerRole
    score_1_to_10: float = Field(..., ge=1.0, le=10.0)
    blocking_issues: list[str] = Field(default_factory=list)
    non_blocking_suggestions: list[str] = Field(default_factory=list)
    strengths_to_preserve: list[str] = Field(default_factory=list)


class RevisionDecision(StrictContractModel):
    iteration: int = Field(..., ge=0, le=10)
    gates: DeterministicGateSuite
    reviews: list[ReviewerCritique] = Field(..., min_length=3, max_length=3)
    hitl_notes: list[str] = Field(default_factory=list)
    addressed_issues: list[str] = Field(default_factory=list)
    outcome: ReviewDecisionOutcome

    @model_validator(mode="after")
    def _enforce_panel_and_gate_invariants(self) -> RevisionDecision:
        roles = {r.reviewer_role for r in self.reviews}
        if roles != set(ALL_REVIEWER_ROLES):
            raise ValueError(
                f"RevisionDecision requires all 3 reviewer roles {ALL_REVIEWER_ROLES}, got {roles}."
            )
        if self.outcome == "accept" and not self.gates.all_passed:
            raise ValueError("Cannot set outcome='accept' when any deterministic gate has failed.")
        return self


# ---------------------------------------------------------------------------
# Deterministic JSON Schema Export & Sync Check
# ---------------------------------------------------------------------------

SCHEMA_REGISTRY: dict[str, type[StrictContractModel]] = {
    "symbol_table.schema.json": SymbolTable,
    "outline.schema.json": OutlineContract,
    "citation_registry.schema.json": CitationRegistry,
    "verification_report.schema.json": DeterministicGateSuite,
    "review_panel.schema.json": RevisionDecision,
}


def export_all_schemas(schemas_dir: Path, check_only: bool = False) -> list[Path]:
    """Export or verify canonical JSON Schema files in schemas_dir."""
    if not check_only:
        schemas_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    drifted: list[str] = []
    for filename, model_cls in SCHEMA_REGISTRY.items():
        target = schemas_dir / filename
        rendered = json.dumps(model_cls.model_json_schema(), indent=2, sort_keys=True) + "\n"
        if check_only:
            if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                drifted.append(filename)
        else:
            target.write_text(rendered, encoding="utf-8")
        written.append(target)
    if drifted:
        raise RuntimeError(f"JSON schemas out of sync with contracts.py: {drifted}")
    return written
