"""Canonical paper_bundle initializer, Stage-0 bypass detector, and bundle gate runner (D-02)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from agy_paper_agent.contracts import CitationRegistry, DeterministicGateSuite, SymbolTable
from agy_paper_agent.verifiers import run_all_gates

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_ROOT / "templates"

BUNDLE_SUBDIRS: tuple[str, ...] = (
    "contract",
    "template",
    "state",
    "state/verification_reports",
    "figures/scripts",
    "figures/tikz",
    "figures/rendered",
    "manuscript",
    "manuscript/sections",
)


@dataclass(frozen=True)
class BundleStatus:
    bundle_dir: Path
    has_canonical_contract: bool
    needs_stage0_ingestion: bool
    has_symbol_table: bool
    has_outline: bool
    has_citation_registry: bool
    has_main_tex: bool


def inspect_bundle(bundle_dir: Path) -> BundleStatus:
    """Inspect a `paper_bundle` directory and determine whether Stage-0 ingestion is needed."""
    idea = bundle_dir / "contract" / "idea.md"
    exp_log = bundle_dir / "contract" / "experimental_log.md"
    has_canonical = (
        idea.is_file()
        and idea.stat().st_size > 20
        and exp_log.is_file()
        and exp_log.stat().st_size > 20
    )
    return BundleStatus(
        bundle_dir=bundle_dir,
        has_canonical_contract=has_canonical,
        needs_stage0_ingestion=not has_canonical,
        has_symbol_table=(bundle_dir / "contract" / "symbol_table.json").is_file(),
        has_outline=(bundle_dir / "state" / "outline.json").is_file(),
        has_citation_registry=(bundle_dir / "state" / "citation_registry.json").is_file(),
        has_main_tex=(bundle_dir / "manuscript" / "main.tex").is_file(),
    )


def init_paper_bundle(
    bundle_dir: Path,
    *,
    bundle_id: str | None = None,
    template_name: str = "generic_article",
    templates_root: Path | None = None,
) -> Path:
    """Create canonical `paper_bundle/` structure with default state files and selected template."""
    t_root = templates_root or TEMPLATES_DIR
    src_tpl = t_root / template_name
    if not src_tpl.is_dir():
        raise ValueError(f"Unknown template '{template_name}' under '{t_root}'.")

    for rel in BUNDLE_SUBDIRS:
        (bundle_dir / rel).mkdir(parents=True, exist_ok=True)

    # Copy template assets without overwriting existing user customizations
    for item in src_tpl.iterdir():
        if item.is_file():
            dst = bundle_dir / "template" / item.name
            if not dst.exists():
                shutil.copy2(item, dst)

    main_tex = bundle_dir / "manuscript" / "main.tex"
    tpl_tex = bundle_dir / "template" / "template.tex"
    if not main_tex.exists() and tpl_tex.is_file():
        shutil.copy2(tpl_tex, main_tex)

    bib_file = bundle_dir / "manuscript" / "references.bib"
    if not bib_file.exists():
        bib_file.write_text("", encoding="utf-8")

    sym_path = bundle_dir / "contract" / "symbol_table.json"
    if not sym_path.exists():
        default_sym = SymbolTable(bundle_id=bundle_id or bundle_dir.name, entries=[])
        sym_path.write_text(json.dumps(default_sym.model_dump(), indent=2) + "\n", encoding="utf-8")

    reg_path = bundle_dir / "state" / "citation_registry.json"
    if not reg_path.exists():
        default_reg = CitationRegistry(papers=[])
        reg_path.write_text(json.dumps(default_reg.model_dump(), indent=2) + "\n", encoding="utf-8")

    return bundle_dir


def verify_paper_bundle(
    bundle_dir: Path,
    *,
    tex_filename: str = "main.tex",
    max_pages: int | None = None,
    enforce_citation_utilization: bool = False,
    allow_intro_symbol_preview: bool = False,
    report_out: Path | None = None,
) -> DeterministicGateSuite:
    """Run all 4 deterministic gates across an initialized `paper_bundle/`."""
    exp_path = bundle_dir / "contract" / "experimental_log.md"
    idea_path = bundle_dir / "contract" / "idea.md"
    sym_path = bundle_dir / "contract" / "symbol_table.json"
    reg_path = bundle_dir / "state" / "citation_registry.json"
    bib_path = bundle_dir / "manuscript" / "references.bib"
    manuscript_dir = bundle_dir / "manuscript"

    exp_text = exp_path.read_text(encoding="utf-8") if exp_path.is_file() else ""
    idea_text = idea_path.read_text(encoding="utf-8") if idea_path.is_file() else ""
    sym_table = SymbolTable.model_validate_json(sym_path.read_text(encoding="utf-8"))
    cit_reg = CitationRegistry.model_validate_json(reg_path.read_text(encoding="utf-8"))
    bib_text = bib_path.read_text(encoding="utf-8") if bib_path.is_file() else ""

    sections_dir = manuscript_dir / "sections"
    ordered_sections: list[tuple[str, str]] = []
    if sections_dir.is_dir():
        sec_files = sorted(sections_dir.glob("*.tex"))
        for sf in sec_files:
            ordered_sections.append((sf.stem, sf.read_text(encoding="utf-8")))
    if not ordered_sections:
        entry_tex = manuscript_dir / tex_filename
        ordered_sections.append(
            (tex_filename, entry_tex.read_text(encoding="utf-8") if entry_tex.is_file() else "")
        )

    scripts_dir = bundle_dir / "figures" / "scripts"
    plot_scripts = sorted(scripts_dir.glob("*.py")) if scripts_dir.is_dir() else []

    suite = run_all_gates(
        target_artifact=f"manuscript/{tex_filename}",
        source_texts=[exp_text, idea_text],
        ordered_sections=ordered_sections,
        bib_text=bib_text,
        citation_registry=cit_reg,
        symbol_table=sym_table,
        latex_source_dir=manuscript_dir,
        tex_filename=tex_filename,
        plot_scripts=plot_scripts,
        max_pages=max_pages,
        enforce_citation_utilization=enforce_citation_utilization,
        allow_intro_symbol_preview=allow_intro_symbol_preview,
    )

    if report_out is not None:
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text(json.dumps(suite.model_dump(), indent=2) + "\n", encoding="utf-8")

    return suite
