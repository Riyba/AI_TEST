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


def run_command(root: Path, command: str) -> tuple[bool, str]:
    argv = _parse(command, ALLOWED_EXECUTABLES)
    if isinstance(argv, str):
        return False, argv
    return _run(root, argv)


def detect_test_command(root: Path) -> str | None:
    if (root / "package.json").exists():
        return "npm test"
    if any((root / f).exists() for f in ("pytest.ini", "pyproject.toml", "setup.py", "tests", "conftest.py")):
        return "pytest -q"
    return None


def run_tests(root: Path, command: str = "") -> tuple[bool, str]:
    command = command.strip() or detect_test_command(root) or ""
    if not command:
        return False, "could not detect a test runner; pass an explicit command"
    argv = _parse(command, TEST_RUNNERS)
    if isinstance(argv, str):
        return False, argv
    return _run(root, argv)
