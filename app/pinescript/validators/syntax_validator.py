"""
Syntax and semantic validator for Pine Script DSL.

Produces structured error reports without executing the script.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from lark.exceptions import UnexpectedInput, UnexpectedCharacters, UnexpectedToken

from app.pinescript.parser.parser_engine import parse
from app.pinescript.sandbox.sandbox_runtime import check_source_limits, SandboxViolation

logger = logging.getLogger(__name__)


@dataclass
class CompilerError:
    line: int
    col: int
    message: str
    severity: str = "error"   # "error" | "warning" | "info"
    source: str = "parser"


@dataclass
class ValidationResult:
    valid: bool
    errors: list[CompilerError] = field(default_factory=list)
    warnings: list[CompilerError] = field(default_factory=list)
    strategy_name: Optional[str] = None
    indicators_used: list[str] = field(default_factory=list)


def validate(source: str) -> ValidationResult:
    """
    Validate Pine Script DSL source.  Never raises — all errors are returned
    as structured CompilerError objects.
    """
    errors: list[CompilerError] = []
    warnings: list[CompilerError] = []

    # 1. Source-level limits
    try:
        check_source_limits(source)
    except SandboxViolation as exc:
        errors.append(CompilerError(line=0, col=0, message=str(exc), source="sandbox"))
        return ValidationResult(valid=False, errors=errors)

    # 2. Parse
    try:
        ast = parse(source)
    except UnexpectedCharacters as exc:
        errors.append(CompilerError(
            line=exc.line,
            col=exc.column,
            message=_friendly_char_error(exc),
            source="lexer",
        ))
        return ValidationResult(valid=False, errors=errors)
    except UnexpectedToken as exc:
        errors.append(CompilerError(
            line=exc.line,
            col=exc.column,
            message=_friendly_token_error(exc),
            source="parser",
        ))
        return ValidationResult(valid=False, errors=errors)
    except UnexpectedInput as exc:
        errors.append(CompilerError(
            line=getattr(exc, "line", 0),
            col=getattr(exc, "column", 0),
            message=str(exc),
            source="parser",
        ))
        return ValidationResult(valid=False, errors=errors)
    except Exception as exc:
        errors.append(CompilerError(
            line=0, col=0,
            message=f"Parse error: {exc}",
            source="parser",
        ))
        return ValidationResult(valid=False, errors=errors)

    # 3. Semantic checks
    from app.pinescript.ast.ast_nodes import (
        ProgramNode, StrategyDeclNode, AssignmentNode,
        MethodCallNode, FuncCallNode, VarNode, IfNode,
    )
    from app.pinescript.indicators.indicator_registry import INDICATOR_REGISTRY, CROSSOVER_REGISTRY

    strategy_name: Optional[str] = None
    indicators_used: list[str] = []
    defined_vars: set[str] = set()
    BUILTIN = {
        "close", "open", "high", "low", "volume",
        "hl2", "hlc3", "ohlc4", "bar_index", "timenow",
    }
    ALLOWED_TA = set(INDICATOR_REGISTRY) | set(CROSSOVER_REGISTRY)
    ALLOWED_STRATEGY = {"entry", "exit", "close", "long", "short"}
    ALLOWED_INPUT = {"int", "float", "bool", "source", "string", "timeframe"}
    ALLOWED_FUNCS = {"strategy", "indicator", "plot", "hline", "input"}

    def walk(node):
        nonlocal strategy_name
        if isinstance(node, StrategyDeclNode):
            strategy_name = node.name
        elif isinstance(node, FuncCallNode) and node.name.lower() in ("strategy", "indicator"):
            if node.args:
                from app.pinescript.ast.ast_nodes import StringNode
                arg0 = node.args[0]
                if isinstance(arg0, StringNode):
                    strategy_name = arg0.value
        elif isinstance(node, AssignmentNode):
            defined_vars.add(node.name)
            if node.value:
                walk(node.value)
        elif isinstance(node, IfNode):
            if node.condition:
                walk(node.condition)
            for stmt in node.body:
                walk(stmt)
            for elif_node in node.elif_chain:
                walk(elif_node)
            for stmt in node.else_body:
                walk(stmt)
        elif isinstance(node, MethodCallNode):
            ns = node.namespace.lower()
            method = node.method.lower()
            if ns == "ta":
                if method not in ALLOWED_TA:
                    errors.append(CompilerError(
                        line=node.line, col=node.col,
                        message=f"Unknown indicator: ta.{method}. "
                                f"Allowed: {', '.join(sorted(ALLOWED_TA))}",
                        source="semantic",
                    ))
                elif method not in indicators_used:
                    indicators_used.append(method)
            elif ns == "strategy":
                if method not in ALLOWED_STRATEGY:
                    errors.append(CompilerError(
                        line=node.line, col=node.col,
                        message=f"Unknown strategy member: strategy.{method}. "
                                f"Allowed: {', '.join(sorted(ALLOWED_STRATEGY))}",
                        source="semantic",
                    ))
            elif ns == "input":
                if method not in ALLOWED_INPUT:
                    errors.append(CompilerError(
                        line=node.line, col=node.col,
                        message=f"Unknown input type: input.{method}. "
                                f"Allowed: {', '.join(sorted(ALLOWED_INPUT))}",
                        source="semantic",
                    ))
            else:
                errors.append(CompilerError(
                    line=node.line, col=node.col,
                    message=f"Unknown namespace '{ns}'. Use ta, strategy, or input.",
                    source="semantic",
                ))
            for a in node.args:
                walk(a)
        elif isinstance(node, FuncCallNode):
            if node.name.lower() not in ALLOWED_FUNCS and node.name.lower() != "__ternary__":
                errors.append(CompilerError(
                    line=node.line, col=node.col,
                    message=f"Unknown function: {node.name}. "
                            f"Allowed: {', '.join(sorted(ALLOWED_FUNCS))}",
                    source="semantic",
                ))
            for a in node.args:
                walk(a)
        elif hasattr(node, "__dataclass_fields__"):
            for fname in node.__dataclass_fields__:
                child = getattr(node, fname)
                if hasattr(child, "__dataclass_fields__"):
                    walk(child)
                elif isinstance(child, list):
                    for item in child:
                        if hasattr(item, "__dataclass_fields__"):
                            walk(item)

    walk(ast)

    if not errors and strategy_name is None:
        warnings.append(CompilerError(
            line=1, col=1,
            message='Consider adding strategy("Name") or indicator("Name") at the top.',
            severity="warning",
            source="semantic",
        ))

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        strategy_name=strategy_name,
        indicators_used=indicators_used,
    )


def _friendly_char_error(exc: UnexpectedCharacters) -> str:
    char = getattr(exc, "char", "?")
    allowed = getattr(exc, "allowed", [])
    base = f"Unexpected character '{char}' at line {exc.line}, column {exc.column}."
    if allowed:
        expected = ", ".join(str(a) for a in list(allowed)[:5])
        return f"{base} Expected one of: {expected}"
    return base


def _friendly_token_error(exc: UnexpectedToken) -> str:
    token = getattr(exc, "token", "?")
    expected = getattr(exc, "expected", [])
    base = f"Unexpected token '{token}' at line {exc.line}, column {exc.column}."
    if expected:
        exp_str = ", ".join(str(e) for e in list(expected)[:5])
        return f"{base} Expected: {exp_str}."
    return base
