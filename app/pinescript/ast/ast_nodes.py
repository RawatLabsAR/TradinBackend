"""
AST node definitions for the Pine Script DSL.

All nodes are immutable dataclasses carrying source location for error reporting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ASTNode:
    """Base class for every AST node."""
    line: int = 0
    col: int = 0


# ─────────────────────────── Top-level ──────────────────────────────────────

@dataclass
class ProgramNode(ASTNode):
    statements: list[ASTNode] = field(default_factory=list)


@dataclass
class StrategyDeclNode(ASTNode):
    name: str = "Unnamed"
    options: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────── Statements ─────────────────────────────────────

@dataclass
class AssignmentNode(ASTNode):
    name: str = ""
    value: Optional[ASTNode] = None
    is_var: bool = False       # var x = ...  (init once, persist)
    is_reassign: bool = False  # x := ...


@dataclass
class IfNode(ASTNode):
    condition: Optional[ASTNode] = None
    body: list[ASTNode] = field(default_factory=list)
    elif_chain: list["IfNode"] = field(default_factory=list)
    else_body: list[ASTNode] = field(default_factory=list)


@dataclass
class ExprStmtNode(ASTNode):
    expr: Optional[ASTNode] = None


# ─────────────────────────── Expressions ─────────────────────────────────────

@dataclass
class BinaryOpNode(ASTNode):
    op: str = ""
    left: Optional[ASTNode] = None
    right: Optional[ASTNode] = None


@dataclass
class UnaryOpNode(ASTNode):
    op: str = ""
    operand: Optional[ASTNode] = None


@dataclass
class MethodCallNode(ASTNode):
    """Handles ta.ema(close, 20) and strategy.entry('LONG')."""
    namespace: str = ""   # "ta", "strategy", etc.
    method: str = ""
    args: list[ASTNode] = field(default_factory=list)
    kwargs: dict[str, ASTNode] = field(default_factory=dict)


@dataclass
class FuncCallNode(ASTNode):
    """Bare function call like strategy('EMA Cross')."""
    name: str = ""
    args: list[ASTNode] = field(default_factory=list)
    kwargs: dict[str, ASTNode] = field(default_factory=dict)


# ─────────────────────────── Literals / leaves ───────────────────────────────

@dataclass
class NumberNode(ASTNode):
    value: float = 0.0


@dataclass
class StringNode(ASTNode):
    value: str = ""


@dataclass
class BoolNode(ASTNode):
    value: bool = False


@dataclass
class NaNNode(ASTNode):
    pass


@dataclass
class MemberAccessNode(ASTNode):
    """Namespace constant: strategy.long, strategy.short, etc."""
    namespace: str = ""
    member: str = ""


@dataclass
class VarNode(ASTNode):
    """Reference to a variable or built-in series (close, open, …)."""
    name: str = ""


# ─────────────────────────── Series index ────────────────────────────────────

@dataclass
class IndexAccessNode(ASTNode):
    """Series look-back: close[1] → previous bar's close."""
    series: Optional[ASTNode] = None
    index: Optional[ASTNode] = None
