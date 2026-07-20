"""Path jailing (tools/fs.py::resolve_jailed) — security sensitive.

Every filesystem tool resolves user-supplied paths through resolve_jailed,
which must confine access to the run's repo directory. These tests exercise
jail-escape attempts explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools import fs


# --------------------------------------------------------------------------- #
# resolve_jailed                                                              #
# --------------------------------------------------------------------------- #


def test_relative_path_stays_inside(repo: Path) -> None:
    resolved = fs.resolve_jailed(repo, "src/main.py")
    assert resolved == (repo / "src" / "main.py").resolve()


def test_absolute_path_inside_root_allowed(repo: Path) -> None:
    inside = repo / "a" / "b.txt"
    resolved = fs.resolve_jailed(repo, str(inside))
    assert resolved == inside.resolve()


def test_dotdot_escape_rejected(repo: Path) -> None:
    with pytest.raises(PermissionError):
        fs.resolve_jailed(repo, "../secret.txt")


def test_deep_dotdot_escape_rejected(repo: Path) -> None:
    with pytest.raises(PermissionError):
        fs.resolve_jailed(repo, "a/b/../../../etc/passwd")


def test_absolute_path_outside_root_rejected(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    with pytest.raises(PermissionError):
        fs.resolve_jailed(repo, str(outside))


def test_absolute_system_path_rejected(repo: Path) -> None:
    with pytest.raises(PermissionError):
        fs.resolve_jailed(repo, "/etc/passwd")


def test_symlink_escape_rejected(repo: Path, tmp_path: Path) -> None:
    """A symlink inside the jail pointing outside must not grant access:
    resolve() follows the link, so the resolved target escapes root."""
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    link = repo / "link"
    link.symlink_to(secret)
    with pytest.raises(PermissionError):
        fs.resolve_jailed(repo, "link")


def test_sibling_prefix_not_confused(tmp_path: Path) -> None:
    """/repo must not be treated as containing /repo-evil (prefix, not parent)."""
    root = tmp_path / "repo"
    root.mkdir()
    sibling = tmp_path / "repo-evil"
    sibling.mkdir()
    with pytest.raises(PermissionError):
        fs.resolve_jailed(root, str(sibling / "x.txt"))


# --------------------------------------------------------------------------- #
# The tools that depend on jailing                                           #
# --------------------------------------------------------------------------- #


def test_read_file_rejects_escape(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("nope")
    with pytest.raises(PermissionError):
        fs.read_file(repo, "../secret.txt")


def test_write_file_rejects_escape(repo: Path, tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        fs.write_file(repo, "../escaped.txt", "data")
    assert not (tmp_path / "escaped.txt").exists()


def test_list_files_rejects_escape(repo: Path) -> None:
    with pytest.raises(PermissionError):
        fs.list_files(repo, "..")


def test_search_files_rejects_escape(repo: Path) -> None:
    with pytest.raises(PermissionError):
        fs.search_files(repo, "pattern", "..")


# --------------------------------------------------------------------------- #
# Normal (in-jail) behaviour of the tools                                    #
# --------------------------------------------------------------------------- #


def test_write_then_read_roundtrip(repo: Path) -> None:
    ok, msg = fs.write_file(repo, "notes/todo.txt", "hello")
    assert ok and "5 chars" in msg
    ok, content = fs.read_file(repo, "notes/todo.txt")
    assert ok and content == "hello"


def test_write_creates_parent_dirs(repo: Path) -> None:
    fs.write_file(repo, "deep/nested/file.txt", "x")
    assert (repo / "deep" / "nested" / "file.txt").is_file()


def test_read_missing_file(repo: Path) -> None:
    ok, msg = fs.read_file(repo, "missing.txt")
    assert not ok and "Not a file" in msg


def test_read_truncates_large_file(repo: Path) -> None:
    big = "a" * (fs.MAX_READ_BYTES + 100)
    fs.write_file(repo, "big.txt", big)
    ok, content = fs.read_file(repo, "big.txt")
    assert ok
    assert "[truncated]" in content
    assert len(content) <= fs.MAX_READ_BYTES + len("\n… [truncated]")


def test_list_files_skips_vendor_dirs(repo: Path) -> None:
    fs.write_file(repo, "src/app.py", "x")
    fs.write_file(repo, "node_modules/pkg/index.js", "y")
    fs.write_file(repo, ".git/config", "z")
    ok, listing = fs.list_files(repo, ".")
    assert ok
    assert "src/app.py" in listing
    assert "node_modules" not in listing
    assert ".git" not in listing


def test_search_files_finds_matches(repo: Path) -> None:
    fs.write_file(repo, "a.py", "def foo():\n    return 1\n")
    fs.write_file(repo, "b.py", "x = 2\n")
    ok, results = fs.search_files(repo, r"def \w+", ".")
    assert ok
    assert "a.py:1:def foo():" in results
    assert "b.py" not in results


def test_search_invalid_regex(repo: Path) -> None:
    ok, msg = fs.search_files(repo, "(unclosed", ".")
    assert not ok and "Invalid regex" in msg


def test_search_empty_pattern(repo: Path) -> None:
    ok, msg = fs.search_files(repo, "", ".")
    assert not ok and "Empty search pattern" in msg
