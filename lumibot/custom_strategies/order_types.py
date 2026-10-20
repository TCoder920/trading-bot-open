"""Session-aware order-type decision layer.

The ORB strategy expresses *intent* (e.g. "enter on a stop above the opening-range
high", "flatten now"). Alpaca's accepted order types depend on the current session:

* Regular hours (RTH): market / stop / limit are all accepted.
* Extended hours (pre-market, after-hours): ONLY ``limit`` orders with
  ``time_in_force=day`` and ``extended_hours=true`` are accepted. Market and stop
  orders are rejected by Alpaca.

This module converts a strategy *intent* into a concrete, Alpaca-valid order spec for
the given session. Outside RTH, stop/market intents are converted into **marketable
limit** orders: a limit priced far enough past the touch that it fills immediately,
emulating a market order while remaining extended-hours eligible.

Pure + dependency-light so it is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lumibot.custom_strategies.session import EXTENDED_SESSIONS, Session

# Intents the strategy can express.
INTENT_MARKET = "market"
INTENT_STOP = "stop"
INTENT_LIMIT = "limit"
INTENT_STOP_LIMIT = "stop_limit"

DEFAULT_MARKETABLE_OFFSET_PCT = 0.2  # 0.2% past the touch for marketable limits
DEFAULT_TICK_SIZE = 0.01


@dataclass
class OrderSpec:
    """Concrete, broker-ready order parameters."""

    order_type: str
    time_in_force: str = "day"
    extended_hours: bool = False
    limit_price: float | None = None
    stop_price: float | None = None
    converted_from: str | None = None  # original intent if it was rewritten
    notes: str | None = None
    diagnostics: dict = field(default_factory=dict)

    def to_payload_fields(self) -> dict:
        out: dict = {
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "extended_hours": self.extended_hours,
        }
        if self.limit_price is not None:
            out["limit_price"] = self.limit_price
        if self.stop_price is not None:
            out["stop_price"] = self.stop_price
        return out


def _round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return round(price, 4)
    return round(round(price / tick) * tick, 4)


def marketable_limit_price(side: str, reference_price: float, *, offset_pct: float,
                           tick_size: float = DEFAULT_TICK_SIZE) -> float:
    """Limit price that should fill immediately given a reference (last/ask/bid).

    Buys are priced *above* the reference, sells *below*, by ``offset_pct`` percent.
    """
    side = (side or "buy").lower()
    factor = offset_pct / 100.0
    if side == "buy":
        raw = reference_price * (1.0 + factor)
    else:
        raw = reference_price * (1.0 - factor)
    return _round_to_tick(raw, tick_size)


def resolve_order_type(
    *,
    side: str,
    session: str,
    intent: str,
    reference_price: float | None,
    stop_price: float | None = None,
    limit_price: float | None = None,
    config: dict | None = None,
) -> OrderSpec:
    """Resolve a strategy intent into an Alpaca-valid :class:`OrderSpec` for ``session``.

    ``reference_price`` is the current marketable reference (last trade / quote) used to
    build marketable limits when converting for extended hours. If it is missing while a
    conversion is required, a ``ValueError`` is raised rather than fabricating a price.
    """
    config = config or {}
    intent = (intent or INTENT_MARKET).lower()
    offset_pct = float(config.get("marketable_limit_offset_pct", DEFAULT_MARKETABLE_OFFSET_PCT))
    tick = float(config.get("tick_size", DEFAULT_TICK_SIZE))
    is_extended = session in EXTENDED_SESSIONS

    if not is_extended:
        # Regular hours (or a closed session that the caller already vetted): keep the
        # native intent. Closed sessions should be blocked upstream, not here.
        if intent == INTENT_MARKET:
            return OrderSpec(order_type="market", time_in_force="day", extended_hours=False)
        if intent == INTENT_STOP:
            if stop_price is None:
                raise ValueError("stop intent requires a stop_price")
            return OrderSpec(order_type="stop", time_in_force="day", extended_hours=False,
                             stop_price=stop_price)
        if intent == INTENT_LIMIT:
            if limit_price is None:
                raise ValueError("limit intent requires a limit_price")
            return OrderSpec(order_type="limit", time_in_force="day", extended_hours=False,
                             limit_price=limit_price)
        if intent == INTENT_STOP_LIMIT:
            if stop_price is None or limit_price is None:
                raise ValueError("stop_limit intent requires stop_price and limit_price")
            return OrderSpec(order_type="stop_limit", time_in_force="day", extended_hours=False,
                             stop_price=stop_price, limit_price=limit_price)
        raise ValueError(f"Unknown order intent: {intent}")

    # ── Extended hours: everything becomes a marketable limit ────────────
    if intent == INTENT_LIMIT and limit_price is not None:
        # Respect an explicit limit price but still tag it extended-hours eligible.
        return OrderSpec(order_type="limit", time_in_force="day", extended_hours=True,
                         limit_price=_round_to_tick(limit_price, tick),
                         converted_from=None,
                         notes="extended-hours limit")

    ref = reference_price
    if ref is None and intent == INTENT_STOP:
        # A stop entry naturally triggers at the stop level; use it as the reference so
        # we do not fabricate a price out of thin air.
        ref = stop_price
    if ref is None:
        raise ValueError(
            "extended-hours order requires a reference price to build a marketable limit"
        )
    lp = marketable_limit_price(side, ref, offset_pct=offset_pct, tick_size=tick)
    return OrderSpec(
        order_type="limit",
        time_in_force="day",
        extended_hours=True,
        limit_price=lp,
        converted_from=intent if intent != INTENT_LIMIT else None,
        notes=f"{intent}->marketable_limit (offset {offset_pct}% of {ref})",
        diagnostics={"reference_price": ref, "offset_pct": offset_pct,
                     "session": session},
    )


def session_allows_intent(session: str, intent: str) -> bool:
    """Whether the *native* intent is directly accepted by Alpaca in ``session``.

    (Extended-hours stop/market intents are not directly accepted, hence conversion.)
    """
    if session == Session.CLOSED:
        return False
    if session in EXTENDED_SESSIONS:
        return intent == INTENT_LIMIT
    return True
