"""Turn the raw hourly buckets kept in ``data.json`` into chart-ready series.

Buckets are stored in UTC; the dashboard asks for a timezone offset so the
hour-of-day histogram lines up with the user's clock rather than with UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import storage

HOURS_IN_DAY = 24


def _parse_hour(key: str) -> datetime | None:
    try:
        return datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def timeline(buckets: dict[str, int], hours: int, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Continuous hourly series ending at the current hour, gaps filled with 0."""
    now = (now or datetime.now(tz=timezone.utc)).replace(minute=0, second=0, microsecond=0)
    series = []
    for offset in range(hours - 1, -1, -1):
        moment = now - timedelta(hours=offset)
        series.append(
            {
                "hour": moment.isoformat(timespec="minutes"),
                "count": int(buckets.get(storage.hour_key(moment), 0)),
            }
        )
    return series


def hour_of_day(buckets: dict[str, int], *, tz_offset_minutes: int = 0, days: int = 7) -> list[int]:
    """Histogram over the 24 hours of a day, shifted into the caller's timezone."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    shift = timedelta(minutes=tz_offset_minutes)
    histogram = [0] * HOURS_IN_DAY
    for key, count in buckets.items():
        moment = _parse_hour(key)
        if moment is None or moment < cutoff:
            continue
        histogram[(moment + shift).hour] += int(count)
    return histogram


def summarize(record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Headline numbers shown on the card and at the top of the detail view."""
    stats = storage.get_stats(record)
    found = stats["found_by_hour"]
    now = now or datetime.now(tz=timezone.utc)

    last_24h = sum(entry["count"] for entry in timeline(found, 24, now=now))
    last_hour = int(found.get(storage.hour_key(now), 0))
    checks = int(stats["checks"])

    return {
        "found_total": int(stats["found_total"]),
        "found_last_hour": last_hour,
        "found_last_24h": last_24h,
        "checks": checks,
        "errors": int(stats["errors"]),
        "error_rate": round(stats["errors"] / checks, 4) if checks else 0.0,
        "last_found_at": stats["last_found_at"],
        # Average per active hour is more honest than dividing by wall-clock time:
        # a URL that was stopped overnight should not look like it went quiet.
        "found_per_hour": round(
            int(stats["found_total"]) / max(len(found), 1),
            2,
        ),
    }


def detail(record: dict[str, Any], *, tz_offset_minutes: int = 0, hours: int = 24) -> dict[str, Any]:
    stats = storage.get_stats(record)
    return {
        "summary": summarize(record),
        "found_timeline": timeline(stats["found_by_hour"], hours),
        "listed_by_hour_of_day": hour_of_day(stats["listed_by_hour"], tz_offset_minutes=tz_offset_minutes),
        "found_by_hour_of_day": hour_of_day(stats["found_by_hour"], tz_offset_minutes=tz_offset_minutes),
        "timeline_hours": hours,
    }
