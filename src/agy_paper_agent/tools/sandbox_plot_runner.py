"""Sandboxed pure code-vector visual runner for Matplotlib (.py) and TikZ (.tex) (D-05).

Security & Rigor Guarantees:
- AST pre-audit blocks network/process/shell imports and `eval`/`exec`/`__import__`.
- Executes Matplotlib scripts in an isolated child Python process with API secrets scrubbed.
- Compiles TikZ/PGFPlots with `-no-shell-escape` and rasterizes vector PDF to 300-DPI PNG
  via `pdftoppm` or MiKTeX Ghostscript (`mgs`) for downstream VLM layout inspection.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "subprocess",
        "socket",
        "urllib",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
        "telnetlib",
        "webbrowser",
        "ctypes",
        "multiprocessing",
        "winreg",
        "shutil",
    }
)
FORBIDDEN_CALL_NAMES = frozenset({"eval", "exec", "compile", "__import__", "breakpoint", "input"})
SENSITIVE_ENV_PATTERNS = ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")


@dataclass(frozen=True)
class VisualBuildResult:
    succeeded: bool
    pdf_path: Path | None
    png_path: Path | None
    errors: list[str]


def audit_plot_script_ast(script_source: str, filename: str = "<plot_script>") -> list[str]:
    """Static AST security check forbidding network, shell, and dynamic code execution."""
    try:
        tree = ast.parse(script_source, filename=filename)
    except SyntaxError as exc:
        return [f"SyntaxError at line {exc.lineno}: {exc.msg}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append(f"Line {node.lineno}: forbidden import '{alias.name}'.")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                violations.append(f"Line {node.lineno}: forbidden import from '{node.module}'.")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALL_NAMES:
                violations.append(f"Line {node.lineno}: forbidden builtin call '{node.func.id}()'.")
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen"}:
                violations.append(
                    f"Line {node.lineno}: forbidden OS shell call '.{node.func.attr}()'."
                )
    return violations


def _scrubbed_child_env() -> dict[str, str]:
    """Return environment with API keys/tokens removed and headless Agg backend enforced."""
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        upper = k.upper()
        if any(pat in upper for pat in SENSITIVE_ENV_PATTERNS):
            continue
        if upper in {"TEXINPUTS", "TEXMFHOME", "TEXMF", "TEXMFVAR", "TEXMFCONFIG"}:
            continue
        env[k] = v
    env["MPLBACKEND"] = "Agg"
    env["PYTHONUTF8"] = "1"
    return env


def rasterize_pdf_to_png(
    pdf_path: Path, png_path: Path, dpi: int = 300, timeout_sec: int = 30
) -> list[str]:
    """Convert single-page vector PDF to PNG using `pdftoppm` or MiKTeX `mgs`."""
    png_path.parent.mkdir(parents=True, exist_ok=True)
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        prefix = str(png_path.with_suffix(""))
        proc = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), "-singlefile", str(pdf_path), prefix],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode == 0 and png_path.is_file():
            return []
        return [f"pdftoppm failed ({proc.returncode}): {proc.stderr.strip()}"]

    gs_bin = shutil.which("mgs") or shutil.which("gs")
    if gs_bin:
        proc = subprocess.run(
            [
                gs_bin,
                "-dSAFER",
                "-dBATCH",
                "-dNOPAUSE",
                "-sDEVICE=png16m",
                f"-r{dpi}",
                f"-sOutputFile={png_path}",
                str(pdf_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode == 0 and png_path.is_file():
            return []
        return [f"Ghostscript failed ({proc.returncode}): {proc.stderr.strip()}"]

    return ["Neither 'pdftoppm' nor Ghostscript ('mgs'/'gs') is available on PATH."]


def run_matplotlib_script(
    *,
    script_path: Path,
    output_pdf: Path,
    output_png: Path | None = None,
    dpi: int = 300,
    timeout_sec: int = 45,
    python_executable: str | None = None,
) -> VisualBuildResult:
    """Audit and run a Matplotlib script in an isolated subprocess, saving vector PDF + PNG."""
    if not script_path.is_file():
        return VisualBuildResult(False, None, None, [f"Plot script not found: '{script_path}'."])

    source = script_path.read_text(encoding="utf-8")
    ast_errors = audit_plot_script_ast(source, filename=script_path.name)
    if ast_errors:
        return VisualBuildResult(False, None, None, ast_errors)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    target_png = output_png or output_pdf.with_suffix(".png")
    target_png.parent.mkdir(parents=True, exist_ok=True)

    py_exe = python_executable or sys.executable
    env = _scrubbed_child_env()
    env["AGY_OUTPUT_PDF"] = str(output_pdf.resolve())
    env["AGY_OUTPUT_PNG"] = str(target_png.resolve())

    # Runner executes the user script and auto-saves active figure if script didn't save directly
    harness = (
        "import os, runpy, matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        f"runpy.run_path({str(script_path.resolve())!r}, run_name='__main__')\n"
        "pdf_out = os.environ['AGY_OUTPUT_PDF']\n"
        "png_out = os.environ['AGY_OUTPUT_PNG']\n"
        "if plt.get_fignums():\n"
        "    if not os.path.exists(pdf_out):\n"
        "        plt.savefig(pdf_out, format='pdf', bbox_inches='tight')\n"
        "    if not os.path.exists(png_out):\n"
        f"        plt.savefig(png_out, format='png', dpi={dpi}, bbox_inches='tight')\n"
        "    plt.close('all')\n"
    )

    with tempfile.TemporaryDirectory(prefix="agy_plot_sbx_") as tmp_dir:
        try:
            proc = subprocess.run(
                [py_exe, "-c", harness],
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return VisualBuildResult(
                False, None, None, [f"Plot script timed out after {timeout_sec}s."]
            )

        if proc.returncode != 0:
            return VisualBuildResult(
                False,
                None,
                None,
                [f"Plot script exited with code {proc.returncode}: {proc.stderr.strip()}"],
            )

    if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
        return VisualBuildResult(
            False, None, None, ["Plot script did not produce a non-empty PDF."]
        )

    if not target_png.is_file() or target_png.stat().st_size == 0:
        rast_errs = rasterize_pdf_to_png(output_pdf, target_png, dpi=dpi)
        if rast_errs:
            return VisualBuildResult(False, output_pdf, None, rast_errs)

    return VisualBuildResult(True, output_pdf, target_png, [])


def compile_tikz_diagram(
    *,
    tikz_tex_path: Path,
    output_pdf: Path,
    output_png: Path | None = None,
    dpi: int = 300,
    timeout_sec: int = 60,
) -> VisualBuildResult:
    """Compile a TikZ/PGFPlots source file with `-no-shell-escape` to vector PDF + 300-DPI PNG."""
    if not tikz_tex_path.is_file():
        return VisualBuildResult(False, None, None, [f"TikZ file not found: '{tikz_tex_path}'."])

    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        return VisualBuildResult(False, None, None, ["'pdflatex' is not available on PATH."])

    raw_tex = tikz_tex_path.read_text(encoding="utf-8")
    if r"\documentclass" not in raw_tex:
        full_tex = (
            "\\documentclass[tikz,border=4pt]{standalone}\n"
            "\\usepackage{amsmath,amssymb}\n"
            "\\usetikzlibrary{arrows.meta,positioning,shapes.geometric,calc,fit}\n"
            "\\begin{document}\n"
            f"{raw_tex}\n"
            "\\end{document}\n"
        )
    else:
        full_tex = raw_tex

    target_png = output_png or output_pdf.with_suffix(".png")
    env = _scrubbed_child_env()

    with tempfile.TemporaryDirectory(prefix="agy_tikz_sbx_") as tmp_str:
        work = Path(tmp_str)
        (work / "diagram.tex").write_text(full_tex, encoding="utf-8")
        try:
            proc = subprocess.run(
                [
                    pdflatex,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    "diagram.tex",
                ],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return VisualBuildResult(
                False, None, None, [f"TikZ build timed out after {timeout_sec}s."]
            )

        built_pdf = work / "diagram.pdf"
        if proc.returncode != 0 or not built_pdf.is_file():
            tail = "\n".join(proc.stdout.splitlines()[-15:])
            return VisualBuildResult(
                False,
                None,
                None,
                [f"TikZ compilation failed (code {proc.returncode}): {tail}"],
            )

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_pdf, output_pdf)

    rast_errs = rasterize_pdf_to_png(output_pdf, target_png, dpi=dpi)
    if rast_errs:
        return VisualBuildResult(False, output_pdf, None, rast_errs)

    return VisualBuildResult(True, output_pdf, target_png, [])
