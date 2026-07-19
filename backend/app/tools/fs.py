"""Filesystem tools, jailed to the run's repo path."""

from __future__ import annotations

import re
from pathlib import Path

MAX_READ_BYTES = 200_000
MAX_LIST = 500
MAX_SEARCH_RESULTS = 200
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"}


def resolve_jailed(root: Path, path: str) -> Path:
    """Resolve a (possibly hostile) path and ensure it stays inside root."""
    root = root.resolve()
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise PermissionError(f"path escapes the project directory: {path}")
    return resolved


def read_file(root: Path, path: str) -> tuple[bool, str]:
    target = resolve_jailed(root, path)
    if not target.is_file():
        return False, f"Not a file: {path}"
    data = target.read_bytes()[: MAX_READ_BYTES + 1]
    truncated = len(data) > MAX_READ_BYTES
    text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += "\n… [truncated]"
    return True, text


def write_file(root: Path, path: str, content: str) -> tuple[bool, str]:
    target = resolve_jailed(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return True, f"Wrote {len(content)} chars to {target.relative_to(root.resolve())}"


def _iter_files(base: Path):
    for entry in sorted(base.rglob("*")):
        if any(part in SKIP_DIRS for part in entry.parts):
            continue
        if entry.is_file():
            yield entry


def list_files(root: Path, path: str = ".") -> tuple[bool, str]:
    base = resolve_jailed(root, path)
    if not base.is_dir():
        return False, f"Not a directory: {path}"
    lines: list[str] = []
    for entry in _iter_files(base):
        lines.append(str(entry.relative_to(root.resolve())))
        if len(lines) >= MAX_LIST:
            lines.append("… [truncated]")
            break
    return True, "\n".join(lines) or "(empty)"


def search_files(root: Path, pattern: str, path: str = ".") -> tuple[bool, str]:
    if not pattern:
        return False, "Empty search pattern"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return False, f"Invalid regex: {exc}"
    base = resolve_jailed(root, path)
    results: list[str] = []
    for entry in _iter_files(base):
        try:
            text = entry.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = entry.relative_to(root.resolve())
                results.append(f"{rel}:{lineno}:{line.strip()[:200]}")
                if len(results) >= MAX_SEARCH_RESULTS:
                    results.append("… [truncated]")
                    return True, "\n".join(results)
    return True, "\n".join(results) or "(no matches)"
