"""Standalone harness that executes one custom tool in an isolated subprocess.

Invoked as:  python _pyrunner.py <payload_json> <result_json>

It deliberately imports nothing from the ``app`` package — the whole point is
that user-authored tool code runs in a fresh process that never touches the
server's settings, database, or API credentials. The parent (app/tools/pyexec.py)
sets cwd to the run's repo, scrubs the environment, and enforces timeouts and
resource limits before this script runs.

Contract: the tool source must define a top-level ``run(params) -> str``.
Returning a ``(bool, str)`` tuple sets (success, output) explicitly; any other
return value is treated as a successful string result. Raising signals failure.
"""

import contextlib
import io
import json
import sys
import traceback

MAX_OUTPUT = 200_000


def main() -> None:
    payload_path, result_path = sys.argv[1], sys.argv[2]
    with open(payload_path, encoding="utf-8") as f:
        payload = json.load(f)
    source = payload["source"]
    params = payload.get("params") or {}

    buf = io.StringIO()
    try:
        namespace: dict = {"__name__": "__tool__"}
        with contextlib.redirect_stdout(buf):
            exec(compile(source, "<custom_tool>", "exec"), namespace)
            fn = namespace.get("run")
            if not callable(fn):
                raise RuntimeError(
                    "tool source must define a top-level function: def run(params): ..."
                )
            ret = fn(params)
        if isinstance(ret, tuple) and len(ret) == 2:
            success, output = bool(ret[0]), str(ret[1])
        else:
            success, output = True, "" if ret is None else str(ret)
        printed = buf.getvalue().strip()
        if printed:
            output = f"{output}\n{printed}".strip() if output else printed
        result = {"success": success, "output": output[:MAX_OUTPUT]}
    except Exception:
        printed = buf.getvalue()
        tb = traceback.format_exc()
        combined = (f"{printed}\n{tb}" if printed.strip() else tb).strip()
        result = {"success": False, "output": combined[:MAX_OUTPUT]}

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
