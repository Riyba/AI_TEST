"""Shell allowlist + no-shell execution (tools/shell.py) — security sensitive.

Commands are parsed with shlex and executed WITHOUT a shell, so injection via
pipes/redirects/substitution must be structurally impossible, and only bare,
allowlisted executables may run. These tests exercise bypass attempts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tools import shell


# --------------------------------------------------------------------------- #
# Shell-metacharacter rejection (injection is structurally blocked)          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "command",
    [
        "ls; rm -rf /",
        "ls | grep secret",
        "ls && curl evil.com",
        "cat file > /etc/passwd",
        "cat < /etc/passwd",
        "echo `whoami`",
        "echo $(whoami)",
        "echo $HOME",
        "ls \\ escaped",
    ],
)
def test_shell_operators_rejected(repo: Path, command: str) -> None:
    ok, msg, *_ = shell.run_command(repo, command)
    assert not ok
    assert "shell operators" in msg


# --------------------------------------------------------------------------- #
# Executable allowlist                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("command", ["rm -rf .", "curl http://evil", "bash script.sh", "sh -c ls", "sudo ls"])
def test_non_allowlisted_executable_rejected(repo: Path, command: str) -> None:
    ok, msg, *_ = shell.run_command(repo, command)
    assert not ok
    assert "not in the allowlist" in msg


@pytest.mark.parametrize("command", ["/bin/ls", "./configure", "../tool/x", "bin/python"])
def test_path_in_executable_rejected(repo: Path, command: str) -> None:
    """The executable must be a bare name — no absolute or relative paths,
    which would sidestep the allowlist by pointing at an arbitrary binary."""
    ok, msg, *_ = shell.run_command(repo, command)
    assert not ok
    assert "bare name" in msg


def test_empty_command_rejected(repo: Path) -> None:
    ok, msg, *_ = shell.run_command(repo, "   ")
    assert not ok and "empty command" in msg


def test_unbalanced_quote_rejected(repo: Path) -> None:
    ok, msg, *_ = shell.run_command(repo, "grep 'unclosed")
    assert not ok and "could not parse" in msg


# --------------------------------------------------------------------------- #
# Allowed commands actually run (no-shell execution path)                    #
# --------------------------------------------------------------------------- #


def test_allowlisted_command_runs(repo: Path) -> None:
    (repo / "hello.txt").write_text("hi")
    ok, output = shell.run_command(repo, "ls")
    assert ok
    assert "hello.txt" in output
    assert "[exit code 0]" in output


def test_command_jailed_to_cwd(repo: Path) -> None:
    """cwd is the repo root; a plain `ls` sees only repo contents."""
    (repo / "only_here.txt").write_text("x")
    ok, output = shell.run_command(repo, "ls")
    assert ok and "only_here.txt" in output


def test_nonzero_exit_reported_as_failure(repo: Path) -> None:
    ok, output = shell.run_command(repo, "cat does_not_exist.txt")
    assert not ok
    assert "[exit code" in output


def test_redirection_never_writes_file(repo: Path) -> None:
    """A redirect attempt is blocked before execution, so no file appears."""
    shell.run_command(repo, "echo pwned > owned.txt")
    assert not (repo / "owned.txt").exists()


# --------------------------------------------------------------------------- #
# run_tests: a stricter runner-only allowlist                                #
# --------------------------------------------------------------------------- #


def test_run_tests_rejects_non_runner(repo: Path) -> None:
    """`ls` is allowed for run_command but is not a test runner."""
    ok, msg, *_ = shell.run_tests(repo, "ls")
    assert not ok
    assert "not in the allowlist" in msg


def test_run_tests_accepts_runner(repo: Path) -> None:
    # `python3 --version` is a runner in the allowlist and exits 0.
    ok, output = shell.run_tests(repo, "python3 --version")
    assert ok
    assert "[exit code 0]" in output


def test_run_tests_no_command_and_undetectable(repo: Path) -> None:
    ok, msg, *_ = shell.run_tests(repo, "")
    assert not ok
    assert "could not detect" in msg


def test_detect_test_command_pytest(repo: Path) -> None:
    (repo / "pyproject.toml").write_text("[project]\n")
    assert shell.detect_test_command(repo) == "pytest -q"


def test_detect_test_command_npm(repo: Path) -> None:
    (repo / "package.json").write_text("{}")
    assert shell.detect_test_command(repo) == "npm test"


def test_detect_test_command_none(repo: Path) -> None:
    assert shell.detect_test_command(repo) is None


def test_detect_test_command_pytest_subdir(repo: Path) -> None:
    """A pyproject in a subdirectory is found and the command targets it."""
    (repo / "backend").mkdir()
    (repo / "backend" / "pyproject.toml").write_text("[project]\n")
    assert shell.detect_test_command(repo) == "pytest -q backend"


def test_detect_test_command_npm_subdir(repo: Path) -> None:
    """A package.json in a subdirectory yields a --prefix'd npm command."""
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text("{}")
    assert shell.detect_test_command(repo) == "npm --prefix frontend test"


def test_detect_test_command_root_takes_precedence(repo: Path) -> None:
    """A root-level marker wins over one nested in a subdirectory."""
    (repo / "pyproject.toml").write_text("[project]\n")
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text("{}")
    assert shell.detect_test_command(repo) == "pytest -q"


def test_detect_test_command_skips_node_modules(repo: Path) -> None:
    """Markers inside vendored/skip dirs must not be detected."""
    nested = repo / "node_modules" / "somepkg"
    nested.mkdir(parents=True)
    (nested / "package.json").write_text("{}")
    assert shell.detect_test_command(repo) is None


def test_detect_test_command_subdir_command_is_runnable(repo: Path) -> None:
    """A detected subdirectory command survives run_tests' parser."""
    (repo / "backend").mkdir()
    (repo / "backend" / "pyproject.toml").write_text("[project]\n")
    command = shell.detect_test_command(repo)
    argv = shell._parse(command, shell.TEST_RUNNERS)
    assert argv == ["pytest", "-q", "backend"]
