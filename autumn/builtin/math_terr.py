"""Math / numerical computation capability domain.

``calc`` uses an AST whitelist so the model can evaluate arbitrary arithmetic
expressions without ever touching :func:`eval`. Constants like ``pi`` and
``e`` and the common ``math.*`` functions are exposed; everything else is
rejected at parse time.
"""
from __future__ import annotations

import ast
import math
import operator
import statistics
from typing import Any

from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# DoS ceilings — the AST grammar is safe from code execution, but ``**`` and
# ``factorial`` can still ask for an astronomically large integer that hangs the
# event loop / exhausts memory. Bound them before the expensive op runs.
_MAX_POW_EXPONENT = 10_000
_MAX_FACTORIAL = 10_000
_MAX_INT_BITS = 256_000  # ~77k decimal digits — generous for honest math, bounded


def _guard_int(value: Any) -> Any:
    """Reject an integer result whose magnitude has grown past the ceiling."""
    if isinstance(value, int) and value.bit_length() > _MAX_INT_BITS:
        raise ValueError("integer result too large")
    return value


_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
    "nan": math.nan,
}

_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    # math.* projection
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
    "gcd": math.gcd,
    "pow": math.pow,
    "hypot": math.hypot,
    "degrees": math.degrees,
    "radians": math.radians,
}


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"unknown name: {node.id!r}")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            # Bound the exponent (and the estimated result size) *before* the
            # power is computed, so ``2 ** 99999999`` is rejected, not evaluated.
            if isinstance(right, int) and abs(right) > _MAX_POW_EXPONENT:
                raise ValueError("exponent too large")
            if isinstance(left, int) and isinstance(right, int) and right > 0:
                if max(left.bit_length(), 1) * right > _MAX_INT_BITS:
                    raise ValueError("power result too large")
        return _guard_int(op(left, right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported unary op: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ValueError("function call not allowed")
        args = [_eval_node(a) for a in node.args]
        if node.func.id == "factorial" and args and isinstance(args[0], (int, float)) and args[0] > _MAX_FACTORIAL:
            raise ValueError("factorial argument too large")
        return _guard_int(_FUNCS[node.func.id](*args))
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


async def _calc(expression: str) -> str:
    """Evaluate ``expression`` against a tiny arithmetic grammar."""
    # 1024 chars is plenty for honest math; bigger inputs usually mean abuse.
    if len(expression) > 1024:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    result = _eval_node(tree)
    if isinstance(result, float):
        # Format compactly: drop trailing .0 for whole-number floats.
        if result.is_integer() and abs(result) < 1e16:
            return str(int(result))
        return f"{result:.10g}"
    return str(result)


async def _stats(values: list[float], metric: str = "mean") -> str:
    if not values:
        raise ValueError("values list is empty")
    nums = [float(v) for v in values]
    if metric == "mean":
        return f"{statistics.fmean(nums):.10g}"
    if metric == "median":
        return f"{statistics.median(nums):.10g}"
    if metric == "stdev":
        if len(nums) < 2:
            raise ValueError("stdev requires at least two values")
        return f"{statistics.stdev(nums):.10g}"
    if metric == "min":
        return f"{min(nums):.10g}"
    if metric == "max":
        return f"{max(nums):.10g}"
    if metric == "sum":
        return f"{sum(nums):.10g}"
    if metric == "count":
        return str(len(nums))
    raise ValueError(f"unknown metric: {metric}")


def math_terr() -> Terr:
    """Build the ``math`` Terr — safe arithmetic and basic statistics."""
    return Terr(
        name="math",
        description="Safe arithmetic evaluation and basic statistics.",
        tools=[
            Tool(
                name="calc",
                description=(
                    "Evaluate an arithmetic expression. Supports +, -, *, /, //, %, **, "
                    "constants pi/e/tau, and math functions: sqrt, exp, log/log2/log10, "
                    "sin/cos/tan/asin/acos/atan/atan2, floor/ceil, factorial, gcd, pow, "
                    "hypot, degrees, radians, abs, round, min, max, sum."
                ),
                fn=_calc,
                parameters=[
                    ToolParameter("expression", "string", "The arithmetic expression."),
                ],
            ),
            Tool(
                name="stats",
                description="Compute a basic statistic over a list of numbers.",
                fn=_stats,
                parameters=[
                    ToolParameter("values", "array", "Numeric values.",
                                  extra={"items": {"type": "number"}}),
                    ToolParameter("metric", "string",
                                  "mean | median | stdev | min | max | sum | count.",
                                  required=False,
                                  extra={"enum": ["mean", "median", "stdev", "min",
                                                  "max", "sum", "count"]}),
                ],
            ),
        ],
    )
