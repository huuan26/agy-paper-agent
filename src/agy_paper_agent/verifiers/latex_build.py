"""Gate 3: Deterministic LaTeX compilation and layout diagnostics (MiKTeX / TeX Live)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from agy_paper_agent.contracts import GateResult

LatexEngine = Literal["pdflatex", "xelatex"]

FATAL_LOG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^!\s+LaTeX Error:.*$", re.MULTILINE),
    re.compile(r"^!\s+Undefined control sequence.*$", re.MULTILINE),
    re.compile(r"^!\s+Emergency stop.*$", re.MULTILINE),
    re.compile(r"^!\s+Missing \$ inserted.*$", re.MULTILINE),
    re.compile(r"^!\s+Extra \}, or forgotten \$.*$", re.MULTILINE),
    re.compile(r"^!\s+Package [^\n]+ Error:.*$", re.MULTILINE),
)
UNDEFINED_REF_RE = re.compile(
    r"LaTeX Warning: (?:Reference|Citation) [`']([^']+)' on page \d+ undefined"
)
THERE_WERE_UNDEF_RE = re.compile(
    r"LaTeX Warning: There were (?:undefined references|multiply-defined labels)"
)
BIBTEX_ERR_RE = re.compile(
    r"(?:I didn't find a database entry for|Repeated entry---line|---while reading file)",
    re.IGNORECASE,
)
OVERFULL_HBOX_RE = re.compile(
    r"Overfull \\hbox \(([0-9]+(?:\.[0-9]+)?)pt too wide\) "
    r"in (?:paragraph|alignment) at lines (\d+)--(\d+)"
)
OUTPUT_PAGES_RE = re.compile(r"Output written on [^\(\n]+\((\d+) pages?, \d+ bytes?\)")


def _clean_tex_env() -> dict[str, str]:
    """Preserve OS/MiKTeX user cache paths on Windows while clearing custom TEXINPUTS overrides."""
    env = dict(os.environ)
    for var in ("TEXINPUTS", "TEXMFHOME", "TEXMF", "TEXMFVAR", "TEXMFCONFIG"):
        env.pop(var, None)
    return env


def _needs_bibtex(tex_text: str) -> bool:
    return bool(
        re.search(r"\\(?:bibliography|addbibresource)\s*\{", tex_text)
        and re.search(r"\\(?:cite\w*|nocite)\s*(?:\[[^\]]*\])*\s*\{", tex_text)
    )


def _uses_biber(tex_text: str) -> bool:
    return bool(re.search(r"\\usepackage(?:\[[^\]]*\])?\{biblatex\}", tex_text))


def verify_latex_build(
    *,
    source_dir: Path,
    tex_filename: str = "main.tex",
    engine: LatexEngine = "pdflatex",
    timeout_sec: int = 90,
    max_pages: int | None = None,
    overfull_error_pt: float = 15.0,
    output_pdf_path: Path | None = None,
) -> GateResult:
    """Compile LaTeX source in an isolated staging folder and audit .log/.blg diagnostics."""
    errors: list[str] = []
    warnings: list[str] = []

    tex_path = source_dir / tex_filename
    if not tex_path.is_file():
        return GateResult(
            gate="latex_build",
            passed=False,
            errors=[f"Entry TeX file not found: '{tex_path}'."],
        )

    if shutil.which(engine) is None:
        return GateResult(
            gate="latex_build",
            passed=False,
            errors=[f"LaTeX engine '{engine}' is not available on PATH."],
        )

    stem = Path(tex_filename).stem
    tex_content = tex_path.read_text(encoding="utf-8")
    run_bib = _needs_bibtex(tex_content)
    bib_tool = "biber" if _uses_biber(tex_content) else "bibtex"

    commands: list[list[str]] = [
        [engine, "-interaction=nonstopmode", "-halt-on-error", tex_filename]
    ]
    if run_bib:
        commands.append([bib_tool, stem])
        commands.append([engine, "-interaction=nonstopmode", "-halt-on-error", tex_filename])
    commands.append([engine, "-interaction=nonstopmode", "-halt-on-error", tex_filename])

    env = _clean_tex_env()
    page_count = 0
    max_overfull_pt = 0.0

    with tempfile.TemporaryDirectory(prefix="agy_latex_gate_") as tmp_str:
        work_dir = Path(tmp_str) / "build"
        shutil.copytree(source_dir, work_dir)

        for step_cmd in commands:
            cmd_label = " ".join(step_cmd)
            try:
                proc = subprocess.run(
                    step_cmd,
                    cwd=work_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_sec,
                    check=False,
                )
                if proc.returncode != 0:
                    errors.append(f"Command '{cmd_label}' exited with code {proc.returncode}.")
                    break
            except subprocess.TimeoutExpired:
                errors.append(f"Command '{cmd_label}' timed out after {timeout_sec}s.")
                break

        log_path = work_dir / f"{stem}.log"
        blg_path = work_dir / f"{stem}.blg"
        pdf_path = work_dir / f"{stem}.pdf"

        if log_path.is_file():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            for pat in FATAL_LOG_PATTERNS:
                for m in pat.finditer(log_text):
                    errors.append(m.group(0).strip())

            for um in UNDEFINED_REF_RE.finditer(log_text):
                errors.append(f"Undefined citation or reference: '{um.group(1)}'.")

            for tm in THERE_WERE_UNDEF_RE.finditer(log_text):
                errors.append(tm.group(0).strip())

            for om in OVERFULL_HBOX_RE.finditer(log_text):
                pts = float(om.group(1))
                max_overfull_pt = max(max_overfull_pt, pts)
                msg = f"Overfull hbox ({pts:.2f}pt) at lines {om.group(2)}-{om.group(3)}."
                if pts >= overfull_error_pt:
                    errors.append(msg)
                elif pts >= 1.0:
                    warnings.append(msg)

            pm = OUTPUT_PAGES_RE.search(log_text)
            if pm:
                page_count = int(pm.group(1))

        if blg_path.is_file():
            blg_text = blg_path.read_text(encoding="utf-8", errors="replace")
            if BIBTEX_ERR_RE.search(blg_text):
                for line in blg_text.splitlines():
                    if BIBTEX_ERR_RE.search(line):
                        errors.append(f"BibTeX error: {line.strip()}")

        if not pdf_path.is_file() and not errors:
            errors.append(f"Expected output PDF '{stem}.pdf' was not produced.")

        if max_pages is not None and page_count > max_pages:
            errors.append(f"Compiled PDF has {page_count} pages, exceeding max_pages={max_pages}.")

        if pdf_path.is_file() and output_pdf_path is not None and not errors:
            output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf_path, output_pdf_path)

    # Deduplicate error lines while preserving order
    dedup_errors = list(dict.fromkeys(errors))
    dedup_warnings = list(dict.fromkeys(warnings))

    return GateResult(
        gate="latex_build",
        passed=(len(dedup_errors) == 0),
        errors=dedup_errors,
        warnings=dedup_warnings,
        metrics={
            "page_count": page_count,
            "max_overfull_pt": round(max_overfull_pt, 2),
        },
    )
