#!/usr/bin/env python3.12
"""Wall Street trading-session and recency-window helpers for BoltNews.

All times are America/New_York.  The goal is to stop pre/post-market jobs
from mixing yesterday's rally with today's selloff (or vice versa).  This is a
small deterministic calendar; it covers regular US equity market holidays and
observed dates without adding a dependency on pandas-market-calendars.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _observed_fixed(year: int, month: int, day: int) -> date:
    d = date(year, month, day)
    if d.weekday() == 5:  # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        d = date(year, 12, 31)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    # Anonymous Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed(year, 1, 1),    # New Year's Day
        _nth_weekday(year, 1, 0, 3),    # MLK Day
        _nth_weekday(year, 2, 0, 3),    # Presidents' Day
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),      # Memorial Day
        _observed_fixed(year, 6, 19),   # Juneteenth
        _observed_fixed(year, 7, 4),    # Independence Day
        _nth_weekday(year, 9, 0, 1),    # Labor Day
        _nth_weekday(year, 11, 3, 4),   # Thanksgiving
        _observed_fixed(year, 12, 25),  # Christmas
    }
    # NYSE was closed on Jan 9, 2025 for President Carter's funeral; keep one-offs explicit.
    if year == 2025:
        holidays.add(date(2025, 1, 9))
    return holidays


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in market_holidays(d.year)


def previous_trading_day(d: date) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def next_trading_day(d: date) -> date:
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def session_window(target_date: str | date, mode: str) -> dict[str, object]:
    """Return the article-acceptance window for a BoltNews run.

    pre-market: previous trading day's 4:00 PM close through 6:00 AM ET.
    post-market: same trading day's 9:30 AM open through 6:00 PM ET.
    weekend: Friday/previous trading day's 4:00 PM through Sunday 10:00 AM ET.
    """
    d = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    if mode == "pre-market":
        prev = previous_trading_day(d)
        start = datetime.combine(prev, time(16, 0), tzinfo=NY)
        end = datetime.combine(d, time(6, 0), tzinfo=NY)
        label = "overnight session"
    elif mode == "post-market":
        if not is_trading_day(d):
            raise ValueError(f"post-market run date is not a US trading day: {d}")
        start = datetime.combine(d, time(9, 30), tzinfo=NY)
        end = datetime.combine(d, time(18, 0), tzinfo=NY)
        label = "regular trading day + immediate after-hours"
    elif mode == "weekend":
        prev = d
        while prev.weekday() != 4 or not is_trading_day(prev):
            prev = previous_trading_day(prev)
        start = datetime.combine(prev, time(16, 0), tzinfo=NY)
        # Weekend job may run Sunday morning; keep end deterministic from target date.
        end = datetime.combine(d, time(10, 0), tzinfo=NY)
        label = "weekend / week-ahead window"
    else:
        raise ValueError(f"unknown mode: {mode}")
    hours = round((end - start).total_seconds() / 3600, 2)
    return {
        "mode": mode,
        "label": label,
        "window_start_iso": start.isoformat(),
        "window_end_iso": end.isoformat(),
        "hours": hours,
        "timezone": "America/New_York",
        "require_article_timestamp": True,
        "reject_if_timestamp_missing": True,
        "reject_if_outside_window": True,
        "calendar": "NYSE-like US equity calendar with weekends and major Wall Street holidays",
        "target_is_trading_day": is_trading_day(d),
        "previous_trading_day": previous_trading_day(d).isoformat() if d else None,
    }


def parse_article_ts(value: object) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    # Preserve timezone offsets. Avoid slicing off '-04:00'.
    raw = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%B %d, %Y %I:%M %p"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(NY)


def article_timestamp(article: dict) -> datetime | None:
    for key in ("published_at", "fetched_at", "date", "timestamp"):
        ts = parse_article_ts(article.get(key))
        if ts is not None:
            return ts
    return None


def article_in_window(article: dict, window: dict[str, object]) -> tuple[bool, str, float | None]:
    ts = article_timestamp(article)
    if ts is None:
        return False, "missing_timestamp", None
    start = datetime.fromisoformat(str(window["window_start_iso"]))
    end = datetime.fromisoformat(str(window["window_end_iso"]))
    if ts < start:
        age = (end - ts).total_seconds() / 3600
        return False, "before_session_window", age
    if ts > end:
        return False, "after_session_window", None
    age = (end - ts).total_seconds() / 3600
    return True, "inside_session_window", age


if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--mode", required=True, choices=["pre-market", "post-market", "weekend"])
    args = parser.parse_args()
    print(json.dumps(session_window(args.date, args.mode), indent=2))
