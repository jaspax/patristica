"""
Usage samples and the night's budget for the nightly machine-translation agent (#425).

The nightly agent (``.claude/skills/nightly-translate``) runs on the Claude
subscription, which it shares with the owner's daytime work. This script gives
it numbers; it decides nothing (``docs/translation-backends.md``):

- ``sample`` probes the subscription's usage windows with one tiny local
  Claude request and appends it to ``logs/usage.jsonl`` (gitignored), tagged
  ``start`` / ``end`` for the night or ``before`` / ``after`` around a work.
- ``plan`` reads that log and prints the night's projection as JSON: the
  deadline, both windows, the owner's measured daytime use, the night's weekly
  allowance and what is left of it, the usage and time per 1k source
  characters measured from earlier works, and, with ``--chars N``, whether a
  work of N characters is projected to fit.

Usage::

    python -m scripts.nightly_budget sample --tag start
    python -m scripts.nightly_budget sample --tag before --work csel/… --chars 8052
    python -m scripts.nightly_budget plan [--chars 8052]

Utilization is a fraction (0.52 = 52 %), as the CLI reports it.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOG = Path("logs/usage.jsonl")
TZ = ZoneInfo("America/Chicago")
DEADLINE = (6, 30)           # local time the night's work must be finished by
MARGIN = 0.05                # of the 7-day window, never spent at night
FIVE_HOUR_MARGIN = 0.05      # of the 5-hour window, left for the owner
DEFAULT_DAYTIME = 0.10       # of the 7-day window per day, until measured
TAGS = ("start", "end", "before", "after")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def probe() -> dict:
    """The subscription's usage windows now, from one tiny local Claude request."""
    from pydantic import BaseModel

    from scripts.embed_eval.translate import Clients

    class Ok(BaseModel):
        ok: bool

    _, usage = Clients().call("local-haiku", "Answer with ok: true.", "ok?", Ok)
    return usage.get("limits") or {}


def sample(tag: str, limits: dict, at: datetime, work: str | None = None,
           chars: int | None = None) -> dict:
    row: dict = {"time": at.isoformat(timespec="seconds"), "tag": tag}
    for window in ("five_hour", "seven_day"):
        w = limits.get(window) or {}
        row[window] = {"utilization": w.get("utilization"), "resets_at": w.get("resets_at")}
    row["overage"] = bool(limits.get("overage"))
    if work:
        row["work"] = work
    if chars is not None:
        row["chars"] = chars
    return row


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _t(row: dict) -> datetime:
    return datetime.fromisoformat(row["time"])


def _u(row: dict, window: str) -> float | None:
    return (row.get(window) or {}).get("utilization")


def _same_window(a: dict, b: dict, window: str) -> bool:
    """True when no reset of *window* happened between samples *a* and *b*."""
    ra, rb = (a.get(window) or {}).get("resets_at"), (b.get(window) or {}).get("resets_at")
    return ra is not None and ra == rb


def deadline_after(at: datetime) -> datetime:
    local = at.astimezone(TZ)
    d = local.replace(hour=DEADLINE[0], minute=DEADLINE[1], second=0, microsecond=0)
    if d <= local:
        d += timedelta(days=1)
    return d.astimezone(timezone.utc)


def daytime_per_day(rows: list[dict]) -> float | None:
    """The owner's 7-day usage per day between nights: each night's ``end`` to
    the next ``start``, skipping gaps that span a weekly reset (median)."""
    rates = []
    last_end = None
    for row in rows:
        if row.get("tag") == "end":
            last_end = row
        elif row.get("tag") == "start" and last_end is not None:
            a, b = _u(last_end, "seven_day"), _u(row, "seven_day")
            days = (_t(row) - _t(last_end)).total_seconds() / 86400
            if a is not None and b is not None and days > 0.1 and \
                    _same_window(last_end, row, "seven_day"):
                rates.append(max(0.0, b - a) / days)
            last_end = None
    return statistics.median(rates) if rates else None


def work_rates(rows: list[dict]) -> dict:
    """Usage and hours per 1k source characters, from ``before``/``after`` pairs
    of one work within one window (pooled over all such works)."""
    d5 = d7 = c5 = c7 = hours = chars_t = 0.0
    before: dict[str, dict] = {}
    for row in rows:
        work = row.get("work")
        if row.get("tag") == "before" and work:
            before[work] = row
        elif row.get("tag") == "after" and work in before:
            b = before.pop(work)
            chars = b.get("chars") or row.get("chars")
            if not chars:
                continue
            hours += (_t(row) - _t(b)).total_seconds() / 3600
            chars_t += chars
            for window, acc in (("five_hour", "5"), ("seven_day", "7")):
                x, y = _u(b, window), _u(row, window)
                if x is None or y is None or not _same_window(b, row, window):
                    continue
                if acc == "5":
                    d5 += max(0.0, y - x)
                    c5 += chars
                else:
                    d7 += max(0.0, y - x)
                    c7 += chars
    return {
        "five_hour_per_1k": d5 / c5 * 1000 if c5 else None,
        "seven_day_per_1k": d7 / c7 * 1000 if c7 else None,
        "hours_per_1k": hours / chars_t * 1000 if chars_t else None,
        "measured_chars": int(max(c5, c7, chars_t)),
    }


def plan(rows: list[dict], at: datetime, chars: int | None = None) -> dict:
    """The night's projection from the usage log (the latest sample is "now")."""
    if not rows:
        raise SystemExit("no usage samples: run `sample --tag start` first")
    latest = rows[-1]
    starts = [r for r in rows if r.get("tag") == "start"]
    tonight = starts[-1] if starts else latest
    deadline = deadline_after(_t(tonight))
    hours_left = max(0.0, (deadline - at).total_seconds() / 3600)

    u7 = _u(latest, "seven_day") or 0.0
    u5 = _u(latest, "five_hour") or 0.0
    r7 = (latest.get("seven_day") or {}).get("resets_at")
    r5 = (latest.get("five_hour") or {}).get("resets_at")
    days_to_r7 = max(0.0, (r7 - at.timestamp()) / 86400) if r7 else 7.0
    hours_to_r5 = max(0.0, (r5 - at.timestamp()) / 3600) if r5 else 5.0

    measured = daytime_per_day(rows)
    daytime = measured if measured is not None else DEFAULT_DAYTIME
    # Nights from tonight to the weekly reset, and the daytime between them.
    nights = max(1, math.ceil(days_to_r7))
    daytime_days = max(0.0, days_to_r7 - hours_left / 24)
    allowance = max(0.0, (1.0 - (_u(tonight, "seven_day") or u7) - daytime * daytime_days
                          - MARGIN) / nights)
    spent = max(0.0, u7 - (_u(tonight, "seven_day") or u7)) \
        if _same_window(tonight, latest, "seven_day") else None
    remaining = max(0.0, allowance - spent) if spent is not None else None

    rates = work_rates(rows)
    out = {
        "now": at.isoformat(timespec="minutes"),
        "deadline": deadline.astimezone(TZ).isoformat(timespec="minutes"),
        "hours_left": round(hours_left, 2),
        "five_hour": {"utilization": u5, "hours_to_reset": round(hours_to_r5, 2),
                      "headroom": round(max(0.0, 1.0 - FIVE_HOUR_MARGIN - u5), 3)},
        "seven_day": {"utilization": u7, "days_to_reset": round(days_to_r7, 2)},
        "using_extra_usage": bool(latest.get("overage")),
        "daytime_per_day": round(daytime, 3),
        "daytime_source": "measured" if measured is not None else "default",
        "nights_to_weekly_reset": nights,
        "weekly_allowance_tonight": round(allowance, 3),
        "spent_tonight": None if spent is None else round(spent, 3),
        "remaining_tonight": None if remaining is None else round(remaining, 3),
        "rates": rates,
    }
    if chars is not None:
        out["work"] = project(out, chars)
    return out


def project(p: dict, chars: int) -> dict:
    """Whether a work of *chars* source characters is projected to fit tonight."""
    rates = p["rates"]
    k = chars / 1000
    reasons = []
    if p["using_extra_usage"]:
        reasons.append("the subscription is using extra usage")
    need7 = rates["seven_day_per_1k"] * k if rates["seven_day_per_1k"] is not None else None
    need5 = rates["five_hour_per_1k"] * k if rates["five_hour_per_1k"] is not None else None
    hours = rates["hours_per_1k"] * k if rates["hours_per_1k"] is not None else None
    remaining = p["remaining_tonight"]
    if need7 is not None and remaining is not None and need7 > remaining:
        reasons.append(f"7-day: needs {need7:.1%}, {remaining:.1%} left of tonight's allowance")
    if need5 is not None:
        # Spread over the run; the window refills only after its reset.
        before_reset = need5 if hours is None or hours <= p["five_hour"]["hours_to_reset"] \
            else need5 * p["five_hour"]["hours_to_reset"] / hours
        if before_reset > p["five_hour"]["headroom"]:
            reasons.append(f"5-hour: needs {before_reset:.1%} before its reset, "
                           f"{p['five_hour']['headroom']:.1%} headroom")
    if hours is not None and hours > p["hours_left"]:
        reasons.append(f"time: about {hours:.1f} h, {p['hours_left']:.1f} h to the deadline")
    unknown = [n for n, v in (("7-day rate", need7), ("5-hour rate", need5),
                              ("duration", hours)) if v is None]
    return {
        "chars": chars,
        "needs_seven_day": None if need7 is None else round(need7, 3),
        "needs_five_hour": None if need5 is None else round(need5, 3),
        "hours": None if hours is None else round(hours, 2),
        "fits": not reasons and not unknown,
        "reasons": reasons,
        "unknown": unknown,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", type=Path, default=LOG)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="probe usage and append it to the log")
    s.add_argument("--tag", choices=TAGS, required=True)
    s.add_argument("--work")
    s.add_argument("--chars", type=int)
    q = sub.add_parser("plan", help="the night's projection, as JSON")
    q.add_argument("--chars", type=int, help="also project a work of N source characters")
    args = p.parse_args()
    if args.cmd == "sample":
        row = sample(args.tag, probe(), now_utc(), args.work, args.chars)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row))
    else:
        print(json.dumps(plan(read_log(args.log), now_utc(), args.chars), indent=1))


if __name__ == "__main__":
    main()
