"""Isolated execution of user-authored custom tools.

Custom tools are arbitrary Python, which is fundamentally more dangerous than
the builtin tools (whose behaviour is trusted, path-jailed code). To contain
the blast radius we never ``exec`` tool code in the server process. Instead we
run it in a short-lived subprocess (mirroring app/tools/shell.py's posture):

- **cwd** is the run's repo directory, so relative paths land in the jail;
- the **environment is scrubbed** — API keys and other secrets are dropped so a
  tool cannot exfiltrate them;
- a **wall-clock timeout** and best-effort **CPU / memory rlimits** bound runaway
  code;
- **output is capped**.

This is a real process boundary, not a full sandbox: a determined tool can still
reach the network or read absolute paths outside the repo. That trade-off is
acceptable for a single-user local tool, and is the reason tool code is only
ever created through a human-reviewed flow.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL_TIMEOUT = 60  # seconds of wall-clock time per tool call
CPU_SECONDS = 30  # RLIMIT_CPU
MEMORY_BYTES = 512 * 1024 * 1024  # RLIMIT_AS (best effort; flaky on macOS)
MAX_OUTPUT = 200_000

RUNNER = Path(__file__).resolve().parent / "_pyrunner.py"

# Environment variables that must never reach tool code.
_SECRET_KEYS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "DATADOG_API_KEY",
    "DD_API_KEY",
    "OPENAI_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
}
# Only a minimal, non-sensitive allowlist of env vars is forwarded.
_SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SystemRoot"}


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    env["PYTHONIOENCODING"] = "utf-8"
    # Defensive: even if a safe key ever overlapped a secret name, drop it.
    for key in _SECRET_KEYS:
        env.pop(key, None)
    return env


def _set_limits() -> None:  # pragma: no cover - runs in the child, POSIX only
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        except (ValueError, OSError):
            pass  # RLIMIT_AS is unreliable on macOS; CPU + wall timeout still apply.
    except Exception:
        pass


def run_python_tool(
    source: str, root: Path, params: dict
) -> tuple[bool, str]:
    """Execute a custom tool's source in an isolated subprocess and return
    (success, output). Never raises for tool-level failures — errors and
    tracebacks are captured into the output string."""
    with tempfile.TemporaryDirectory(prefix="tool-") as tmp:
        payload_path = Path(tmp) / "payload.json"
        result_path = Path(tmp) / "result.json"
        payload_path.write_text(
            json.dumps({"source": source, "params": params}), encoding="utf-8"
        )
        argv = [sys.executable, str(RUNNER), str(payload_path), str(result_path)]
        kwargs: dict = {
            "cwd": str(root),
            "capture_output": True,
            "text": True,
            "timeout": TOOL_TIMEOUT,
            "env": _child_env(),
        }
        if os.name == "posix":
            kwargs["preexec_fn"] = _set_limits
        try:
            proc = subprocess.run(argv, **kwargs)
        except subprocess.TimeoutExpired:
            return False, f"tool timed out after {TOOL_TIMEOUT}s"

        if not result_path.exists():
            err = (proc.stderr or proc.stdout or "no output").strip()[:MAX_OUTPUT]
            return False, f"tool process crashed (exit {proc.returncode}): {err}"
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return False, f"could not read tool result: {exc}"
        return bool(data.get("success")), str(data.get("output", ""))[:MAX_OUTPUT]
