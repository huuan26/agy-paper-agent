"""Cross-platform AGY hook bootstrapper with graceful fail-open fallback.

Resolves `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python` (POSIX) relative
to the plugin root so AGY lifecycle hooks (`cmd /c` or `sh -c`) always run inside the
plugin's isolated virtual environment without requiring global package installation.
If `.venv` has not been created yet, fails open with a valid JSON response (exit 0).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _fail_open_response(raw_stdin: str) -> str:
    try:
        payload = json.loads(raw_stdin) if raw_stdin.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    event = payload.get("hookEventName", "")
    if event in {"PreToolUse", "Stop"}:
        return json.dumps({"decision": "allow"}) + "\n"
    return "{}\n"


def _resolve_venv_python(plugin_root: Path) -> Path | None:
    for candidate in (
        plugin_root / ".venv" / "Scripts" / "python.exe",
        plugin_root / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return candidate
    return None


def main() -> int:
    raw_in = sys.stdin.read()
    override_root = os.environ.get("AGY_HOOK_PLUGIN_ROOT")
    plugin_root = (
        Path(override_root).resolve() if override_root else Path(__file__).resolve().parents[1]
    )
    venv_py = _resolve_venv_python(plugin_root)
    if venv_py is None:
        sys.stdout.write(_fail_open_response(raw_in))
        sys.stdout.flush()
        return 0

    proc = subprocess.run(
        [str(venv_py), "-m", "agy_paper_agent.hooks_entry"],
        cwd=plugin_root,
        input=raw_in,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        sys.stdout.write(proc.stdout)
    else:
        sys.stdout.write(_fail_open_response(raw_in))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
