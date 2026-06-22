"""Time / date capability domain.

Always-safe stdlib-only tools for inspecting and formatting the current moment
and arbitrary timestamps. The model frequently needs ``now`` and ``time_diff``
to ground its reasoning in real time — having these built in saves every
agent author from re-implementing them.

Primitive tools (standalone-callable):
    now, parse_time, time_diff, time_add, time_format, time_in_range, time_floor

Compound skills (orchestrate multiple primitives):
    time_today, time_since, schedule_info
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter


def _parse_iso(s: str) -> datetime:
    # datetime.fromisoformat accepts most ISO 8601 forms in 3.11+.
    return datetime.fromisoformat(s)


# ── Primitive tool functions (exported for standalone use) ────────────────────


async def _now(timezone_name: str = "UTC", fmt: str = "iso") -> str:
    if timezone_name.upper() == "UTC":
        tz = UTC
    else:
        # Lazy import: zoneinfo only needed for non-UTC zones.
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_name)
    dt = datetime.now(tz)
    if fmt == "iso":
        return dt.isoformat()
    if fmt == "unix":
        return str(int(dt.timestamp()))
    if fmt == "date":
        return dt.strftime("%Y-%m-%d")
    if fmt == "time":
        return dt.strftime("%H:%M:%S")
    if fmt == "human":
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    return dt.isoformat()


async def _parse_time(value: str, fmt: str = "iso") -> str:
    if fmt == "unix":
        dt = datetime.fromtimestamp(int(value), tz=UTC)
    elif fmt == "iso":
        dt = _parse_iso(value)
    else:
        dt = datetime.strptime(value, fmt)
    return dt.isoformat()


async def _time_diff(start: str, end: str, unit: str = "seconds") -> str:
    a = _parse_iso(start)
    b = _parse_iso(end)
    delta: timedelta = b - a
    seconds = delta.total_seconds()
    if unit == "seconds":
        return f"{seconds:.3f}"
    if unit == "minutes":
        return f"{seconds / 60:.3f}"
    if unit == "hours":
        return f"{seconds / 3600:.3f}"
    if unit == "days":
        return f"{seconds / 86400:.3f}"
    return f"{seconds:.3f}"


async def _time_add(value: str, amount: int, unit: str = "seconds") -> str:
    dt = _parse_iso(value)
    deltas: dict[str, Any] = {
        "seconds": timedelta(seconds=amount),
        "minutes": timedelta(minutes=amount),
        "hours": timedelta(hours=amount),
        "days": timedelta(days=amount),
        "weeks": timedelta(weeks=amount),
    }
    if unit not in deltas:
        raise ValueError(f"unsupported unit: {unit}")
    return (dt + deltas[unit]).isoformat()


async def _time_format(value: str, fmt: str) -> str:
    """Reformat an ISO 8601 timestamp using a strftime pattern."""
    dt = _parse_iso(value)
    return dt.strftime(fmt)


async def _time_in_range(t: str, start: str, end: str) -> bool:
    """Return true if t falls within [start, end] (both inclusive)."""
    dt = _parse_iso(t)
    a = _parse_iso(start)
    b = _parse_iso(end)
    # Make comparable: strip tz if only some are aware
    if (dt.tzinfo is None) != (a.tzinfo is None):
        dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
        a = a.replace(tzinfo=UTC) if a.tzinfo is None else a
        b = b.replace(tzinfo=UTC) if b.tzinfo is None else b
    return a <= dt <= b


async def _time_floor(value: str, unit: str = "hour") -> str:
    """Floor an ISO 8601 timestamp to the nearest unit boundary."""
    dt = _parse_iso(value)
    if unit == "minute":
        dt = dt.replace(second=0, microsecond=0)
    elif unit == "hour":
        dt = dt.replace(minute=0, second=0, microsecond=0)
    elif unit == "day":
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif unit == "month":
        dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif unit == "year":
        dt = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"unsupported unit: {unit!r}; use minute | hour | day | month | year")
    return dt.isoformat()


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _time_today(timezone_name: str = "UTC") -> str:
    if timezone_name.upper() == "UTC":
        tz = UTC
    else:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_name)
    dt = datetime.now(tz)
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]
    return f"{dt.strftime('%Y-%m-%d')} ({weekday})"


async def _time_since(value: str, timezone_name: str = "UTC") -> str:
    """Human-readable relative time: 'X units ago' or 'in X units'."""
    then = _parse_iso(value)
    if timezone_name.upper() == "UTC":
        tz = UTC
    else:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    # Make both offset-aware before subtracting
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    delta = now - then
    seconds = delta.total_seconds()
    future = seconds < 0
    seconds = abs(seconds)
    suffix = "from now" if future else "ago"
    if seconds < 60:
        n = int(seconds)
        return f"{n} second{'s' if n != 1 else ''} {suffix}"
    elif seconds < 3600:
        n = int(seconds / 60)
        return f"{n} minute{'s' if n != 1 else ''} {suffix}"
    elif seconds < 86400:
        n = int(seconds / 3600)
        return f"{n} hour{'s' if n != 1 else ''} {suffix}"
    elif seconds < 86400 * 30:
        n = int(seconds / 86400)
        return f"{n} day{'s' if n != 1 else ''} {suffix}"
    elif seconds < 86400 * 365:
        n = int(seconds / (86400 * 30))
        return f"{n} month{'s' if n != 1 else ''} {suffix}"
    else:
        n = int(seconds / (86400 * 365))
        return f"{n} year{'s' if n != 1 else ''} {suffix}"


async def _schedule_info(value: str, timezone_name: str = "UTC") -> str:
    """Return a rich schedule summary for an ISO timestamp as a JSON object.

    Includes weekday name, ISO week number, quarter, day of year, and
    human-readable label — useful for scheduling logic and display.
    """
    if timezone_name.upper() == "UTC":
        tz = UTC
    else:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_name)
    dt = _parse_iso(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    iso_cal = dt.isocalendar()
    return json.dumps({
        "iso": dt.isoformat(),
        "weekday": weekday_names[dt.weekday()],
        "is_weekend": dt.weekday() >= 5,
        "iso_week": iso_cal[1],
        "iso_year": iso_cal[0],
        "quarter": (dt.month - 1) // 3 + 1,
        "day_of_year": dt.timetuple().tm_yday,
        "timezone": str(tz),
    }, ensure_ascii=False)


# ── Terr factory ──────────────────────────────────────────────────────────────


def time_terr() -> Terr:
    """Build the ``time`` Terr.

    Primitive tools (standalone-callable):
        now(timezone="UTC", fmt="iso")         → current timestamp
        parse_time(value, fmt="iso")           → normalize to ISO 8601
        time_diff(start, end, unit)            → arithmetic between two ISO timestamps
        time_add(value, amount, unit)          → ISO timestamp shifted by a delta
        time_format(value, fmt)                → reformat with strftime pattern
        time_in_range(t, start, end)           → bool: t ∈ [start, end]
        time_floor(value, unit)                → floor to minute/hour/day/month/year

    Compound skills (orchestrate primitives):
        time_today(timezone="UTC")             → YYYY-MM-DD (Weekday)
        time_since(value, timezone="UTC")      → human 'X units ago'
        schedule_info(value, timezone="UTC")   → rich JSON schedule context
    """
    return Terr(
        name="time",
        description=(
            "Date/time inspection, arithmetic, and formatting. "
            "Primitive tools for timestamp parsing and calculation; "
            "compound skills for human-readable relative time and schedule context."
        ),
        tools=[
            Tool(
                name="now",
                description="Return the current timestamp. Default UTC ISO 8601.",
                fn=_now,
                parameters=[
                    ToolParameter("timezone_name", "string",
                                  "IANA timezone (e.g. 'UTC', 'Asia/Shanghai').",
                                  required=False),
                    ToolParameter("fmt", "string",
                                  "One of: iso, unix, date, time, human.",
                                  required=False,
                                  extra={"enum": ["iso", "unix", "date", "time", "human"]}),
                ],
            ),
            Tool(
                name="parse_time",
                description="Parse a timestamp string into ISO 8601.",
                fn=_parse_time,
                parameters=[
                    ToolParameter("value", "string", "The timestamp to parse."),
                    ToolParameter("fmt", "string",
                                  "'iso', 'unix', or a strptime format string.",
                                  required=False),
                ],
            ),
            Tool(
                name="time_diff",
                description="Subtract two ISO 8601 timestamps and return the delta.",
                fn=_time_diff,
                parameters=[
                    ToolParameter("start", "string", "ISO 8601 start time."),
                    ToolParameter("end", "string", "ISO 8601 end time."),
                    ToolParameter("unit", "string",
                                  "seconds | minutes | hours | days.",
                                  required=False,
                                  extra={"enum": ["seconds", "minutes", "hours", "days"]}),
                ],
            ),
            Tool(
                name="time_add",
                description="Shift an ISO 8601 timestamp by an integer amount of units.",
                fn=_time_add,
                parameters=[
                    ToolParameter("value", "string", "ISO 8601 timestamp."),
                    ToolParameter("amount", "integer", "Signed amount to add."),
                    ToolParameter("unit", "string",
                                  "seconds | minutes | hours | days | weeks.",
                                  required=False,
                                  extra={"enum": ["seconds", "minutes", "hours", "days", "weeks"]}),
                ],
            ),
            Tool(
                name="time_format",
                description="Reformat an ISO 8601 timestamp using a strftime pattern (e.g. '%d %b %Y').",
                fn=_time_format,
                parameters=[
                    ToolParameter("value", "string", "ISO 8601 timestamp to reformat."),
                    ToolParameter("fmt", "string", "strftime pattern, e.g. '%Y/%m/%d %H:%M'."),
                ],
            ),
            Tool(
                name="time_in_range",
                description="Return true if timestamp t falls within [start, end] (both inclusive).",
                fn=_time_in_range,
                parameters=[
                    ToolParameter("t", "string", "ISO 8601 timestamp to test."),
                    ToolParameter("start", "string", "ISO 8601 range start."),
                    ToolParameter("end", "string", "ISO 8601 range end."),
                ],
            ),
            Tool(
                name="time_floor",
                description="Floor an ISO 8601 timestamp to the nearest unit boundary.",
                fn=_time_floor,
                parameters=[
                    ToolParameter("value", "string", "ISO 8601 timestamp."),
                    ToolParameter("unit", "string",
                                  "minute | hour | day | month | year.",
                                  required=False,
                                  extra={"enum": ["minute", "hour", "day", "month", "year"]}),
                ],
            ),
        ],
        skills=[
            Skill(
                name="time_today",
                description="Return today's date in YYYY-MM-DD and the weekday name.",
                handler=_time_today,
                parameters=[
                    ToolParameter("timezone_name", "string", "IANA timezone.",
                                  required=False),
                ],
            ),
            Skill(
                name="time_since",
                description=(
                    "Return a human-readable relative time string for an ISO timestamp: "
                    "'3 hours ago', '2 days from now', etc."
                ),
                handler=_time_since,
                parameters=[
                    ToolParameter("value", "string", "ISO 8601 timestamp."),
                    ToolParameter("timezone_name", "string",
                                  "IANA timezone for 'now'. Default UTC.",
                                  required=False),
                ],
            ),
            Skill(
                name="schedule_info",
                description=(
                    "Return a rich schedule context for an ISO timestamp as JSON: "
                    "weekday name, ISO week number, quarter (1–4), day of year, "
                    "is_weekend flag, and timezone."
                ),
                handler=_schedule_info,
                parameters=[
                    ToolParameter("value", "string", "ISO 8601 timestamp."),
                    ToolParameter("timezone_name", "string",
                                  "IANA timezone to localise the timestamp.",
                                  required=False),
                ],
            ),
        ],
    )


__all__ = [
    "time_terr",
    # primitive fns (standalone-callable)
    "_now", "_parse_time", "_time_diff", "_time_add",
    "_time_format", "_time_in_range", "_time_floor",
    # compound skill fns
    "_time_today", "_time_since", "_schedule_info",
]
