"""Time / date capability domain.

Always-safe stdlib-only tools for inspecting and formatting the current moment
and arbitrary timestamps. The model frequently needs ``now`` and ``time_diff``
to ground its reasoning in real time — having these built in saves every
agent author from re-implementing them.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter


def _parse_iso(s: str) -> datetime:
    # datetime.fromisoformat accepts most ISO 8601 forms in 3.11+.
    return datetime.fromisoformat(s)


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


def time_terr() -> Terr:
    """Build the ``time`` Terr.

    Tools:
        now(timezone="UTC", fmt="iso") → current timestamp
        parse_time(value, fmt="iso")   → normalize to ISO 8601
        time_diff(start, end, unit)    → arithmetic between two ISO timestamps
        time_add(value, amount, unit)  → ISO timestamp shifted by a delta
    """
    return Terr(
        name="time",
        description="Date/time inspection and arithmetic.",
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
        ],
    )


async def _time_today(timezone_name: str = "UTC") -> str:
    if timezone_name.upper() == "UTC":
        tz = UTC
    else:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(timezone_name)
    dt = datetime.now(tz)
    weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.weekday()]
    return f"{dt.strftime('%Y-%m-%d')} ({weekday})"
