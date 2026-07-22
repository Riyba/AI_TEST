"""Pure helpers in graph/nodes.py: prompt templating and predicate evaluation
(the logic condition nodes route on)."""

from __future__ import annotations

from app.graph.nodes import _eval_predicate, build_agent_system, render
from app.graph.spec import Predicate
from conftest import make_agent


# --------------------------------------------------------------------------- #
# render                                                                       #
# --------------------------------------------------------------------------- #


def test_render_substitutes_known_placeholders() -> None:
    state = {"task": "ship it", "repo_path": "/r", "last_output": "prev"}
    assert render("Task: {task} in {repo_path}", state) == "Task: ship it in /r"


def test_render_injects_node_outputs() -> None:
    state = {"task": "t", "node_outputs": {"n1": "hello"}}
    assert render("prior said: {n1}", state) == "prior said: hello"


def test_render_blanks_unknown_placeholder() -> None:
    """_SafeDict blanks unknown keys rather than raising KeyError — e.g. a
    loop-back prompt referencing a node not yet reached on this path."""
    assert render("value is [{mystery}]", {"task": "t"}) == "value is []"


def test_render_defaults_missing_state_keys_to_empty() -> None:
    assert render("[{last_output}]", {}) == "[]"


# --------------------------------------------------------------------------- #
# _eval_predicate                                                             #
# --------------------------------------------------------------------------- #


def test_output_contains_true() -> None:
    pred = Predicate(kind="output_contains", value="PASS")
    assert _eval_predicate(pred, {"last_output": "tests PASS ok"}) is True


def test_output_contains_is_case_insensitive() -> None:
    pred = Predicate(kind="output_contains", value="pass")
    assert _eval_predicate(pred, {"last_output": "ALL PASS"}) is True


def test_output_not_contains() -> None:
    pred = Predicate(kind="output_not_contains", value="error")
    assert _eval_predicate(pred, {"last_output": "all good"}) is True
    assert _eval_predicate(pred, {"last_output": "an Error occurred"}) is False


def test_tool_success_predicate() -> None:
    pred = Predicate(kind="tool_success")
    assert _eval_predicate(pred, {"last_tool_success": True}) is True
    assert _eval_predicate(pred, {"last_tool_success": False}) is False


def test_predicate_targets_specific_node_output() -> None:
    pred = Predicate(kind="output_contains", value="yes", node_id="n2")
    state = {"last_output": "no", "node_outputs": {"n2": "yes indeed"}}
    assert _eval_predicate(pred, state) is True


# --------------------------------------------------------------------------- #
# should_retry predicate                                                      #
# --------------------------------------------------------------------------- #


def test_should_retry_true_when_retryable_failure_under_budget() -> None:
    pred = Predicate(kind="should_retry")
    state = {"last_tool_success": False, "last_tool_retryable": True, "last_tool_attempts": 1}
    assert _eval_predicate(pred, state, max_attempts=5) is True


def test_should_retry_false_after_success() -> None:
    pred = Predicate(kind="should_retry")
    state = {"last_tool_success": True, "last_tool_retryable": True, "last_tool_attempts": 1}
    assert _eval_predicate(pred, state, max_attempts=5) is False


def test_should_retry_false_when_failure_is_terminal() -> None:
    """A non-retryable failure (missing prereq) must not invite another try."""
    pred = Predicate(kind="should_retry")
    state = {"last_tool_success": False, "last_tool_retryable": False, "last_tool_attempts": 1}
    assert _eval_predicate(pred, state, max_attempts=5) is False


def test_should_retry_false_when_budget_spent() -> None:
    pred = Predicate(kind="should_retry")
    state = {"last_tool_success": False, "last_tool_retryable": True, "last_tool_attempts": 5}
    assert _eval_predicate(pred, state, max_attempts=5) is False


# --------------------------------------------------------------------------- #
# build_agent_system                                                         #
# --------------------------------------------------------------------------- #


def test_build_agent_system_includes_role_and_repo() -> None:
    system = build_agent_system(make_agent(role="reviewer"), "/repo/x")
    assert "Role: reviewer" in system
    assert "/repo/x" in system
