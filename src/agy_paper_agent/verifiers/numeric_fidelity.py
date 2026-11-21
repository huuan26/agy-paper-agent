"""Gate 1: Deterministic numeric fidelity verifier for LaTeX tables, prose, and plot scripts.

Enforces precision-aware rounding matching: a displayed number `c` with `d` decimal places
is grounded in source float `s` iff `|float(c) - s| <= 0.5 * 10**(-d) + 1e-12` (with explicit
support for percentage scaling when `%` / `\\%` is attached).
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path

from agy_paper_agent.contracts import GateResult

LATEX_COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
TABULAR_ENV_RE = re.compile(
    r"\\begin\{(tabular\*?|tabularx|nicematrix)\}(?:\[[^\]]*\])?(?:\{[^\}]*\})?(.*?)\\end\{\1\}",
    re.DOTALL,
)
STRUCTURAL_CMD_RE = re.compile(
    r"\\(?:multicolumn|multirow)\{\d+\}\{[^\}]*\}"
    r"|\\cmidrule(?:\([^\)]*\))?\{[\d\-]+\}"
    r"|\\(?:toprule|midrule|bottomrule|hline|cline\{[\d\-]+\})"
    r"|\[[+-]?\d+(?:\.\d+)?(?:pt|mm|cm|ex|em|in)\]"
    r"|\\(?:hspace|vspace)\*?\{[^\}]*\}"
    r"|^\s*\(\d+\)\s*",
    re.MULTILINE,
)
SCI_LATEX_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*\\(?:cdot|times)\s*10\^\{\s*([+-]?\d+)\s*\}")
TEN_POW_LATEX_RE = re.compile(r"(?<![\d\.])10\^\{\s*([+-]?\d+)\s*\}")
NUMBER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_\\])([+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(\s*\\?%)?"
)
PROSE_QUANT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(?:\\?%|\\pm\s*[+-]?\d+(?:\.\d+)?)")

PLOT_STYLE_KWARGS = frozenset(
    {
        "figsize",
        "dpi",
        "fontsize",
        "linewidth",
        "lw",
        "markersize",
        "ms",
        "alpha",
        "zorder",
        "rot",
        "rotation",
        "pad",
        "labelpad",
        "ncol",
        "nrow",
        "nrows",
        "ncols",
        "bins",
        "seed",
        "random_state",
        "capsize",
        "width",
        "height",
    }
)


@dataclass(frozen=True)
class SourceNumberPool:
    """Grounded numeric pool extracted from experimental_log.md, idea.md, and provenance JSON."""

    raw_values: tuple[float, ...]

    def matches(self, raw_literal: str, value: float, has_percent_context: bool = False) -> bool:
        decimals = _count_decimals(raw_literal)
        tol = 0.5 * (10.0 ** (-decimals)) + 1e-12
        candidates = [value]
        if has_percent_context:
            candidates.extend([value / 100.0, value * 100.0])
        for cand in candidates:
            for src in self.raw_values:
                if math.isclose(cand, src, abs_tol=tol, rel_tol=0.0):
                    return True
                if has_percent_context:
                    # Also allow comparing scaled source at candidate's displayed decimal precision
                    if math.isclose(value, src * 100.0, abs_tol=tol, rel_tol=0.0):
                        return True
                    if math.isclose(value, src / 100.0, abs_tol=tol, rel_tol=0.0):
                        return True
        return False


def _count_decimals(num_str: str) -> int:
    cleaned = num_str.replace(",", "").strip().lstrip("+-")
    if "e" in cleaned.lower():
        mantissa, exp_s = re.split(r"[eE]", cleaned, maxsplit=1)
        exp = int(exp_s)
        frac = len(mantissa.split(".")[1]) if "." in mantissa else 0
        return max(0, frac - exp)
    if "." in cleaned:
        return len(cleaned.split(".", maxsplit=1)[1])
    return 0


def strip_latex_comments(tex: str) -> str:
    return LATEX_COMMENT_RE.sub("", tex)


def extract_source_number_pool(*texts: str) -> SourceNumberPool:
    """Extract all grounded numeric values (including LaTeX sci-notation) from source docs."""
    values: list[float] = []
    for text in texts:
        if not text:
            continue
        for m in SCI_LATEX_RE.finditer(text):
            values.append(float(m.group(1)) * (10.0 ** int(m.group(2))))
        for m in TEN_POW_LATEX_RE.finditer(text):
            values.append(10.0 ** int(m.group(1)))
        for m in NUMBER_TOKEN_RE.finditer(text):
            lit = m.group(1).replace(",", "")
            pct = bool(m.group(2))
            val = float(lit)
            values.append(val)
            if pct:
                values.append(val / 100.0)
    return SourceNumberPool(raw_values=tuple(values))


def _check_latex_tables_and_prose(
    tex: str, label: str, pool: SourceNumberPool
) -> tuple[list[str], int]:
    errors: list[str] = []
    checked = 0
    clean_tex = strip_latex_comments(tex)

    for idx, tab_match in enumerate(TABULAR_ENV_RE.finditer(clean_tex), start=1):
        body = STRUCTURAL_CMD_RE.sub(" ", tab_match.group(2))
        # Replace LaTeX scientific notation inline before generic token scan
        for sm in SCI_LATEX_RE.finditer(body):
            checked += 1
            sval = float(sm.group(1)) * (10.0 ** int(sm.group(2)))
            exp = int(sm.group(2))
            pseudo_lit = f"{sm.group(1)}e{exp}"
            if not pool.matches(pseudo_lit, sval, has_percent_context=False):
                errors.append(f"{label} [table #{idx}]: ungrounded value '{sm.group(0)}' ({sval}).")
        body_no_sci = SCI_LATEX_RE.sub(" ", body)
        body_no_sci = TEN_POW_LATEX_RE.sub(" ", body_no_sci)

        # Remove citation/ref arguments inside tables
        body_no_sci = re.sub(r"\\(?:cite\w*|ref|eqref|label)\{[^\}]*\}", " ", body_no_sci)
        has_header_pct = "%" in body_no_sci

        for nm in NUMBER_TOKEN_RE.finditer(body_no_sci):
            lit = nm.group(1)
            val = float(lit.replace(",", ""))
            pct = bool(nm.group(2)) or has_header_pct
            checked += 1
            if not pool.matches(lit, val, has_percent_context=pct):
                errors.append(f"{label} [table #{idx}]: ungrounded cell value '{lit}'.")

    # Check prose quantitative claims with explicit % or \pm outside tabular environments
    non_table_tex = TABULAR_ENV_RE.sub(" ", clean_tex)
    non_table_tex = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^\}]*\}", " ", non_table_tex)
    for pm in PROSE_QUANT_RE.finditer(non_table_tex):
        full = pm.group(0)
        for nm in NUMBER_TOKEN_RE.finditer(full):
            lit = nm.group(1)
            val = float(lit.replace(",", ""))
            checked += 1
            if not pool.matches(lit, val, has_percent_context=("%" in full)):
                errors.append(f"{label} [prose claim '{full.strip()}']: ungrounded number '{lit}'.")

    return errors, checked


def _check_plot_script_ast(script_path: Path, pool: SourceNumberPool) -> tuple[list[str], int]:
    """Inspect data containers in Matplotlib scripts via AST, ignoring styling kwargs."""
    src = script_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(script_path))
    errors: list[str] = []
    checked = 0

    def _extract_num(node: ast.AST) -> tuple[str, float] | None:
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            seg = ast.get_source_segment(src, node) or str(node.value)
            return seg, float(node.value)
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
        ):
            seg = ast.get_source_segment(src, node) or ""
            sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
            return seg, sign * float(node.operand.value)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Skip styling assignments like FIGSIZE = (8, 4) or DPI = 300
            target_names = {t.id.lower() for t in node.targets if isinstance(t, ast.Name)}
            if target_names & PLOT_STYLE_KWARGS:
                continue
            if isinstance(node.value, (ast.List, ast.Tuple)):
                nums = [_extract_num(elt) for elt in node.value.elts]
                real_nums = [n for n in nums if n is not None]
                # Data series typically have >= 2 numeric points
                if len(real_nums) >= 2:
                    for seg, val in real_nums:
                        checked += 1
                        if not pool.matches(seg, val, has_percent_context=True):
                            errors.append(
                                f"{script_path.name}:L{node.lineno}: "
                                f"ungrounded plot data literal '{seg}'."
                            )
    return errors, checked


def verify_numeric_fidelity(
    *,
    source_texts: list[str],
    tex_files: dict[str, str],
    plot_scripts: list[Path] | None = None,
) -> GateResult:
    """Run Gate 1 across LaTeX files and optional Matplotlib scripts against source logs."""
    pool = extract_source_number_pool(*source_texts)
    errors: list[str] = []
    warnings: list[str] = []
    total_checked = 0

    if not pool.raw_values:
        warnings.append("Source number pool is empty; verify experimental_log.md is populated.")

    for label, tex_content in tex_files.items():
        errs, cnt = _check_latex_tables_and_prose(tex_content, label, pool)
        errors.extend(errs)
        total_checked += cnt

    for script in plot_scripts or []:
        errs, cnt = _check_plot_script_ast(script, pool)
        errors.extend(errs)
        total_checked += cnt

    return GateResult(
        gate="numeric_fidelity",
        passed=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
        metrics={
            "source_numbers_indexed": len(pool.raw_values),
            "target_numbers_checked": total_checked,
        },
    )
