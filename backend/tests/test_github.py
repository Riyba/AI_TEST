"""GitHub PR tool (tools/github.py). No network: `_open_pr` is monkeypatched
to capture the request, mirroring how test_datadog.py isolates `_post_series`.
The behaviour under test is owner/repo parsing from the origin remote, head/
title/body defaulting, and the disabled-when-unconfigured guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.tools import github


def _run(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(repo: Path) -> Path:
    _run(repo, "init", "-q", "-b", "feature/x")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "f.txt").write_text("x")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def with_origin(git_repo: Path):
    _run(git_repo, "remote", "add", "origin", "git@github.com:acme/widgets.git")
    return git_repo


@pytest.fixture
def token_configured(monkeypatch):
    monkeypatch.setattr(github, "get_settings", lambda: Settings(github_token="ghp_test"))


@pytest.fixture
def token_missing(monkeypatch):
    monkeypatch.setattr(github, "get_settings", lambda: Settings(github_token=None))


@pytest.fixture
def captured(monkeypatch):
    """Capture the (owner, repo, token, payload) passed to _open_pr; pretend
    GitHub accepted it."""
    calls: list[dict] = []

    def fake_open_pr(owner, repo, token, payload):
        calls.append({"owner": owner, "repo": repo, "token": token, "payload": payload})
        return True, f"opened PR #7: https://github.com/{owner}/{repo}/pull/7"

    monkeypatch.setattr(github, "_open_pr", fake_open_pr)
    return calls


# --------------------------------------------------------------------------- #
# GITHUB_TOKEN gate                                                          #
# --------------------------------------------------------------------------- #


def test_missing_token_returns_clear_error(with_origin: Path, token_missing) -> None:
    ok, msg, *_ = github.create_pull_request(with_origin, {})
    assert not ok
    assert "GITHUB_TOKEN" in msg


# --------------------------------------------------------------------------- #
# owner/repo parsing from the origin remote                                  #
# --------------------------------------------------------------------------- #


def test_ssh_remote_parsed(with_origin: Path, token_configured, captured) -> None:
    ok, _ = github.create_pull_request(with_origin, {"base": "dev"})
    assert ok
    assert captured[0]["owner"] == "acme"
    assert captured[0]["repo"] == "widgets"


def test_https_remote_parsed(git_repo: Path, token_configured, captured) -> None:
    _run(git_repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    ok, _ = github.create_pull_request(git_repo, {"base": "dev"})
    assert ok
    assert captured[0]["owner"] == "acme"
    assert captured[0]["repo"] == "widgets"


def test_missing_origin_fails_cleanly(git_repo: Path, token_configured, captured) -> None:
    ok, msg, *_ = github.create_pull_request(git_repo, {"base": "dev"})
    assert not ok
    assert "origin" in msg.lower()
    assert not captured


def test_non_github_remote_rejected(git_repo: Path, token_configured, captured) -> None:
    _run(git_repo, "remote", "add", "origin", "https://gitlab.com/acme/widgets.git")
    ok, msg, *_ = github.create_pull_request(git_repo, {"base": "dev"})
    assert not ok
    assert "github.com" in msg
    assert not captured


# --------------------------------------------------------------------------- #
# head / title / body defaulting                                            #
# --------------------------------------------------------------------------- #


def test_head_defaults_to_current_branch(with_origin: Path, token_configured, captured) -> None:
    ok, _ = github.create_pull_request(with_origin, {"base": "dev"})
    assert ok
    assert captured[0]["payload"]["head"] == "feature/x"


def test_explicit_head_overrides_current_branch(with_origin: Path, token_configured, captured) -> None:
    ok, _ = github.create_pull_request(with_origin, {"base": "dev", "head": "other-branch"})
    assert ok
    assert captured[0]["payload"]["head"] == "other-branch"


def test_base_defaults_to_dev(with_origin: Path, token_configured, captured) -> None:
    ok, _ = github.create_pull_request(with_origin, {})
    assert ok
    assert captured[0]["payload"]["base"] == "dev"


def test_title_defaults_when_blank(with_origin: Path, token_configured, captured) -> None:
    ok, _ = github.create_pull_request(with_origin, {"base": "dev"})
    assert ok
    assert "feature/x" in captured[0]["payload"]["title"]
    assert "dev" in captured[0]["payload"]["title"]


def test_explicit_title_and_body_passed_through(with_origin: Path, token_configured, captured) -> None:
    ok, _ = github.create_pull_request(
        with_origin, {"base": "dev", "title": "Add dark mode", "body": "Details here"}
    )
    assert ok
    assert captured[0]["payload"]["title"] == "Add dark mode"
    assert captured[0]["payload"]["body"] == "Details here"


# --------------------------------------------------------------------------- #
# success message                                                            #
# --------------------------------------------------------------------------- #


def test_success_message_includes_pr_url(with_origin: Path, token_configured, captured) -> None:
    ok, msg = github.create_pull_request(with_origin, {"base": "dev"})
    assert ok
    assert "https://github.com/acme/widgets/pull/7" in msg
