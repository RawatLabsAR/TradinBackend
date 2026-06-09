"""
Pine Script DSL parser — TradingView Pine v5 compatible subset.

Uses Lark with its built-in Indenter to handle Python/Pine-like indented blocks.
Type annotations are stripped by pine_compat.preprocess before parsing.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from lark import Lark
from lark.indenter import Indenter

from app.pinescript.ast.ast_nodes import ProgramNode
from app.pinescript.ast.ast_builder import ASTBuilder
from app.pinescript.parser.pine_compat import preprocess

logger = logging.getLogger(__name__)


class PineIndenter(Indenter):
    NL_type = "_NEWLINE"
    OPEN_PAREN_types = ["LPAR", "LSQB"]
    CLOSE_PAREN_types = ["RPAR", "RSQB"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 4


PINE_GRAMMAR = r"""
    start: _NEWLINE* stmt*

    ?stmt: assign _NEWLINE+
         | if_block
         | callstmt _NEWLINE+

    assign: NAME ":=" expr                    -> reassign
          | VAR_MODIFIER NAME "=" expr        -> var_assign
          | NAME "=" expr                     -> assign

    VAR_MODIFIER: "var" | "varip"

    if_block: "if" expr _NEWLINE _INDENT stmt+ _DEDENT elif_block* else_block?

    elif_block: "else" "if" expr _NEWLINE _INDENT stmt+ _DEDENT

    else_block: "else" _NEWLINE _INDENT stmt+ _DEDENT

    callstmt: func_call | method_call

    ?expr: ternary

    ?ternary: or_expr
            | or_expr "?" or_expr ":" or_expr -> ternary_op

    ?or_expr: and_expr
            | or_expr "or" and_expr   -> or_op

    ?and_expr: not_expr
             | and_expr "and" not_expr -> and_op

    ?not_expr: comparison
             | "not" not_expr          -> not_op

    ?comparison: arith
               | comparison ">"  arith -> gt
               | comparison "<"  arith -> lt
               | comparison ">=" arith -> gte
               | comparison "<=" arith -> lte
               | comparison "==" arith -> eq
               | comparison "!=" arith -> neq

    ?arith: term
          | arith "+" term -> add
          | arith "-" term -> sub

    ?term: factor
         | term "*" factor -> mul
         | term "/" factor -> div

    ?factor: "-" primary   -> neg
           | primary

    ?primary: func_call
            | method_call
            | member_access
            | subscript
            | atom

    member_access: NAME "." member_ref           -> member_access

    member_ref: NAME
               | "long" | "short"

    subscript: NAME "[" expr "]"       -> index_access

    func_call:   NAME "(" arglist? ")"
    method_call: NAME "." NAME "(" arglist? ")"

    arglist: arg ("," arg)*
    arg: expr | NAME "=" expr        -> kwarg

    ?atom: number
         | string_val
         | bool_val
         | na_val
         | "(" expr ")"
         | var

    number:     NUMBER
    string_val: ESCAPED_STRING
    bool_val:   "true"  -> true_val
              | "false" -> false_val
    na_val:     "na"
    var:        NAME

    NAME: /(?!(var|varip|if|else|and|or|not|true|false|na)\b)[a-zA-Z_][a-zA-Z0-9_]*/
    NUMBER: /\d+(\.\d*)?([eE][+-]?\d+)?/
    LPAR:   "("
    RPAR:   ")"
    LSQB:   "["
    RSQB:   "]"

    %declare _INDENT _DEDENT
    %import common.ESCAPED_STRING
    %import common.WS_INLINE
    %ignore WS_INLINE
    %ignore /\/\/[^\n]*/
    %ignore /#[^\n]*/

    _NEWLINE: /(\r?\n[\t ]*)+/
"""


@lru_cache(maxsize=1)
def _build_parser() -> Lark:
    return Lark(
        PINE_GRAMMAR,
        parser="lalr",
        lexer="basic",
        postlex=PineIndenter(),
        propagate_positions=True,
    )


def parse(source: str) -> ProgramNode:
    """Parse Pine Script source and return a typed AST."""
    parser = _build_parser()
    source = preprocess(source).strip() + "\n"
    tree = parser.parse(source)
    logger.debug("Parse tree:\n%s", tree.pretty())
    builder = ASTBuilder()
    return builder.transform(tree)
