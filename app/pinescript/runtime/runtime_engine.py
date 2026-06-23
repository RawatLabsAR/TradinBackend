"""
Runtime engine — evaluates a typed AST against an ExecutionContext.

The engine is a visitor over AST nodes.  It is stateless itself; all mutable
state lives inside ExecutionContext so the same engine instance can run
multiple scripts concurrently (one context each).
"""
from __future__ import annotations

import math
import logging
from typing import Any

import numpy as np

from app.pinescript.ast.ast_nodes import (
    ASTNode, ProgramNode, StrategyDeclNode,
    AssignmentNode, IfNode, ExprStmtNode,
    BinaryOpNode, UnaryOpNode,
    MethodCallNode, FuncCallNode,
    NumberNode, StringNode, BoolNode, NaNNode, VarNode,
    IndexAccessNode, MemberAccessNode,
)
from app.pinescript.runtime.context import ExecutionContext, SeriesValue, Signal
from app.pinescript.indicators.indicator_registry import (
    get_indicator,
    get_crossover_fn,
    ta_crossover,
    ta_crossunder,
    ta_ema,
    ta_sma,
    ta_rsi,
    ta_macd,
    ta_bb,
    ta_atr,
)

logger = logging.getLogger(__name__)


class RuntimeError(Exception):
    """Raised when script execution encounters a semantic error."""
    def __init__(self, msg: str, line: int = 0, col: int = 0) -> None:
        super().__init__(msg)
        self.line = line
        self.col = col


class RuntimeEngine:
    """
    Evaluates Pine Script DSL AST nodes against an ExecutionContext.

    Usage:
        engine = RuntimeEngine()
        for bar_idx in range(num_bars):
            ctx.set_bar(bar_idx)
            engine.run(ast, ctx)
            signals = ctx.strategy.flush_signals()
    """

    def run(self, node: ASTNode, ctx: ExecutionContext) -> Any:
        """Dispatch to typed visitor method."""
        method = f"_eval_{type(node).__name__}"
        visitor = getattr(self, method, self._eval_default)
        return visitor(node, ctx)

    def _eval_default(self, node: ASTNode, ctx: ExecutionContext) -> None:
        logger.warning("No evaluator for %s", type(node).__name__)
        return None

    # ── Program ──────────────────────────────────────────────────────────────

    def _eval_ProgramNode(self, node: ProgramNode, ctx: ExecutionContext) -> None:
        for stmt in node.statements:
            self.run(stmt, ctx)

    # ── Strategy declaration (runs on bar 0 only to register metadata) ───────

    def _eval_StrategyDeclNode(self, node: StrategyDeclNode,
                               ctx: ExecutionContext) -> None:
        ctx.strategy_name = node.name

    # ── Assignment ───────────────────────────────────────────────────────────

    def _eval_AssignmentNode(self, node: AssignmentNode,
                             ctx: ExecutionContext) -> None:
        value = self.run(node.value, ctx)
        if node.is_reassign:
            ctx.reassign_var(node.name, value)
        elif node.is_var:
            ctx.set_var(node.name, value, is_var=True)
        else:
            ctx.set_var(node.name, value)

    # ── If statement ─────────────────────────────────────────────────────────

    def _eval_IfNode(self, node: IfNode, ctx: ExecutionContext) -> None:
        if _truthy(self.run(node.condition, ctx)):
            for stmt in node.body:
                self.run(stmt, ctx)
            return
        for elif_node in node.elif_chain:
            if _truthy(self.run(elif_node.condition, ctx)):
                for stmt in elif_node.body:
                    self.run(stmt, ctx)
                return
        for stmt in node.else_body:
            self.run(stmt, ctx)

    # ── Expression statement ──────────────────────────────────────────────────

    def _eval_ExprStmtNode(self, node: ExprStmtNode,
                           ctx: ExecutionContext) -> Any:
        return self.run(node.expr, ctx)

    # ── Binary operations ────────────────────────────────────────────────────

    def _eval_BinaryOpNode(self, node: BinaryOpNode,
                           ctx: ExecutionContext) -> Any:
        op = node.op

        # Short-circuit logical operators
        if op == "or":
            left = self.run(node.left, ctx)
            if _truthy(left):
                return True
            return _truthy(self.run(node.right, ctx))
        if op == "and":
            left = self.run(node.left, ctx)
            if not _truthy(left):
                return False
            return _truthy(self.run(node.right, ctx))

        left = self.run(node.left, ctx)
        right = self.run(node.right, ctx)

        left = _scalar(left, ctx.bar_index)
        right = _scalar(right, ctx.bar_index)

        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left / right if right != 0 else math.nan
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        if op == ">=":
            return left >= right
        if op == "<=":
            return left <= right
        if op == "==":
            return left == right
        if op == "!=":
            return left != right

        raise RuntimeError(f"Unknown binary operator: {op}")

    # ── Unary operations ──────────────────────────────────────────────────────

    def _eval_UnaryOpNode(self, node: UnaryOpNode,
                          ctx: ExecutionContext) -> Any:
        operand = self.run(node.operand, ctx)
        if node.op == "-":
            return -_scalar(operand, ctx.bar_index)
        if node.op == "not":
            return not _truthy(operand)
        raise RuntimeError(f"Unknown unary operator: {node.op}")

    # ── Variables ────────────────────────────────────────────────────────────

    def _eval_MemberAccessNode(self, node: MemberAccessNode,
                               ctx: ExecutionContext) -> Any:
        ns = node.namespace.lower()
        member = node.member.lower()
        if ns == "strategy":
            if member in ("long", "short"):
                return member
        return f"{ns}.{member}"

    def _eval_VarNode(self, node: VarNode, ctx: ExecutionContext) -> Any:
        try:
            val = ctx.get_var(node.name)
            # get_var returns scalar for series; but SeriesValue stored directly
            # need to extract scalar at current bar
            if isinstance(val, SeriesValue):
                return val.scalar(ctx.bar_index)
            return val
        except NameError as exc:
            raise RuntimeError(str(exc), node.line, node.col) from exc

    # ── Literals ─────────────────────────────────────────────────────────────

    def _eval_NumberNode(self, node: NumberNode, _: ExecutionContext) -> float:
        return node.value

    def _eval_StringNode(self, node: StringNode, _: ExecutionContext) -> str:
        return node.value

    def _eval_BoolNode(self, node: BoolNode, _: ExecutionContext) -> bool:
        return node.value

    def _eval_NaNNode(self, _node: NaNNode, _ctx: ExecutionContext) -> float:
        return math.nan

    # ── Index access: close[1] ────────────────────────────────────────────────

    def _eval_IndexAccessNode(self, node: IndexAccessNode,
                              ctx: ExecutionContext) -> float:
        series_val = self.run(node.series, ctx)
        idx_offset = int(self.run(node.index, ctx))
        target_idx = ctx.bar_index - idx_offset
        if isinstance(series_val, SeriesValue):
            return series_val.scalar(target_idx)
        if isinstance(series_val, np.ndarray):
            if 0 <= target_idx < len(series_val):
                return float(series_val[target_idx])
        return math.nan

    # ── Method calls: ta.* and strategy.* ────────────────────────────────────

    def _eval_MethodCallNode(self, node: MethodCallNode,
                             ctx: ExecutionContext) -> Any:
        ns = node.namespace.lower()

        if ns == "ta":
            return self._call_ta(node, ctx)
        if ns == "strategy":
            return self._call_strategy(node, ctx)
        if ns == "input":
            return self._call_input(node, ctx)

        raise RuntimeError(
            f"Unknown namespace '{ns}'. Supported: ta, strategy, input",
            node.line, node.col,
        )

    def _call_ta(self, node: MethodCallNode, ctx: ExecutionContext) -> Any:
        method = node.method.lower()

        if method in ("crossover", "crossunder"):
            # For crossover/crossunder, resolve args to arrays
            arr_args = [_resolve_to_array(a, ctx, self) for a in node.args]
            fn = ta_crossover if method == "crossover" else ta_crossunder
            return fn(arr_args[0], arr_args[1], ctx.bar_index)

        # For all other ta.* functions, resolve args to arrays
        arr_args = [_resolve_to_array(a, ctx, self) for a in node.args]
        return self._compute_indicator(method, arr_args, ctx)

    def _compute_indicator(
        self,
        method: str,
        args: list,    # already numpy arrays or scalars
        ctx: ExecutionContext,
    ) -> Any:
        """Compute or retrieve cached indicator series."""
        # Build a cache key from method + args
        cache_key = self._indicator_key(method, args, ctx)
        cached = ctx.get_cached_indicator(cache_key)
        if cached is not None:
            return cached  # Return full SeriesValue; callers extract scalar as needed

        fn = get_indicator(method)
        if fn is None:
            raise RuntimeError(f"Unknown indicator: ta.{method}")

        # Convert scalar args (periods) to python int/float
        final_args = []
        for i, a in enumerate(args):
            if isinstance(a, np.ndarray):
                final_args.append(a)
            else:
                final_args.append(float(a) if isinstance(a, (int, float)) else a)

        result = fn(*final_args)

        # Some indicators return tuples (macd, bb, stoch)
        if isinstance(result, tuple):
            # Return primary series; cache all components
            for comp_idx, comp in enumerate(result):
                comp_key = f"{cache_key}_{comp_idx}"
                ctx.cache_indicator(comp_key, SeriesValue(np.asarray(comp, dtype=float)))
            primary = SeriesValue(np.asarray(result[0], dtype=float))
            ctx.cache_indicator(cache_key, primary)
            return primary  # Return SeriesValue so assignment stores the full series
        else:
            sv = SeriesValue(np.asarray(result, dtype=float))
            ctx.cache_indicator(cache_key, sv)
            return sv  # Return SeriesValue so assignment stores the full series

    def _indicator_key(self, method: str, args: list, ctx: ExecutionContext) -> str:
        parts = [method]
        for a in args:
            if isinstance(a, np.ndarray):
                parts.append(f"arr{len(a)}")
            elif isinstance(a, SeriesValue):
                parts.append(f"sv{len(a)}")
            else:
                parts.append(str(a))
        return "_".join(parts)

    def _call_input(self, node: MethodCallNode, ctx: ExecutionContext) -> Any:
        """input.int/float/bool/source — return the default value (arg 0)."""
        if not node.args:
            return 0
        val = self.run(node.args[0], ctx)
        if isinstance(val, SeriesValue):
            return val.scalar(ctx.bar_index)
        return val

    def _call_strategy(self, node: MethodCallNode, ctx: ExecutionContext) -> None:
        method = node.method.lower()
        args = [self.run(a, ctx) for a in node.args]
        price = ctx.current_close
        ts = ctx.current_timestamp

        if method == "entry":
            label = str(args[0]) if args else "LONG"
            direction = str(args[1]).lower() if len(args) > 1 else "long"
            if "short" in direction:
                label = label if "SHORT" in label.upper() else f"{label}_SHORT"
            ctx.strategy.emit_entry(label, price, ctx.bar_index, ts)

        elif method == "exit":
            label = str(args[0]) if args else "exit"
            stop_val = limit_val = None
            if "stop" in node.kwargs:
                stop_val = self.run(node.kwargs["stop"], ctx)
            if "limit" in node.kwargs:
                limit_val = self.run(node.kwargs["limit"], ctx)
            if stop_val is not None or limit_val is not None:
                stop_f = float(stop_val) if stop_val is not None and not isinstance(stop_val, SeriesValue) else None
                limit_f = float(limit_val) if limit_val is not None and not isinstance(limit_val, SeriesValue) else None
                ctx.strategy.set_bracket(stop_f, limit_f)
            else:
                ctx.strategy.emit_exit(label, price, ctx.bar_index, ts)

        elif method == "close":
            target = str(args[0]) if args else None
            if target and ctx.strategy.position:
                ctx.strategy.emit_exit(target, price, ctx.bar_index, ts)
            else:
                ctx.strategy.emit_close(price, ctx.bar_index, ts)

        else:
            raise RuntimeError(
                f"Unknown strategy method: strategy.{method}",
                node.line, node.col,
            )

    # ── Bare function calls (e.g. strategy("Name")) ──────────────────────────

    def _eval_FuncCallNode(self, node: FuncCallNode,
                           ctx: ExecutionContext) -> Any:
        name = node.name.lower()

        if name == "__ternary__":
            cond, if_true, if_false = [self.run(a, ctx) for a in node.args]
            return if_true if _truthy(cond) else if_false

        if name in ("strategy", "indicator"):
            if node.args:
                ctx.strategy_name = str(self.run(node.args[0], ctx))
            return None

        if name == "plot":
            return self._call_plot(node, ctx)

        if name == "hline":
            return self._call_hline(node, ctx)

        if name == "input":
            return self._call_input(
                MethodCallNode(namespace="input", method="source", args=node.args),
                ctx,
            )

        raise RuntimeError(
            f"Unknown function: {node.name}",
            node.line, node.col,
        )

    def _call_plot(self, node: FuncCallNode, ctx: ExecutionContext) -> None:
        if not node.args:
            return None
        series_val = self.run(node.args[0], ctx)
        title = "Plot"
        if len(node.args) > 1:
            title = str(self.run(node.args[1], ctx))
        elif "title" in node.kwargs:
            title = str(self.run(node.kwargs["title"], ctx))

        if isinstance(series_val, SeriesValue):
            ctx.register_plot(title, series_val)
        elif isinstance(series_val, (int, float)):
            arr = np.full(ctx.total_bars, float(series_val))
            ctx.register_plot(title, SeriesValue(arr))
        return None

    def _call_hline(self, node: FuncCallNode, ctx: ExecutionContext) -> None:
        if not node.args:
            return None
        level = float(self.run(node.args[0], ctx))
        title = f"hline_{level}"
        if len(node.args) > 1:
            title = str(self.run(node.args[1], ctx))
        arr = np.full(ctx.total_bars, level)
        ctx.register_plot(title, SeriesValue(arr))
        return None


# ─────────────────────────── Helpers ─────────────────────────────────────────

def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return not math.isnan(v) and v != 0.0
    if isinstance(v, int):
        return v != 0
    return bool(v)


def _scalar(v: Any, idx: int) -> float:
    if isinstance(v, SeriesValue):
        return v.scalar(idx)
    if isinstance(v, np.ndarray):
        if 0 <= idx < len(v):
            x = v[idx]
            return float(x) if not np.isnan(x) else math.nan
        return math.nan
    if isinstance(v, (int, float)):
        return float(v)
    return math.nan


def _to_array(v: Any, ctx: ExecutionContext) -> np.ndarray:
    """Resolve any value to a numpy array over the full history."""
    if isinstance(v, np.ndarray):
        return v.astype(float)
    if isinstance(v, SeriesValue):
        return v.array()
    if isinstance(v, str) and v in ExecutionContext.BUILTIN_SERIES:
        arr = ctx.get_series(v)
        if arr is not None:
            return arr.astype(float)
    if isinstance(v, (int, float)):
        # Scalar → broadcast as constant series
        return np.full(ctx.total_bars, float(v))
    # fallback: all-nan
    return np.full(ctx.total_bars, np.nan)


def _resolve_to_array(
    node: ASTNode,
    ctx: ExecutionContext,
    engine: "RuntimeEngine",
) -> Any:
    """
    Resolve an AST node to its raw form for indicator computation.

    - Series variables (close, open, …) → full numpy array
    - User variables holding a SeriesValue → SeriesValue.array()
    - Number literals → plain float (passed as period/param)
    - Computed results (e.g. ta.ema() inside arg) → scalar float
    """
    from app.pinescript.ast.ast_nodes import VarNode, NumberNode

    if isinstance(node, VarNode):
        name = node.name
        # Built-in OHLCV series → return full array
        if name in ExecutionContext.BUILTIN_SERIES:
            arr = ctx.get_series(name)
            if arr is not None:
                return arr.astype(float)
        # User-defined variable — may be SeriesValue (from ta.ema etc.)
        try:
            raw = ctx._vars.get(name)  # peek directly at raw stored value
        except Exception:
            raw = None
        if isinstance(raw, SeriesValue):
            return raw.array()
        if isinstance(raw, np.ndarray):
            return raw.astype(float)
        # Fall through: scalar or None - evaluate normally
        return engine.run(node, ctx)

    if isinstance(node, NumberNode):
        return node.value

    # For any other node (e.g. nested ta.ema() call as arg),
    # evaluate and return as scalar
    return engine.run(node, ctx)
