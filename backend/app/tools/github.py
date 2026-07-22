"""GitHub REST API integration: opens pull requests.

Gated behind a GITHUB_TOKEN setting (app/config.py) — the token is read
server-side and never exposed to the model or the tool's params. Owner/repo
is inferred from the repo's `origin` remote so no separate repo-slug config
is needed; the head branch defaults to whatever is currently checked out.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from . import gitops

TIMEOUT_SECONDS = 20.0

# Matches both SSH (git@github.com:owner/repo.git) and HTTPS
# (https://github.com/owner/repo.git) origin URLs.
_REMOTE_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def _parse_owner_repo(remote: str) -> tuple[str, str] | None:
    match = _REMOTE_RE.search(remote.strip())
    if not match:
        return None
    return match.group("owner"), match.group("repo")


def _open_pr(
    owner: str, repo: str, token: str, payload: dict[str, str]
) -> tuple[bool, str]:
    """The actual network call, isolated so tests can monkeypatch it without
    mocking httpx internals (same seam as datadog.py's _post_series)."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
    except httpx.HTTPError as exc:
        return False, f"GitHub request failed: {exc}"

    if response.is_success:
        data = response.json()
        return True, f"opened PR #{data.get('number')}: {data.get('html_url')}"
    return False, f"GitHub rejected PR creation: HTTP {response.status_code} {response.text[:500]}"


def create_pull_request(
    root: Path, params: dict[str, Any]
) -> tuple[bool, str] | tuple[bool, str, bool]:
    # Each early return below is a missing prerequisite/misconfiguration
    # (no token, no/foreign remote, no branch) — terminal, not worth retrying.
    token = get_settings().github_token
    if not token:
        return False, "GITHUB_TOKEN is not configured; set it in .env to enable PR creation", False

    ok, remote = gitops.remote_url(root)
    if not ok:
        return False, f"could not read git remote 'origin': {remote}", False
    parsed = _parse_owner_repo(remote)
    if parsed is None:
        return False, f"origin remote is not a github.com URL: {remote}", False
    owner, repo = parsed

    head = str(params.get("head") or "").strip()
    if not head:
        ok, head = gitops.current_branch(root)
        if not ok:
            return False, f"could not determine current branch: {head}", False

    base = str(params.get("base") or "dev").strip()
    title = str(params.get("title") or "").strip() or f"Merge {head} into {base}"
    body = str(params.get("body") or "")

    return _open_pr(
        owner, repo, token, {"title": title, "body": body, "head": head, "base": base}
    )
