"""
Transforms a Lark parse tree into our typed AST.

Uses lark's Transformer pattern: each method name matches a grammar rule name
and receives already-transformed children.
"""
from __future__ import annotations

import math
from typing import Any

from lark import Transformer, Token, Tree

from app.pinescript.ast.ast_nodes import (
    ASTNode, ProgramNode, StrategyDeclNode,
    AssignmentNode, IfNode, ExprStmtNode,
    BinaryOpNode, UnaryOpNode,
    MethodCallNode, FuncCallNode,
    NumberNode, StringNode, BoolNode, NaNNode, VarNode,
    IndexAccessNode, MemberAccessNode,
)


def _pos(token: Token) -> tuple[int, int]:
    return (getattr(token, "line", 0) or 0, getattr(token, "column", 0) or 0)


class ASTBuilder(Transformer):
    """Transforms Lark parse-tree nodes into our AST."""

    # ── Top-level ─────────────────────────────────────────────────────────────

    def start(self, items: list) -> ProgramNode:
        stmts = [s for s in items if isinstance(s, ASTNode)]
        return ProgramNode(statements=stmts)

    def program(self, items: list) -> ProgramNode:
        stmts = [s for s in items if isinstance(s, ASTNode)]
        return ProgramNode(statements=stmts)

    # Drop keyword terminals  
    def OR(self, _): return None
    def AND(self, _): return None
    def NOT(self, _): return None
    def TRUE(self, _): return None
    def FALSE(self, _): return None
    def NA(self, _): return None

    # ── Statements ────────────────────────────────────────────────────────────

    def assign(self, items: list) -> AssignmentNode:
        return self._make_assignment(items)

    def var_assign(self, items: list) -> AssignmentNode:
        return self._make_assignment(items, is_var=True)

    def reassign(self, items: list) -> AssignmentNode:
        return self._make_assignment(items, is_reassign=True)

    def _make_assignment(
        self,
        items: list,
        *,
        is_var: bool = False,
        is_reassign: bool = False,
    ) -> AssignmentNode:
        # var_assign includes VAR_MODIFIER token before name
        name_tok = items[-2]
        value = items[-1]
        name = str(name_tok)
        l, c = _pos(name_tok) if isinstance(name_tok, Token) else (0, 0)
        return AssignmentNode(
            name=name,
            value=value,
            is_var=is_var,
            is_reassign=is_reassign,
            line=l,
            col=c,
        )

    def if_block(self, items: list) -> IfNode:
        condition = items[0]
        body: list[ASTNode] = []
        elif_chain: list[IfNode] = []
        else_body: list[ASTNode] = []

        for item in items[1:]:
            if isinstance(item, IfNode):
                elif_chain.append(item)
            elif isinstance(item, list):
                else_body = item
            elif isinstance(item, ASTNode):
                body.append(item)

        return IfNode(
            condition=condition,
            body=body,
            elif_chain=elif_chain,
            else_body=else_body,
        )

    def elif_block(self, items: list) -> IfNode:
        condition = items[0]
        body = [s for s in items[1:] if isinstance(s, ASTNode)]
        return IfNode(condition=condition, body=body)

    def else_block(self, items: list) -> list:
        return [s for s in items if isinstance(s, ASTNode)]

    def ternary_op(self, items):
        cond, if_true, if_false = items
        return FuncCallNode(
            name="__ternary__",
            args=[cond, if_true, if_false],
        )

    def expr_stmt(self, items: list) -> ExprStmtNode:
        return ExprStmtNode(expr=items[0] if items else None)

    def callstmt(self, items: list) -> ExprStmtNode:
        return ExprStmtNode(expr=items[0] if items else None)

    def subscript(self, items: list) -> IndexAccessNode:
        return IndexAccessNode(series=items[0], index=items[1])

    # ── Binary operators ──────────────────────────────────────────────────────

    def or_op(self, items):
        return BinaryOpNode(op="or", left=items[0], right=items[1])

    def and_op(self, items):
        return BinaryOpNode(op="and", left=items[0], right=items[1])

    def not_op(self, items):
        return UnaryOpNode(op="not", operand=items[0])

    def gt(self, items):
        return BinaryOpNode(op=">", left=items[0], right=items[1])

    def lt(self, items):
        return BinaryOpNode(op="<", left=items[0], right=items[1])

    def gte(self, items):
        return BinaryOpNode(op=">=", left=items[0], right=items[1])

    def lte(self, items):
        return BinaryOpNode(op="<=", left=items[0], right=items[1])

    def eq(self, items):
        return BinaryOpNode(op="==", left=items[0], right=items[1])

    def neq(self, items):
        return BinaryOpNode(op="!=", left=items[0], right=items[1])

    def add(self, items):
        return BinaryOpNode(op="+", left=items[0], right=items[1])

    def sub(self, items):
        return BinaryOpNode(op="-", left=items[0], right=items[1])

    def mul(self, items):
        return BinaryOpNode(op="*", left=items[0], right=items[1])

    def div(self, items):
        return BinaryOpNode(op="/", left=items[0], right=items[1])

    def neg(self, items):
        return UnaryOpNode(op="-", operand=items[0])

    # ── Calls ─────────────────────────────────────────────────────────────────

    def member_access(self, items: list) -> MemberAccessNode:
        return MemberAccessNode(namespace=str(items[0]), member=str(items[1]))

    def method_call(self, items: list) -> MethodCallNode:
        ns = str(items[0])
        method = str(items[1])
        args: list[ASTNode] = []
        kwargs: dict[str, ASTNode] = {}
        if len(items) > 2:
            self._split_args(items[2], args, kwargs)
        return MethodCallNode(namespace=ns, method=method, args=args, kwargs=kwargs)

    def func_call(self, items: list) -> FuncCallNode:
        name = str(items[0])
        args: list[ASTNode] = []
        kwargs: dict[str, ASTNode] = {}
        if len(items) > 1:
            self._split_args(items[1], args, kwargs)
        return FuncCallNode(name=name, args=args, kwargs=kwargs)

    def arg(self, items: list):
        return items[0]

    def arglist(self, items: list) -> list:
        return list(items)

    def kwarg(self, items: list) -> tuple:
        return (str(items[0]), items[1])

    def _split_args(
        self,
        raw: list,
        args: list[ASTNode],
        kwargs: dict[str, ASTNode],
    ) -> None:
        for item in raw:
            if isinstance(item, tuple) and len(item) == 2:
                kwargs[item[0]] = item[1]
            elif isinstance(item, ASTNode):
                args.append(item)

    # ── Index access ─────────────────────────────────────────────────────────

    def index_access(self, items: list) -> IndexAccessNode:
        return IndexAccessNode(series=items[0], index=items[1])

    # ── Literals ─────────────────────────────────────────────────────────────

    def number(self, items) -> NumberNode:
        tok = items[0]
        l, c = _pos(tok) if isinstance(tok, Token) else (0, 0)
        return NumberNode(value=float(str(tok)), line=l, col=c)

    def string_val(self, items) -> StringNode:
        tok = items[0]
        l, c = _pos(tok) if isinstance(tok, Token) else (0, 0)
        raw = str(tok)
        # strip surrounding quotes
        if (raw.startswith('"') and raw.endswith('"')) or \
           (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        return StringNode(value=raw, line=l, col=c)

    def true_val(self, _) -> BoolNode:
        return BoolNode(value=True)

    def false_val(self, _) -> BoolNode:
        return BoolNode(value=False)

    def na_val(self, _) -> NaNNode:
        return NaNNode()

    def var(self, items) -> VarNode:
        tok = items[0]
        l, c = _pos(tok) if isinstance(tok, Token) else (0, 0)
        return VarNode(name=str(tok), line=l, col=c)
