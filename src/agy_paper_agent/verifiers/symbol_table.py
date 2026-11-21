"""Gate 4: Deterministic mathematical symbol table consistency verifier."""

from __future__ import annotations

import re

from agy_paper_agent.contracts import GateResult, SymbolEntry, SymbolTable
from agy_paper_agent.verifiers.numeric_fidelity import strip_latex_comments

MATH_SPAN_RE = re.compile(
    r"\$\$(.*?)\$\$"
    r"|\\\[(.*?)\\\]"
    r"|\\\((.*?)\\\)"
    r"|\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}(.*?)\\end\{\4\}"
    r"|(?<!\\)\$(?!\$)(.+?)(?<!\\)\$",
    re.DOTALL,
)
MACRO_DEF_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareMathOperator)\*?\s*\{\s*(\\[A-Za-z]+)\s*\}"
)
CUSTOM_STRUCT_SYMBOL_RE = re.compile(
    r"\\(?:mathcal|mathbf|mathbb|mathsf|mathfrak|boldsymbol)\{[A-Za-z0-9_]+\}"
    r"(?:_(?:\{[^\}]+\}|[A-Za-z0-9]))?"
)
PROSE_DOMAIN_CLAIM_RE = re.compile(r"\$([^\$]+?)\\in\s*([^\$,.;]+)\$")
STANDARD_MATH_SETS = frozenset(
    {
        r"\mathbb{R}",
        r"\mathbb{N}",
        r"\mathbb{Z}",
        r"\mathbb{C}",
        r"\mathbb{Q}",
        r"\mathbb{E}",
        r"\mathbb{P}",
        r"\mathbb{I}",
        r"\mathcal{O}",
        r"\mathcal{N}",
        r"\mathcal{L}",
    }
)


def _extract_math_segments(tex: str) -> list[str]:
    clean = strip_latex_comments(tex)
    segments: list[str] = []
    for m in MATH_SPAN_RE.finditer(clean):
        seg = m.group(1) or m.group(2) or m.group(3) or m.group(5) or m.group(6)
        if seg:
            segments.append(seg)
    return segments


def _token_present_in_math(token: str, math_segments: list[str]) -> bool:
    escaped = re.escape(token)
    if token.startswith("\\") or token[-1].isalnum():
        pat = re.compile(escaped + r"(?![A-Za-z])")
    else:
        pat = re.compile(escaped)
    return any(pat.search(seg) for seg in math_segments)


def _normalize_space_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr).strip()


def verify_symbol_consistency(
    *,
    symbol_table: SymbolTable,
    ordered_sections: list[tuple[str, str]],
    allow_intro_preview: bool = False,
) -> GateResult:
    """Run Gate 4 across ordered `(section_id, tex_content)` pairs against SymbolTable."""
    errors: list[str] = []
    warnings: list[str] = []

    token_to_entry: dict[str, SymbolEntry] = {}
    for entry in symbol_table.entries:
        for tok in (entry.symbol, *entry.aliases):
            token_to_entry[tok] = entry

    section_order: dict[str, int] = {
        sec_id: idx for idx, (sec_id, _) in enumerate(ordered_sections)
    }
    exempt_preview = (
        {"sec_abstract", "abstract", "sec_intro", "introduction"} if allow_intro_preview else set()
    )

    # Check that every declared defined_in_section exists when full section order is supplied
    for entry in symbol_table.entries:
        if ordered_sections and entry.defined_in_section not in section_order:
            warnings.append(
                f"Symbol '{entry.symbol}' declares "
                f"defined_in_section='{entry.defined_in_section}', "
                "which is not in ordered_sections."
            )

    unregistered_counts: dict[str, int] = {}

    for sec_idx, (sec_id, raw_tex) in enumerate(ordered_sections):
        clean_tex = strip_latex_comments(raw_tex)
        math_segs = _extract_math_segments(clean_tex)

        # 1. Macro redefinition collisions outside defining section
        for mm in MACRO_DEF_RE.finditer(clean_tex):
            macro_tok = mm.group(1)
            if macro_tok in token_to_entry:
                owner = token_to_entry[macro_tok]
                if sec_id != owner.defined_in_section:
                    errors.append(
                        f"[{sec_id}] Macro '{macro_tok}' redefined outside its defining section "
                        f"'{owner.defined_in_section}'."
                    )

        # 2. Use-before-definition across ordered sections
        for tok, entry in token_to_entry.items():
            if entry.defined_in_section in section_order:
                def_idx = section_order[entry.defined_in_section]
                if sec_idx < def_idx and sec_id.lower() not in exempt_preview:
                    if _token_present_in_math(tok, math_segs):
                        errors.append(
                            f"[{sec_id}] Symbol '{tok}' is used before its defining section "
                            f"'{entry.defined_in_section}'."
                        )

        # 3. Conflicting domain/shape membership statements ($X \in ...$)
        for dm in PROSE_DOMAIN_CLAIM_RE.finditer(clean_tex):
            lhs = dm.group(1).strip()
            rhs = _normalize_space_expr(dm.group(2))
            if lhs in token_to_entry:
                entry = token_to_entry[lhs]
                expected = _normalize_space_expr(entry.domain_or_shape)
                # Flag if both sides specify explicit spaces (e.g., \mathbb{R}^{...}) that disagree
                if (
                    expected.startswith(r"\mathbb{")
                    and rhs.startswith(r"\mathbb{")
                    and rhs != expected
                ):
                    errors.append(
                        f"[{sec_id}] Domain conflict for '{lhs}': text states '{rhs}', "
                        f"but symbol_table specifies '{expected}'."
                    )

        # 4. Track unregistered structural math tokens (\mathcal{...}, \mathbf{...}, etc.)
        for seg in math_segs:
            for cm in CUSTOM_STRUCT_SYMBOL_RE.finditer(seg):
                sym = cm.group(0)
                if sym not in token_to_entry and sym not in STANDARD_MATH_SETS:
                    unregistered_counts[sym] = unregistered_counts.get(sym, 0) + 1

    for sym, cnt in sorted(unregistered_counts.items()):
        if cnt >= 2:
            warnings.append(
                f"Unregistered structural symbol '{sym}' appears {cnt} times; "
                "consider adding it to symbol_table.json."
            )

    return GateResult(
        gate="symbol_table",
        passed=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
        metrics={
            "registered_symbols": len(symbol_table.entries),
            "sections_audited": len(ordered_sections),
            "unregistered_recurring_symbols": sum(
                1 for c in unregistered_counts.values() if c >= 2
            ),
        },
    )
