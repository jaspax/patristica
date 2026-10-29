"""Tests for the nightly machine-translation budget (scripts.nightly_budget, #425)."""

from __future__ import annotations

from datetime import datetime, timezone

from scripts import nightly_budget as nb

R7 = int(datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc).timestamp())  # weekly reset
R5 = int(datetime(2026, 10, 30, 7, 0, tzinfo=timezone.utc).timestamp())  # 5-hour reset


def row(tag: str, when: str, u7: float, u5: float = 0.1, r5: int = R5,
        r7: int = R7, **extra) -> dict:
    at = datetime.fromisoformat(when)
    return {**nb.sample(tag, {"five_hour": {"utilization": u5, "resets_at": r5},
                              "seven_day": {"utilization": u7, "resets_at": r7}}, at),
            **extra}


def test_deadline_is_the_next_0630_chicago():
    # 22:15 CDT on Oct 29 = 03:15 UTC Oct 30; deadline 06:30 CDT Oct 30 = 11:30 UTC
    at = datetime(2026, 10, 30, 3, 15, tzinfo=timezone.utc)
    assert nb.deadline_after(at) == datetime(2026, 10, 30, 11, 30, tzinfo=timezone.utc)
    after = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    assert nb.deadline_after(after).day == 31


def test_daytime_use_is_measured_between_nights_and_skips_a_weekly_reset():
    rows = [
        row("end", "2026-10-28T11:00:00+00:00", 0.40),
        row("start", "2026-10-29T03:00:00+00:00", 0.48),          # 0.08 in 2/3 day
        row("end", "2026-10-29T11:00:00+00:00", 0.55),
        row("start", "2026-10-30T03:00:00+00:00", 0.05, r7=R7 + 7 * 86400),  # reset: skipped
    ]
    assert abs(nb.daytime_per_day(rows) - 0.12) < 1e-9
    assert nb.daytime_per_day(rows[:1]) is None


def test_work_rates_pool_before_after_pairs():
    rows = [
        row("before", "2026-10-30T03:20:00+00:00", 0.50, 0.10, work="a", chars=10_000),
        row("after", "2026-10-30T03:50:00+00:00", 0.52, 0.16, work="a"),
        row("before", "2026-10-30T04:00:00+00:00", 0.52, 0.16, work="b", chars=30_000),
        row("after", "2026-10-30T05:00:00+00:00", 0.58, 0.34, work="b"),
    ]
    r = nb.work_rates(rows)
    assert abs(r["seven_day_per_1k"] - 0.08 / 40) < 1e-9
    assert abs(r["five_hour_per_1k"] - 0.24 / 40) < 1e-9
    assert abs(r["hours_per_1k"] - 1.5 / 40) < 1e-9


def test_plan_allowance_spent_and_projection():
    rows = [
        row("end", "2026-10-29T11:00:00+00:00", 0.45),
        row("start", "2026-10-30T03:15:00+00:00", 0.50),     # daytime 0.05 in ~0.68 day
        row("before", "2026-10-30T03:20:00+00:00", 0.50, 0.10, work="a", chars=10_000),
        row("after", "2026-10-30T03:50:00+00:00", 0.52, 0.16, work="a"),
    ]
    at = datetime(2026, 10, 30, 3, 50, tzinfo=timezone.utc)
    p = nb.plan(rows, at)
    assert p["daytime_source"] == "measured"
    assert p["nights_to_weekly_reset"] == 5                  # ~4.2 days to the reset
    assert p["spent_tonight"] == 0.02
    assert 0 < p["weekly_allowance_tonight"] < 0.1
    assert p["deadline"].startswith("2026-10-30T06:30")

    small = nb.project(p, 5_000)
    assert small["fits"] and small["needs_seven_day"] == 0.01
    huge = nb.project(p, 2_000_000)
    assert not huge["fits"]
    assert any(r.startswith("7-day") for r in huge["reasons"])
    assert any(r.startswith("time") for r in huge["reasons"])


def test_projection_without_history_is_unknown_and_overage_stops():
    rows = [row("start", "2026-10-30T03:15:00+00:00", 0.50)]
    p = nb.plan(rows, datetime(2026, 10, 30, 3, 15, tzinfo=timezone.utc))
    assert p["daytime_source"] == "default"
    w = nb.project(p, 5_000)
    assert not w["fits"] and set(w["unknown"]) == {"7-day rate", "5-hour rate", "duration"}
    rows[0]["overage"] = True
    p = nb.plan(rows, datetime(2026, 10, 30, 3, 15, tzinfo=timezone.utc))
    assert "the subscription is using extra usage" in nb.project(p, 5_000)["reasons"]
