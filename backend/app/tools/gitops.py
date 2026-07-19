"""Read-only git tools (shelling out to git, cwd-jailed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_TIMEOUT = 60
MAX_OUTPUT = 200_000


def _git(root: Path, *args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "git is not installed"
    except subprocess.TimeoutExpired:
        return False, "git command timed out"
    output = (proc.stdout + proc.stderr)[:MAX_OUTPUT]
    return proc.returncode == 0, output.strip() or "(no output)"


def status(root: Path) -> tuple[bool, str]:
    return _git(root, "status", "--short", "--branch")


def diff(root: Path, rev_range: str = "") -> tuple[bool, str]:
    if rev_range:
        # A rev range is not a path; reject anything that looks like an option.
        if rev_range.startswith("-"):
            return False, "invalid revision range"
        return _git(root, "diff", rev_range)
    ok, out = _git(root, "diff", "HEAD")
    if ok and out != "(no output)":
        return ok, out
    # No commits yet or empty diff vs HEAD — fall back to working tree diff.
    return _git(root, "diff")


def log(root: Path, count: int = 10) -> tuple[bool, str]:
    count = max(1, min(count, 100))
    return _git(root, "log", f"-{count}", "--oneline", "--decorate")
