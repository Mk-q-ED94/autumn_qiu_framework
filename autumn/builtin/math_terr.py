"""Math / numerical computation capability domain.

``calc`` uses an AST whitelist so the model can evaluate arbitrary arithmetic
expressions without ever touching :func:`eval`. Constants like ``pi`` and
``e`` and the common ``math.*`` functions are exposed; everything else is
rejected at parse time.

Primitive tools (standalone-callable):
    calc, stats, percentage, clamp, linear_scale, convert_unit

Compound skills (orchestrate multiple primitives):
    stats_summary
"""
from __future__ import annotations

import ast
import json
import math
import operator
import statistics
from typing import Any

from ..core.components.skill import Skill
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


# ── Primitive tool functions (exported for standalone use) ────────────────────


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


async def _percentage(value: float, total: float) -> str:
    """Return ``value`` as a percentage of ``total``."""
    if total == 0:
        raise ValueError("total cannot be zero")
    return f"{(value / total * 100):.6g}%"


async def _clamp(value: float, min_v: float, max_v: float) -> float:
    """Clamp ``value`` to the range [min_v, max_v]."""
    if min_v > max_v:
        raise ValueError(f"min_v ({min_v}) must be <= max_v ({max_v})")
    return max(min_v, min(max_v, value))


async def _linear_scale(
    value: float,
    in_min: float,
    in_max: float,
    out_min: float,
    out_max: float,
) -> float:
    """Linearly map ``value`` from [in_min, in_max] to [out_min, out_max]."""
    if in_min == in_max:
        raise ValueError("in_min and in_max must be different")
    return out_min + (value - in_min) / (in_max - in_min) * (out_max - out_min)


# Unit tables: every unit stored as its factor relative to the base unit.
_LENGTH_UNITS: dict[str, float] = {
    "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
    "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344,
}
_WEIGHT_UNITS: dict[str, float] = {
    "mg": 1e-6, "g": 0.001, "kg": 1.0, "t": 1000.0,
    "oz": 0.028349523125, "lb": 0.45359237,
}
_AREA_UNITS: dict[str, float] = {
    "cm2": 1e-4, "m2": 1.0, "km2": 1e6,
    "in2": 6.4516e-4, "ft2": 0.09290304, "acre": 4046.8564224, "ha": 10_000.0,
}
_TIME_UNITS: dict[str, float] = {
    "ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0,
    "day": 86400.0, "week": 604800.0,
}
_UNIT_GROUPS: list[dict[str, float]] = [_LENGTH_UNITS, _WEIGHT_UNITS, _AREA_UNITS, _TIME_UNITS]
_TEMP_UNITS = {"c", "f", "k"}


async def _convert_unit(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a numeric value between compatible units.

    Supports length (mm/cm/m/km/in/ft/yd/mi), weight (mg/g/kg/t/oz/lb),
    area (cm2/m2/km2/in2/ft2/acre/ha), time (ms/s/min/h/day/week), and
    temperature (c/f/k).
    """
    fu, tu = from_unit.lower(), to_unit.lower()
    # Temperature needs special handling (offset, not ratio)
    if fu in _TEMP_UNITS or tu in _TEMP_UNITS:
        if fu == "c":
            celsius = float(value)
        elif fu == "f":
            celsius = (float(value) - 32) * 5 / 9
        elif fu == "k":
            celsius = float(value) - 273.15
        else:
            raise ValueError(f"unknown temperature unit: {from_unit!r}")
        if tu == "c":
            result = celsius
        elif tu == "f":
            result = celsius * 9 / 5 + 32
        elif tu == "k":
            result = celsius + 273.15
        else:
            raise ValueError(f"unknown temperature unit: {to_unit!r}")
        return f"{result:.10g}"
    for group in _UNIT_GROUPS:
        if fu in group and tu in group:
            base = float(value) * group[fu]
            return f"{base / group[tu]:.10g}"
    raise ValueError(
        f"incompatible or unknown units: {from_unit!r} → {to_unit!r}. "
        "Supported groups: length, weight, area, time, temperature (c/f/k)."
    )


async def _solve_linear(a: float, b: float) -> str:
    """Solve the linear equation a·x + b = 0 for x. Returns x = -b/a."""
    if a == 0:
        raise ValueError("coefficient 'a' must be non-zero for a unique solution")
    return f"{(-b / a):.10g}"


async def _compound_interest(
    principal: float,
    rate: float,
    periods: float,
    times_per_period: int = 1,
) -> str:
    """Compute the future value under compound interest as a JSON object.

    ``rate`` is the per-period nominal rate (e.g. 0.05 for 5%). ``periods`` is
    the number of periods. ``times_per_period`` is the compounding frequency
    within each period (1 = annual, 12 = monthly when a period is a year).
    Returns JSON with the final amount and the total interest earned.
    """
    if times_per_period < 1:
        raise ValueError("times_per_period must be >= 1")
    if principal < 0:
        raise ValueError("principal must be non-negative")
    n = times_per_period
    amount = principal * (1 + rate / n) ** (n * periods)
    return json.dumps({
        "final_amount": round(amount, 6),
        "interest": round(amount - principal, 6),
        "principal": principal,
    }, ensure_ascii=False)


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _stats_summary(values: list[float]) -> str:
    """Return all common statistics at once as a JSON object.

    Computes count, min, max, sum, mean, median, stdev (if ≥2 values),
    variance, and quartiles (q1, q3).
    """
    if not values:
        raise ValueError("values list is empty")
    nums = sorted(float(v) for v in values)
    n = len(nums)
    result: dict[str, Any] = {
        "count": n,
        "min": nums[0],
        "max": nums[-1],
        "sum": sum(nums),
        "mean": statistics.fmean(nums),
        "median": statistics.median(nums),
    }
    if n >= 2:
        result["stdev"] = statistics.stdev(nums)
        result["variance"] = statistics.variance(nums)
    # Quartiles (method: lower/upper halves)
    lower = nums[: n // 2]
    upper = nums[(n + 1) // 2:]
    if lower:
        result["q1"] = statistics.median(lower)
    if upper:
        result["q3"] = statistics.median(upper)
    result["range"] = nums[-1] - nums[0]
    return json.dumps(
        {k: round(v, 10) if isinstance(v, float) else v for k, v in result.items()},
        ensure_ascii=False,
    )


async def _linear_regression(points: list[list[float]]) -> str:
    """Fit a least-squares line y = slope·x + intercept over (x, y) points.

    ``points`` is a list of ``[x, y]`` pairs. Returns JSON with slope,
    intercept, r_squared (goodness of fit), and n (point count). Useful for
    trend detection and simple forecasting.
    """
    if len(points) < 2:
        raise ValueError("linear_regression requires at least two points")
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("each point must be a [x, y] numeric pair") from exc
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    if ss_xx == 0:
        raise ValueError("all x values are identical; slope is undefined")
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot else 1.0
    return json.dumps({
        "slope": round(slope, 10),
        "intercept": round(intercept, 10),
        "r_squared": round(r_squared, 10),
        "n": n,
    }, ensure_ascii=False)


# ── Terr factory ──────────────────────────────────────────────────────────────


def math_terr() -> Terr:
    """Build the ``math`` Terr — safe arithmetic, statistics, and unit conversion.

    Primitive tools (standalone-callable):
        calc(expression)                          → safe AST-evaluated arithmetic
        stats(values, metric)                     → single statistic over a list
        percentage(value, total)                  → value as percent of total
        clamp(value, min_v, max_v)                → bound a value to a range
        linear_scale(value, in_min, in_max, …)   → linear interpolation / remapping
        convert_unit(value, from_unit, to_unit)   → cross-unit numeric conversion

    Compound skills (orchestrate primitives):
        stats_summary(values)                     → all statistics as JSON
    """
    return Terr(
        name="math",
        description=(
            "Safe arithmetic, statistics, and numeric utility operations. "
            "Primitive tools for single calculations; compound skill for full "
            "descriptive statistics in one call."
        ),
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
            Tool(
                name="percentage",
                description="Return value as a percentage of total (e.g. 25/200 → '12.5%').",
                fn=_percentage,
                parameters=[
                    ToolParameter("value", "number", "The numerator."),
                    ToolParameter("total", "number", "The denominator (must be non-zero)."),
                ],
            ),
            Tool(
                name="clamp",
                description="Clamp a number to the range [min_v, max_v].",
                fn=_clamp,
                parameters=[
                    ToolParameter("value", "number", "The value to clamp."),
                    ToolParameter("min_v", "number", "Lower bound."),
                    ToolParameter("max_v", "number", "Upper bound."),
                ],
            ),
            Tool(
                name="linear_scale",
                description=(
                    "Linearly remap a value from one range to another. "
                    "Useful for normalising or scaling sensor readings, coordinates, etc."
                ),
                fn=_linear_scale,
                parameters=[
                    ToolParameter("value", "number", "Input value to remap."),
                    ToolParameter("in_min", "number", "Minimum of the input range."),
                    ToolParameter("in_max", "number", "Maximum of the input range."),
                    ToolParameter("out_min", "number", "Minimum of the output range."),
                    ToolParameter("out_max", "number", "Maximum of the output range."),
                ],
            ),
            Tool(
                name="convert_unit",
                description=(
                    "Convert a numeric value between compatible units. "
                    "Length: mm/cm/m/km/in/ft/yd/mi. "
                    "Weight: mg/g/kg/t/oz/lb. "
                    "Area: cm2/m2/km2/in2/ft2/acre/ha. "
                    "Time: ms/s/min/h/day/week. "
                    "Temperature: c/f/k."
                ),
                fn=_convert_unit,
                parameters=[
                    ToolParameter("value", "number", "The numeric value to convert."),
                    ToolParameter("from_unit", "string", "Source unit (e.g. 'kg', 'ft', 'c')."),
                    ToolParameter("to_unit", "string", "Target unit (e.g. 'lb', 'm', 'f')."),
                ],
            ),
            Tool(
                name="solve_linear",
                description="Solve the linear equation a·x + b = 0 for x (returns -b/a).",
                fn=_solve_linear,
                parameters=[
                    ToolParameter("a", "number", "Coefficient of x (must be non-zero)."),
                    ToolParameter("b", "number", "Constant term."),
                ],
            ),
            Tool(
                name="compound_interest",
                description=(
                    "Compute future value under compound interest. Returns JSON with "
                    "final_amount and interest. rate is the per-period rate (0.05 = 5%); "
                    "times_per_period is the compounding frequency (1=annual, 12=monthly)."
                ),
                fn=_compound_interest,
                parameters=[
                    ToolParameter("principal", "number", "The starting principal."),
                    ToolParameter("rate", "number", "Per-period nominal rate, e.g. 0.05."),
                    ToolParameter("periods", "number", "Number of periods."),
                    ToolParameter("times_per_period", "integer",
                                  "Compounding frequency per period. Default 1.",
                                  required=False),
                ],
            ),
        ],
        skills=[
            Skill(
                name="linear_regression",
                description=(
                    "Fit a least-squares line y = slope·x + intercept over a list of "
                    "[x, y] points. Returns JSON with slope, intercept, r_squared, and n. "
                    "Use for trend detection and simple forecasting."
                ),
                handler=_linear_regression,
                parameters=[
                    ToolParameter("points", "array",
                                  "List of [x, y] numeric pairs.",
                                  extra={"items": {"type": "array", "items": {"type": "number"}}}),
                ],
            ),
            Skill(
                name="stats_summary",
                description=(
                    "Compute all common descriptive statistics over a list of numbers "
                    "in a single call. Returns JSON with: count, min, max, sum, mean, "
                    "median, stdev (if ≥2), variance, q1, q3, and range."
                ),
                handler=_stats_summary,
                parameters=[
                    ToolParameter("values", "array", "Numeric values.",
                                  extra={"items": {"type": "number"}}),
                ],
            ),
        ],
    )


__all__ = [
    "math_terr",
    # primitive fns
    "_calc", "_stats", "_percentage", "_clamp", "_linear_scale", "_convert_unit",
    "_solve_linear", "_compound_interest",
    # compound skill fns
    "_stats_summary", "_linear_regression",
]
