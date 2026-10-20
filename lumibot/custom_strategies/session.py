"""Single source of truth for trading-session time.

Everything that reasons about "what time is it / which session are we in" should go
through :class:`SessionClock`. This guarantees the strategy, the autonomous runner,
the risk ledger, and the order-type decision layer all agree on:

* one timezone (America/New_York), and
* one definition of the trading "session day".

The module is intentionally dependency-light (stdlib only) so it can be unit tested
without Lumibot, FastAPI, or a market-data provider.

NO-FABRICATION NOTE: this module only reasons about *time*. It never invents market
data. Whether bars exist for a given session is a data-layer concern, handled honestly
elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Default US-equity session windows (ET). Overnight (20:00-04:00) is intentionally
# out of scope for this bot and is reported as CLOSED.
DEFAULT_PREMARKET_START = time(4, 0)
DEFAULT_RTH_START = time(9, 30)
DEFAULT_RTH_END = time(16, 0)
DEFAULT_AFTERHOURS_END = time(20, 0)


class Session:
    """Named trading sessions."""

    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"


EXTENDED_SESSIONS = frozenset({Session.PRE_MARKET, Session.AFTER_HOURS})
TRADEABLE_SESSIONS = frozenset({Session.PRE_MARKET, Session.REGULAR, Session.AFTER_HOURS})


def _coerce_time(value: str | time | None, default: time) -> time:
    if value is None:
        return default
    if isinstance(value, time):
        return value
    return datetime.strptime(str(value), "%H:%M").time()


@dataclass(frozen=True)
class SessionWindows:
    """ET session boundaries. Immutable so they can be shared safely across threads."""

    premarket_start: time = DEFAULT_PREMARKET_START
    rth_start: time = DEFAULT_RTH_START
    rth_end: time = DEFAULT_RTH_END
    afterhours_end: time = DEFAULT_AFTERHOURS_END

    @classmethod
    def from_config(cls, cfg: dict | None) -> "SessionWindows":
        cfg = cfg or {}
        return cls(
            premarket_start=_coerce_time(cfg.get("premarket_session_start"), DEFAULT_PREMARKET_START),
            rth_start=_coerce_time(cfg.get("opening_range_start"), DEFAULT_RTH_START),
            rth_end=_coerce_time(cfg.get("rth_end") or cfg.get("regular_session_end"), DEFAULT_RTH_END),
            afterhours_end=_coerce_time(cfg.get("postmarket_session_end"), DEFAULT_AFTERHOURS_END),
        )


class SessionClock:
    """Wall-clock + session classifier anchored to America/New_York.

    Parameters
    ----------
    windows:
        Optional :class:`SessionWindows`. Defaults to the standard US-equity windows.
    now_provider:
        Optional callable returning a timezone-aware (or naive-UTC-assumed) ``datetime``.
        Inject a fake clock in tests; defaults to ``datetime.now(ET)``.
    """

    def __init__(self, windows: SessionWindows | None = None, *, now_provider=None):
        self.windows = windows or SessionWindows()
        self._now_provider = now_provider

    # ── time ────────────────────────────────────────────────────────────
    def now(self) -> datetime:
        """Current time localized to ET."""
        if self._now_provider is not None:
            dt = self._now_provider()
        else:
            dt = datetime.now(ET)
        return self.to_et(dt)

    @staticmethod
    def to_et(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            # Assume naive datetimes are UTC (matches DB timestamps), then convert.
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET)

    # ── session classification ───────────────────────────────────────────
    def session(self, dt: datetime | None = None) -> str:
        et = self.now() if dt is None else self.to_et(dt)
        if et.weekday() >= 5:  # Saturday/Sunday
            return Session.CLOSED
        t = et.time()
        w = self.windows
        if w.premarket_start <= t < w.rth_start:
            return Session.PRE_MARKET
        if w.rth_start <= t < w.rth_end:
            return Session.REGULAR
        if w.rth_end <= t < w.afterhours_end:
            return Session.AFTER_HOURS
        return Session.CLOSED

    def is_extended_hours(self, dt: datetime | None = None) -> bool:
        return self.session(dt) in EXTENDED_SESSIONS

    def is_regular_hours(self, dt: datetime | None = None) -> bool:
        return self.session(dt) == Session.REGULAR

    def is_tradeable(self, dt: datetime | None = None) -> bool:
        return self.session(dt) in TRADEABLE_SESSIONS

    # ── session day ───────────────────────────────────────────────────────
    def session_day(self, dt: datetime | None = None) -> date:
        """The ET calendar date that owns the current session.

        Pre-market (04:00) through after-hours (20:00) of a given ET date all share
        one session day. This is the boundary the risk ledger resets on.
        """
        et = self.now() if dt is None else self.to_et(dt)
        return et.date()

    def session_day_str(self, dt: datetime | None = None) -> str:
        return self.session_day(dt).isoformat()
