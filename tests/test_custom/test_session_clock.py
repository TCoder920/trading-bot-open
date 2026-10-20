"""Tests for the single ET time source + session classifier."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from lumibot.custom_strategies.session import (
    EXTENDED_SESSIONS,
    Session,
    SessionClock,
    SessionWindows,
)

ET = ZoneInfo("America/New_York")


def _clock_at(dt: datetime) -> SessionClock:
    return SessionClock(now_provider=lambda: dt)


class TestSessionClassification:
    def test_pre_market(self):
        clk = _clock_at(datetime(2026, 6, 15, 5, 0, tzinfo=ET))  # Monday 05:00 ET
        assert clk.session() == Session.PRE_MARKET
        assert clk.is_extended_hours()
        assert not clk.is_regular_hours()

    def test_regular_hours(self):
        clk = _clock_at(datetime(2026, 6, 15, 10, 0, tzinfo=ET))
        assert clk.session() == Session.REGULAR
        assert clk.is_regular_hours()
        assert not clk.is_extended_hours()

    def test_after_hours(self):
        clk = _clock_at(datetime(2026, 6, 15, 17, 0, tzinfo=ET))
        assert clk.session() == Session.AFTER_HOURS
        assert clk.is_extended_hours()

    def test_closed_overnight(self):
        clk = _clock_at(datetime(2026, 6, 15, 22, 0, tzinfo=ET))
        assert clk.session() == Session.CLOSED
        assert not clk.is_tradeable()

    def test_weekend_closed(self):
        clk = _clock_at(datetime(2026, 6, 13, 10, 0, tzinfo=ET))  # Saturday
        assert clk.session() == Session.CLOSED

    def test_boundaries(self):
        # 09:30 exactly is RTH, 16:00 exactly is after-hours, 04:00 is pre-market.
        assert _clock_at(datetime(2026, 6, 15, 9, 30, tzinfo=ET)).session() == Session.REGULAR
        assert _clock_at(datetime(2026, 6, 15, 16, 0, tzinfo=ET)).session() == Session.AFTER_HOURS
        assert _clock_at(datetime(2026, 6, 15, 4, 0, tzinfo=ET)).session() == Session.PRE_MARKET
        assert _clock_at(datetime(2026, 6, 15, 3, 59, tzinfo=ET)).session() == Session.CLOSED


class TestSessionDay:
    def test_session_day_is_et_date(self):
        # 23:00 UTC on 2026-06-15 is 19:00 ET same day (after-hours).
        utc = datetime(2026, 6, 15, 23, 0, tzinfo=ZoneInfo("UTC"))
        clk = _clock_at(utc)
        assert clk.session() == Session.AFTER_HOURS
        assert clk.session_day() == date(2026, 6, 15)

    def test_utc_naive_assumed_utc(self):
        clk = SessionClock(now_provider=lambda: datetime(2026, 6, 15, 14, 0))  # naive -> UTC -> 10:00 ET
        assert clk.session() == Session.REGULAR


class TestWindowsFromConfig:
    def test_custom_windows(self):
        windows = SessionWindows.from_config({
            "premarket_session_start": "07:00",
            "opening_range_start": "09:30",
            "rth_end": "16:00",
            "postmarket_session_end": "18:00",
        })
        clk = SessionClock(windows, now_provider=lambda: datetime(2026, 6, 15, 6, 30, tzinfo=ET))
        assert clk.session() == Session.CLOSED  # before 07:00 pre-market start
        clk2 = SessionClock(windows, now_provider=lambda: datetime(2026, 6, 15, 19, 0, tzinfo=ET))
        assert clk2.session() == Session.CLOSED  # after 18:00 post-market end


def test_extended_sessions_constant():
    assert Session.PRE_MARKET in EXTENDED_SESSIONS
    assert Session.AFTER_HOURS in EXTENDED_SESSIONS
    assert Session.REGULAR not in EXTENDED_SESSIONS
