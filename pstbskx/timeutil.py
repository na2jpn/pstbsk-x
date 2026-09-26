from __future__ import annotations
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9), name="JST")


def ensure_utc(dt: datetime | None = None) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_clock(dt_utc: datetime | None = None, show_jst: bool = True, colon_visible: bool = True) -> str:
    utc = ensure_utc(dt_utc)
    sep = ":" if colon_visible else " "
    utc_s = f"UTC {utc:%Y-%m-%d %H}{sep}{utc:%M}"
    if not show_jst:
        return utc_s
    jst = utc.astimezone(JST)
    return f"JST {jst:%Y-%m-%d %H}{sep}{jst:%M}   {utc_s}"
