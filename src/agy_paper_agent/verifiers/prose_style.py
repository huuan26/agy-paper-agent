"""LaTeX-aware AI-writing and academic prose auditor powered by `avoid-ai-writing`."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

COMMENT_RE = re.compile(r"(?<!\\)%[^\n]*")
STRIP_ENVS = (
    "table",
    "table*",
    "tabular",
    "tabular*",
    "tabularx",
    "nicematrix",
    "figure",
    "figure*",
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "tikzpicture",
    "thebibliography",
)
STRIP_ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(re.escape(e) for e in STRIP_ENVS) + r")\}.*?\\end\{\1\}",
    re.DOTALL,
)
PREAMBLE_LINE_RE = re.compile(
    r"^\s*\\(?:documentclass|usepackage|newtheorem|crefname|Crefname|emergencystretch|"
    r"bibliographystyle|bibliography|input|include|maketitle|clearpage|appendix|date|author)\b[^\n]*$",
    re.MULTILINE,
)
SELF_LABEL_RE = re.compile(
    r"(?:^|[.;]\s+)\b(crucially|importantly|notably|remarkably|interestingly|excitingly),",
    re.IGNORECASE | re.MULTILINE,
)
PARTICIPIAL_CLAUSE_RE = re.compile(r",\s+(?:[a-z]+ly\s+)?([a-z]{3,}ing)\b")
BENIGN_ING_WORDS = frozenset(
    {
        "including",
        "excluding",
        "following",
        "according",
        "assuming",
        "using",
        "during",
        "concerning",
        "regarding",
        "pending",
        "notwithstanding",
        "depending",
        "comparing",
        "spanning",
        "starting",
        "beginning",
        "ending",
        "holding",
        "trading",
        "funding",
        "borrowing",
        "hedging",
        "lending",
        "clearing",
        "matching",
        "rebalancing",
    }
)
FALLBACK_CRITICAL_RE = re.compile(
    r"\b(?:as of my last (?:knowledge )?update|i hope this helps|great question!|"
    r"certainly!\s+here is|insert placeholder here|\[todo:?\s*[^\]]*\])\b",
    re.IGNORECASE,
)
FALLBACK_TIER1_RE = re.compile(
    r"\b(?:delve|delves|delving|tapestry|testament to|watershed moment|"
    r"game-changer|game-changing|ever-evolving|nestled|bustling|unleash|unleashing|"
    r"thought leader|thought leadership|in the rapidly evolving)\b",
    re.IGNORECASE,
)
UNICODE_OR_LATEX_EMDASH_RE = re.compile(r"(?:\u2014|\u2013|---)")


@dataclass(frozen=True)
class ProseIssue:
    file: str
    severity: str
    issue_type: str
    source: str
    snippet: str


@dataclass(frozen=True)
class FileProseAudit:
    file: str
    word_count: int
    score: int
    label: str
    issues: list[ProseIssue] = field(default_factory=list)


@dataclass(frozen=True)
class ProseAuditReport:
    passed: bool
    engine_mode: str
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    files: list[FileProseAudit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_latex_prose(tex: str) -> str:
    """Convert a LaTeX manuscript file into clean Markdown prose for `avoid-ai-writing`."""
    s = COMMENT_RE.sub("", tex)
    s = STRIP_ENV_RE.sub("\n\n", s)
    s = re.sub(r"\\title\{([^\}]*)\}", r"\n# \1\n", s)
    s = PREAMBLE_LINE_RE.sub("", s)
    s = re.sub(r"\\\[.*?\\\]", " `math` ", s, flags=re.DOTALL)
    s = re.sub(r"\$\$.*?\$\$", " `math` ", s, flags=re.DOTALL)
    s = re.sub(r"\\\(.*?\\\)", "`x`", s, flags=re.DOTALL)
    s = re.sub(r"(?<!\\)\$[^\$]+(?<!\\)\$", "`x`", s)
    s = s.replace("---", "\u2014")
    s = re.sub(r"(?<=\s)--(?=\s)", "\u2014", s)
    s = re.sub(r"(?<=\d)--(?=\d)", "-", s)
    s = re.sub(r"\\citet(?:\[[^\]]*\])*\{[^\}]*\}", "Author (2020)", s)
    s = re.sub(r"\\(?:citep?|nocite)(?:\[[^\]]*\])*\{[^\}]*\}", "", s)
    s = re.sub(r"\\(?:Cref|cref|ref|eqref)\{[^\}]*\}", "Section 1", s)
    s = re.sub(r"\\label\{[^\}]*\}", "", s)
    s = re.sub(r"\\section\*?\{([^\}]*)\}", r"\n## \1\n", s)
    s = re.sub(r"\\subsection\*?\{([^\}]*)\}", r"\n### \1\n", s)
    s = re.sub(r"\\(?:subsubsection|paragraph)\*?\{([^\}]*)\}", r"\n#### \1\n", s)
    s = re.sub(r"\\texttt\{([^\}]*)\}", r"`\1`", s)
    s = re.sub(r"\\textbf\{([^\}]*)\}", r"**\1**", s)
    s = re.sub(r"\\(?:emph|textit|textrm|textsc)\{([^\}]*)\}", r"\1", s)
    s = re.sub(
        r"\\(?:begin|end)\{(?:document|abstract|enumerate|itemize|theorem|proposition|lemma|corollary|proof)\}"
        r"(?:\[[^\]]*\])?",
        "\n",
        s,
    )
    s = re.sub(r"\\item\b", "\n\n- ", s)
    s = re.sub(r"\\qed\b", "", s)
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("~", " ")
    s = re.sub(r"\\\s+", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip() + "\n"


def _locate_node_executable() -> str | None:
    env_node = os.environ.get("AVOID_AI_WRITING_NODE")
    if env_node and Path(env_node).is_file():
        return env_node
    which_node = shutil.which("node")
    if which_node:
        return which_node
    home = Path.home()
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe",
        home / ".cache" / "pyright-python" / "nodeenv" / "Scripts" / "node.exe",
        home
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def _locate_detector_js() -> Path | None:
    env_dir = os.environ.get("AVOID_AI_WRITING_DIR")
    repo_root = Path(__file__).resolve().parents[3]
    candidates = [
        Path(env_dir) / "detector" / "patterns.js" if env_dir else None,
        repo_root.parent / "avoid-ai-writing" / "detector" / "patterns.js",
        Path.home() / "Documents" / "avoid-ai-writing" / "detector" / "patterns.js",
    ]
    for cand in candidates:
        if cand is not None and cand.is_file():
            return cand
    return None


def _scan_academic_rules(
    file_label: str,
    raw_tex: str,
    prose: str,
    *,
    max_sentence_words: int,
    include_fallback_vocab: bool,
) -> list[ProseIssue]:
    issues: list[ProseIssue] = []
    clean_tex = COMMENT_RE.sub("", raw_tex)
    for m_dash in UNICODE_OR_LATEX_EMDASH_RE.finditer(clean_tex):
        issues.append(
            ProseIssue(
                file=file_label,
                severity="medium",
                issue_type="non_ascii_or_em_dash",
                source="academic-latex",
                snippet=m_dash.group(0),
            )
        )

    for m_adv in SELF_LABEL_RE.finditer(prose):
        issues.append(
            ProseIssue(
                file=file_label,
                severity="medium",
                issue_type="self_labeling_adverbial",
                source="academic-latex",
                snippet=f"{m_adv.group(1)},",
            )
        )

    for para in prose.split("\n\n"):
        stripped = para.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z`\"\(])", stripped.replace("\n", " "))
        for sent in sentences:
            words = sent.split()
            if len(words) > max_sentence_words:
                preview = " ".join(words[:14]) + f" ... ({len(words)} words)"
                issues.append(
                    ProseIssue(
                        file=file_label,
                        severity="medium",
                        issue_type="overlong_sentence",
                        source="academic-latex",
                        snippet=preview,
                    )
                )
            ing_hits = [
                w for w in PARTICIPIAL_CLAUSE_RE.findall(sent) if w.lower() not in BENIGN_ING_WORDS
            ]
            if len(ing_hits) >= 2:
                issues.append(
                    ProseIssue(
                        file=file_label,
                        severity="medium",
                        issue_type="participial_tail_stack",
                        source="academic-latex",
                        snippet=", ".join(ing_hits),
                    )
                )

    if include_fallback_vocab:
        for m_crit in FALLBACK_CRITICAL_RE.finditer(prose):
            issues.append(
                ProseIssue(
                    file=file_label,
                    severity="critical",
                    issue_type="chatbot_or_placeholder",
                    source="academic-latex",
                    snippet=m_crit.group(0),
                )
            )
        for m_t1 in FALLBACK_TIER1_RE.finditer(prose):
            issues.append(
                ProseIssue(
                    file=file_label,
                    severity="high",
                    issue_type="tier1",
                    source="academic-latex",
                    snippet=m_t1.group(0),
                )
            )
    return issues


def audit_manuscript_prose(
    tex_files: dict[str, str],
    *,
    max_issues_per_file: int | None = None,
    max_sentence_words: int = 85,
    detector_js: Path | None = None,
    node_exe: str | None = None,
) -> ProseAuditReport:
    """Audit LaTeX manuscript files using `avoid-ai-writing` + academic LaTeX rules."""
    prose_map = {name: extract_latex_prose(tex) for name, tex in tex_files.items()}
    resolved_node = node_exe or _locate_node_executable()
    resolved_det = detector_js or _locate_detector_js()
    node_results: dict[str, dict[str, Any]] = {}
    engine_mode = "python_fallback"

    if resolved_node and resolved_det and resolved_det.is_file():
        runner = (
            "const fs=require('fs');const D=require(process.argv[2]);"
            "const m=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));const out={};"
            "for(const [k,v] of Object.entries(m)){"
            "out[k]=D.analyzeText(v,{contextMode:'technical',sourceMode:'rendered-markdown'});}"
            "process.stdout.write(JSON.stringify(out));"
        )
        with tempfile.TemporaryDirectory(prefix="agy_prose_") as tmp:
            runner_path = Path(tmp) / "runner.js"
            in_json = Path(tmp) / "prose.json"
            runner_path.write_text(runner, encoding="utf-8")
            in_json.write_text(json.dumps(prose_map), encoding="utf-8")
            proc = subprocess.run(
                [resolved_node, str(runner_path), str(resolved_det), str(in_json)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                node_results = json.loads(proc.stdout)
                engine_mode = "node_detector"

    file_audits: list[FileProseAudit] = []
    for name, raw_tex in tex_files.items():
        prose = prose_map[name]
        issues: list[ProseIssue] = []
        word_count = len(prose.split())
        score = 0
        label = "Fallback scan"

        if name in node_results:
            nr = node_results[name]
            word_count = int((nr.get("stats") or {}).get("wordCount") or word_count)
            score = int(nr.get("score") or 0)
            label = str(nr.get("label") or "Clean")
            for raw_iss in nr.get("issues") or []:
                sev = str(raw_iss.get("severity") or "medium")
                if sev == "low":
                    continue
                snippet = str(
                    raw_iss.get("text") or raw_iss.get("detail") or raw_iss.get("type") or ""
                )
                issues.append(
                    ProseIssue(
                        file=name,
                        severity=sev,
                        issue_type=str(raw_iss.get("type") or "unknown"),
                        source="avoid-ai-writing",
                        snippet=snippet,
                    )
                )

        issues.extend(
            _scan_academic_rules(
                name,
                raw_tex,
                prose,
                max_sentence_words=max_sentence_words,
                include_fallback_vocab=(engine_mode == "python_fallback"),
            )
        )
        file_audits.append(
            FileProseAudit(
                file=name,
                word_count=word_count,
                score=score,
                label=label,
                issues=issues,
            )
        )

    all_issues = [iss for fa in file_audits for iss in fa.issues]
    crit = sum(1 for i in all_issues if i.severity == "critical")
    high = sum(1 for i in all_issues if i.severity == "high")
    med = sum(1 for i in all_issues if i.severity == "medium")

    passed = crit == 0
    if max_issues_per_file is not None:
        passed = passed and all(len(fa.issues) <= max_issues_per_file for fa in file_audits)

    return ProseAuditReport(
        passed=passed,
        engine_mode=engine_mode,
        total_issues=len(all_issues),
        critical_issues=crit,
        high_issues=high,
        medium_issues=med,
        files=file_audits,
    )
