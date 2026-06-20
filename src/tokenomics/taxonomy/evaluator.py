"""Safe evaluator for declarative pattern rules.

A rule is a boolean Python expression over the trajectory feature namespace plus
``th`` (the threshold dataclass), e.g. ``thinking_trivial_turns >= th.thinking_trivial``.
Rules ship with the package (semi-trusted), but we still sandbox: no builtins, no
dunder access, and expressions are compiled at load time so a malformed rule is
rejected up front rather than at scan time.
"""

from __future__ import annotations

from types import CodeType


class RuleError(ValueError):
    """A pattern rule failed to compile or referenced something illegal."""


def compile_rule(expr: str) -> CodeType:
    if "__" in expr:
        raise RuleError(f"rule may not use dunder access: {expr!r}")
    try:
        return compile(expr, "<pattern-rule>", "eval")
    except SyntaxError as exc:
        raise RuleError(f"invalid rule {expr!r}: {exc}") from exc


def evaluate(code: CodeType, namespace: dict) -> bool:
    """Evaluate a pre-compiled rule against a namespace. Missing names → False."""
    try:
        return bool(eval(code, {"__builtins__": {}}, namespace))  # noqa: S307 — sandboxed
    except (NameError, TypeError, ZeroDivisionError, AttributeError):
        return False
