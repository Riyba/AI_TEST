"""Git tools (tools/gitops.py): the mutating branch/commit/push trio plus the
two read helpers they lean on. These shell out to a real `git` against a
throwaway repo (and a throwaway bare "origin") rather than mocking subprocess,
since the thing worth testing is git's actual behavior (branch creation,
nothing-to-commit, push semantics), not our wrapper of it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.tools import gitops


def _run(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(repo: Path) -> Path:
    """`repo` (from conftest) as an initialized git repo on branch 'main'
    with one commit, and git identity configured for commits to succeed."""
    _run(repo, "init", "-q", "-b", "main")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def git_repo_with_origin(git_repo: Path, tmp_path: Path) -> Path:
    """git_repo plus a bare 'origin' remote it can fetch from and push to,
    standing in for a real GitHub remote without any network access."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _run(git_repo, "remote", "add", "origin", str(bare))
    _run(git_repo, "push", "-q", "origin", "main")
    return git_repo


# --------------------------------------------------------------------------- #
# current_branch / remote_url                                                #
# --------------------------------------------------------------------------- #


def test_current_branch_reports_checked_out_branch(git_repo: Path) -> None:
    ok, branch = gitops.current_branch(git_repo)
    assert ok and branch == "main"


def test_remote_url_reports_configured_remote(git_repo_with_origin: Path) -> None:
    ok, url = gitops.remote_url(git_repo_with_origin)
    assert ok and "origin.git" in url


def test_remote_url_fails_without_remote(git_repo: Path) -> None:
    ok, msg = gitops.remote_url(git_repo)
    assert not ok


# --------------------------------------------------------------------------- #
# create_branch                                                              #
# --------------------------------------------------------------------------- #


def test_create_branch_falls_back_to_local_base_without_origin(git_repo: Path) -> None:
    """No origin remote => the fetch fails, but branching off the local base
    still succeeds rather than erroring out."""
    ok, msg = gitops.create_branch(git_repo, base="main", name="Add dark mode")
    assert ok, msg
    assert "from 'main'" in msg
    branch_ok, branch = gitops.current_branch(git_repo)
    assert branch_ok and branch.startswith("feature/add-dark-mode-")


def test_create_branch_fetches_and_branches_from_origin(git_repo_with_origin: Path) -> None:
    ok, msg = gitops.create_branch(git_repo_with_origin, base="main", name="x")
    assert ok, msg
    assert "from 'origin/main'" in msg


def test_create_branch_slugifies_arbitrary_text(git_repo: Path) -> None:
    """Punctuation, whitespace, and mixed case in the task description never
    reach git as a raw ref — only lowercase words survive, joined by hyphens."""
    ok, _ = gitops.create_branch(git_repo, base="main", name="Fix Bug #42!! (urgent)")
    assert ok
    _, branch = gitops.current_branch(git_repo)
    assert branch.startswith("feature/fix-bug-42-urgent-")
    assert all(c.islower() or c.isdigit() or c == "-" or c == "/" for c in branch)


def test_create_branch_appends_unique_suffix_on_collision(git_repo: Path) -> None:
    ok1, msg1 = gitops.create_branch(git_repo, base="main", name="same task")
    assert ok1
    _run(git_repo, "checkout", "main")
    ok2, msg2 = gitops.create_branch(git_repo, base="main", name="same task")
    assert ok2
    assert msg1 != msg2  # different random suffixes => different branch names


def test_create_branch_blank_name_still_produces_valid_branch(git_repo: Path) -> None:
    ok, msg = gitops.create_branch(git_repo, base="main", name="")
    assert ok, msg


# --------------------------------------------------------------------------- #
# commit                                                                      #
# --------------------------------------------------------------------------- #


def test_commit_stages_and_commits_changes(git_repo: Path) -> None:
    (git_repo / "new_file.txt").write_text("content")
    ok, out = gitops.commit(git_repo, "add new_file")
    assert ok, out
    log_ok, log_out = gitops.log(git_repo, 1)
    assert log_ok and "add new_file" in log_out


def test_commit_with_nothing_staged_fails(git_repo: Path) -> None:
    ok, msg = gitops.commit(git_repo, "empty commit attempt")
    assert not ok
    assert "nothing to commit" in msg.lower()


def test_commit_blank_message_gets_a_default(git_repo: Path) -> None:
    (git_repo / "f.txt").write_text("x")
    ok, out = gitops.commit(git_repo, "")
    assert ok, out
    _, log_out = gitops.log(git_repo, 1)
    assert "Automated changes" in log_out


# --------------------------------------------------------------------------- #
# push                                                                        #
# --------------------------------------------------------------------------- #


def test_push_defaults_to_current_branch(git_repo_with_origin: Path, tmp_path: Path) -> None:
    ok, branch = gitops.create_branch(git_repo_with_origin, base="main", name="ship it")
    assert ok
    (git_repo_with_origin / "f.txt").write_text("x")
    gitops.commit(git_repo_with_origin, "work")

    ok, out = gitops.push(git_repo_with_origin, "")
    assert ok, out

    _, current = gitops.current_branch(git_repo_with_origin)
    # The bare origin now has the pushed branch under the same name.
    ls = subprocess.run(
        ["git", "branch", "--list", current],
        cwd=tmp_path / "origin.git",
        capture_output=True,
        text=True,
        check=True,
    )
    assert current in ls.stdout


def test_push_without_origin_fails_cleanly(git_repo: Path) -> None:
    ok, msg = gitops.push(git_repo, "main")
    assert not ok
