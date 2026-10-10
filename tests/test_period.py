"""Tests for the collection-period rule (patristica/period.py)."""

from __future__ import annotations

from patristica.period import (
    AUTHOR_BORN_BEFORE,
    COMPOSED_BY,
    is_out_of_period,
    work_in_period,
)


class TestWorkInPeriod:
    def test_undated_work_is_included(self):
        assert work_in_period(None)

    def test_composition_boundary(self):
        assert work_in_period((1000, COMPOSED_BY))
        assert work_in_period((COMPOSED_BY, 1100))  # straddling: kept as hybrid
        assert not work_in_period((COMPOSED_BY + 1, 1100))

    def test_author_birth_year_decides_when_known(self):
        # Born before the cutoff: in scope even if writing after COMPOSED_BY
        assert work_in_period((1060, 1070), author_birth_year=AUTHOR_BORN_BEFORE - 1)
        # Born after the cutoff: out even if dated early
        assert not work_in_period((1030, 1040), author_birth_year=AUTHOR_BORN_BEFORE)


class TestIsOutOfPeriod:
    def test_flags_by_composition_date(self):
        assert not is_out_of_period(COMPOSED_BY, None)
        assert is_out_of_period(COMPOSED_BY + 1, None)

    def test_flags_by_range_start(self):
        assert not is_out_of_period(None, (900, 1200))
        assert is_out_of_period(None, (COMPOSED_BY + 1, 1200))

    def test_undated_is_not_flagged(self):
        assert not is_out_of_period(None, None)
