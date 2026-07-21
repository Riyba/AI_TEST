"""Git tools (shelling out to git, cwd-jailed).

Read-only (status/diff/log) plus a small set of mutating operations needed to
deliver a branch: create_branch, commit, push. All argv is built from fixed
flags and caller-supplied strings passed straight to subprocess (no shell),
so there is no command-injection surface — the risk with these is scope
(what they change), not injection, which is why each is registered
`mutating=True` in tools/registry.py.
"""

from __future__ import annotations

import re
import subprocess
import uuid
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


def current_branch(root: Path) -> tuple[bool, str]:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD")


def remote_url(root: Path, remote: str = "origin") -> tuple[bool, str]:
    return _git(root, "remote", "get-url", remote)


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "change"


def create_branch(root: Path, base: str = "dev", name: str = "") -> tuple[bool, str]:
    """Create and check out a new branch off ``base``, named from a slugified
    ``name`` plus a random suffix for uniqueness. The caller's ``name`` is
    never used as a raw git ref — it only ever contributes lowercase
    alphanumeric words, so a task description with arbitrary punctuation or
    whitespace can't produce an invalid or surprising ref."""
    base = (base or "dev").strip()
    branch = f"feature/{_slugify(name)}-{uuid.uuid4().hex[:6]}"

    fetch_ok, fetch_out = _git(root, "fetch", "origin", base)
    start_point = f"origin/{base}" if fetch_ok else base

    ok, out = _git(root, "checkout", "-b", branch, start_point)
    if not ok:
        detail = out if fetch_ok else f"{out}\n(fetch of origin/{base} also failed: {fetch_out})"
        return False, f"failed to create branch '{branch}' from '{start_point}': {detail}"
    return True, f"created and checked out branch '{branch}' from '{start_point}'"


def commit(root: Path, message: str = "") -> tuple[bool, str]:
    add_ok, add_out = _git(root, "add", "-A")
    if not add_ok:
        return False, f"git add failed: {add_out}"
    return _git(root, "commit", "-m", message.strip() or "Automated changes")


def push(root: Path, branch: str = "") -> tuple[bool, str]:
    branch = branch.strip()
    if not branch:
        ok, head = current_branch(root)
        if not ok:
            return False, f"could not determine current branch: {head}"
        branch = head
    return _git(root, "push", "-u", "origin", branch)
