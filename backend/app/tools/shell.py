"""Controlled command execution: executable allowlist + working-dir jail.

Commands are parsed with shlex and executed WITHOUT a shell, so pipes,
redirects, substitution, and chaining are structurally impossible.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

COMMAND_TIMEOUT = 300
MAX_OUTPUT = 200_000

ALLOWED_EXECUTABLES = {
    "git", "ls", "cat", "grep", "find", "wc", "head", "tail",
    "pytest", "python", "python3", "pip",
    "npm", "npx", "yarn", "pnpm", "node",
    "ruff", "flake8", "mypy", "black", "eslint", "tsc", "prettier",
    "make", "go", "cargo", "uv",
}

TEST_RUNNERS = {"pytest", "python", "python3", "npm", "npx", "yarn", "pnpm", "go", "cargo", "make", "uv"}

_SHELL_META = set(";|&<>`$\\")


def _run(root: Path, argv: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except FileNotFoundError:
        return False, f"executable not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return False, f"command timed out after {COMMAND_TIMEOUT}s"
    output = (proc.stdout + proc.stderr)[:MAX_OUTPUT]
    header = f"[exit code {proc.returncode}]\n"
    return proc.returncode == 0, header + (output.strip() or "(no output)")


def _parse(command: str, allowed: set[str]) -> list[str] | str:
    """Returns argv on success, or an error message string."""
    if not command.strip():
        return "empty command"
    if any(c in _SHELL_META for c in command):
        return "shell operators (| ; & > < ` $ \\) are not allowed"
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"could not parse command: {exc}"
    executable = Path(argv[0]).name
    if executable != argv[0]:
        return "executable must be a bare name (no paths)"
    if executable not in allowed:
        return f"'{executable}' is not in the allowlist ({', '.join(sorted(allowed))})"
    return argv


def run_command(root: Path, command: str) -> tuple[bool, str] | tuple[bool, str, bool]:
    argv = _parse(command, ALLOWED_EXECUTABLES)
    if isinstance(argv, str):
        # A structurally rejected command (not allowlisted, shell operators,
        # unparseable) is malformed input — it fails identically every retry.
        return False, argv, False
    return _run(root, argv)


# Detection descends at most this many levels below the repo root so a runner
# living in a subdirectory (backend/, frontend/, packages/x/) is still found.
_DETECT_MAX_DEPTH = 3

# Directories that never hold the project's own tests and are expensive or
# misleading to descend into (vendored deps, caches, VCS metadata).
_DETECT_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next", "target",
}

_NPM_MARKERS = ("package.json",)
_PYTEST_MARKERS = ("pytest.ini", "pyproject.toml", "setup.py", "tests", "conftest.py")


def _command_for_dir(directory: Path, rel: str) -> str | None:
    """Test command for markers in `directory`, or None. `rel` is the path
    relative to the repo root ("" for the root itself); a non-empty `rel` is
    threaded into the command so it runs against that subdirectory."""
    if any((directory / f).exists() for f in _NPM_MARKERS):
        return "npm test" if not rel else f"npm --prefix {rel} test"
    if any((directory / f).exists() for f in _PYTEST_MARKERS):
        return "pytest -q" if not rel else f"pytest -q {rel}"
    return None


def _iter_dirs(root: Path):
    """Yield (directory, rel) breadth-first from `root` down to
    _DETECT_MAX_DEPTH, root first, children sorted for deterministic results."""
    queue: list[tuple[Path, str, int]] = [(root, "", 0)]
    while queue:
        directory, rel, depth = queue.pop(0)
        yield directory, rel
        if depth >= _DETECT_MAX_DEPTH:
            continue
        try:
            children = sorted(
                p for p in directory.iterdir()
                if p.is_dir()
                and p.name not in _DETECT_SKIP_DIRS
                and not p.name.startswith(".")
            )
        except OSError:
            children = []
        for child in children:
            child_rel = f"{rel}/{child.name}" if rel else child.name
            queue.append((child, child_rel, depth + 1))


def detect_test_command(root: Path) -> str | None:
    """Find a runnable test command, checking the root first and then
    descending into subdirectories. The shallowest match wins."""
    for directory, rel in _iter_dirs(root):
        command = _command_for_dir(directory, rel)
        if command:
            return command
    return None


def run_tests(root: Path, command: str = "") -> tuple[bool, str] | tuple[bool, str, bool]:
    command = command.strip() or detect_test_command(root) or ""
    if not command:
        # No detectable runner and none supplied — a setup gap, not a flake.
        return False, "could not detect a test runner; pass an explicit command", False
    argv = _parse(command, TEST_RUNNERS)
    if isinstance(argv, str):
        return False, argv, False
    return _run(root, argv)
