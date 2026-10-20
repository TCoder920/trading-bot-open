"""Pre-execution risk control layer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from lumibot.custom_strategies.session import SessionClock, SessionWindows
from lumibot.custom_config.settings import get_config

logger = logging.getLogger(__name__)


def _et_session_day() -> date:
    """Current trading day as an ET session date (see SessionClock.session_day)."""
    return SessionClock().session_day()


@dataclass
class DailyLedger:
    """Tracks intra-day trading activity for risk enforcement.

    The trading "day" is the ET session date (pre-market 04:00 through after-hours
    20:00 of the same ET calendar date), NOT the host machine's local ``date.today()``.
    This keeps the daily-loss limit and trade caps aligned with the market sessions the
    bot actually trades, including extended hours. See
    ``docs/development/EXTENDED_HOURS_AUTONOMOUS_TRADING.md`` for the boundary definition.
    """

    trade_date: date = field(default_factory=_et_session_day)
    trade_count: int = 0
    realised_loss: float = 0.0
    open_positions: int = 0

    def reset_if_new_day(self, clock: SessionClock | None = None) -> bool:
        """Reset counters when the ET session day rolls over. Returns True if reset."""
        today = (clock or SessionClock()).session_day()
        if self.trade_date != today:
            self.trade_date = today
            self.trade_count = 0
            self.realised_loss = 0.0
            return True
        return False


class RiskEngine:
    def __init__(self, config: dict | None = None, *, clock: SessionClock | None = None):
        self._config = config or get_config()
        self._limits = self._config.get("risk_limits", {})
        orb_cfg = self._config.get("stocks_in_play_orb_v1", {})
        self._clock = clock or SessionClock(SessionWindows.from_config(orb_cfg))
        self._ledger = DailyLedger(trade_date=self._clock.session_day())
        self._kill_switch_active = False
        self._kill_switch_reasons: list[str] = []

    @property
    def max_dollars_per_trade(self) -> float:
        return float(self._limits.get("max_dollars_per_trade", 100))

    @property
    def max_loss_per_trade(self) -> float:
        return float(self._limits.get("max_loss_per_trade", 25))

    @property
    def max_daily_loss(self) -> float:
        return float(self._limits.get("max_daily_loss", 200))

    @property
    def max_trades_per_day(self) -> int:
        return int(self._limits.get("max_trades_per_day", 10))

    @property
    def max_open_positions(self) -> int:
        return int(self._limits.get("max_open_positions", 5))

    @property
    def assigned_capital(self) -> float | None:
        raw = self._config.get("paper_trading", {}).get("assigned_capital")
        return float(raw) if raw is not None else None

    @property
    def use_assigned_capital_limit(self) -> bool:
        return bool(self._config.get("paper_trading", {}).get("use_assigned_capital_limit", False))

    @property
    def assigned_capital_limit_active(self) -> bool:
        return self.use_assigned_capital_limit and self.assigned_capital is not None and self.assigned_capital > 0

    @property
    def strategy_capital_limit(self) -> float | None:
        if not self.assigned_capital_limit_active:
            return None
        return max(0.0, self.assigned_capital)

    @property
    def effective_max_daily_loss(self) -> float:
        if self.strategy_capital_limit is None:
            return self.max_daily_loss
        return min(self.max_daily_loss, self.strategy_capital_limit)

    def max_stock_order_notional(self) -> float | None:
        return self.max_order_notional("stocks")

    def max_order_notional(self, asset_class: str) -> float | None:
        """Optional per-asset-class notional cap (dollars). None = no cap.

        Stocks: dollar notional. Options: premium x 100 x contracts. Crypto: notional dollars.
        """
        block = self._config.get(asset_class, {})
        raw = block.get("max_order_notional")
        return float(raw) if raw is not None else None

    def approve_proposal(
        self,
        symbol: str,
        dollar_amount: float,
        asset_class: str = "stocks",
    ) -> tuple[bool, str]:
        """Validate a proposed order for workflow testing (simulation-safe).

        Skips live-trading and execution-mode gates; still enforces limits,
        watchlist, and asset-class rules.
        """
        return self._approve(symbol, dollar_amount, asset_class, require_live_execution=False)

    def approve_exit(
        self,
        symbol: str,
        dollar_amount: float = 0.0,
        asset_class: str = "stocks",
    ) -> tuple[bool, str]:
        """Approve a risk-reducing exit (sell / flatten).

        The kill switch is *protective*: it halts NEW exposure (entries) but must never
        block the bot from getting flat. Exits therefore bypass the entry-oriented gates
        (daily-loss limit, trade caps, per-trade notional, watchlist) and are always
        permitted. The trip is still logged for the audit trail.
        """
        self._ledger.reset_if_new_day(self._clock)
        if self._kill_switch_active:
            logger.warning(
                "Risk approving protective exit while kill switch active: %s %s ($%.2f)",
                asset_class, symbol, dollar_amount,
            )
            return True, "exit allowed (risk-reducing); kill switch does not block exits"
        logger.info("Risk approving exit: %s %s ($%.2f)", asset_class, symbol, dollar_amount)
        return True, "exit allowed (risk-reducing)"

    @property
    def allows_new_entries(self) -> bool:
        """False when the kill switch is engaged. Exits remain allowed regardless."""
        return not self._kill_switch_active

    def approve(
        self,
        symbol: str,
        dollar_amount: float,
        asset_class: str = "stocks",
    ) -> tuple[bool, str]:
        """Validate an order against all risk controls before live execution.

        Returns (approved, reason).
        """
        return self._approve(symbol, dollar_amount, asset_class, require_live_execution=True)

    def _approve(
        self,
        symbol: str,
        dollar_amount: float,
        asset_class: str,
        *,
        require_live_execution: bool,
    ) -> tuple[bool, str]:
        self._ledger.reset_if_new_day(self._clock)
        config = self._config

        # Protective kill switch: halts NEW exposure (entry approvals flow through here).
        # Risk-reducing exits use ``approve_exit`` and are never blocked by the kill switch.
        if self._kill_switch_active:
            if "DAILY_LOSS_BREACHED" in self._kill_switch_reasons:
                return False, (
                    f"daily loss limit reached ({self._ledger.realised_loss} >= "
                    f"{self.effective_max_daily_loss}); kill switch active"
                )
            return False, f"kill switch active ({', '.join(self._kill_switch_reasons) or 'engaged'})"

        if require_live_execution and not config.get("live_trading_enabled", False):
            return False, "live_trading_enabled is false"

        supported = config.get("active_asset_classes", ["stocks"])
        if asset_class not in supported:
            return False, f"asset class '{asset_class}' not supported (allowed: {supported})"

        block = config.get(asset_class, {})
        if not block.get("enabled", False):
            return False, f"asset class '{asset_class}' is disabled"
        if asset_class in {"options", "crypto"}:
            if block.get("require_explicit_enablement", True) and not block.get("explicit_enablement", False):
                return False, f"asset class '{asset_class}' requires explicit enablement"

        mode = config.get("trading_mode", "simulation")
        if require_live_execution and mode != "live":
            return False, f"trading_mode is '{mode}', not 'live'"
        if require_live_execution and asset_class in {"options", "crypto"} and not block.get("live_enabled", False):
            return False, f"live {asset_class} trading is disabled"

        watchlist = config.get("watchlist", {}).get(asset_class, [])
        if watchlist and symbol not in watchlist:
            return False, f"symbol '{symbol}' not in approved watchlist"

        if dollar_amount > self.max_dollars_per_trade:
            return False, (
                f"dollar amount {dollar_amount} exceeds max_dollars_per_trade {self.max_dollars_per_trade}"
            )

        max_notional = self.max_order_notional(asset_class)
        if max_notional is not None and dollar_amount > max_notional:
            return False, (
                f"{asset_class} notional {dollar_amount} exceeds max_order_notional {max_notional}"
            )

        capital_limit = self.strategy_capital_limit
        if capital_limit is not None and dollar_amount > capital_limit:
            return False, (
                f"dollar amount {dollar_amount} exceeds assigned_capital {capital_limit}"
            )

        daily_loss_limit = self.effective_max_daily_loss
        if self._ledger.realised_loss >= daily_loss_limit:
            self.engage_kill_switch("DAILY_LOSS_BREACHED")
            return False, f"daily loss limit reached ({self._ledger.realised_loss} >= {daily_loss_limit})"

        if self._ledger.trade_count >= self.max_trades_per_day:
            return False, f"daily trade limit reached ({self._ledger.trade_count} >= {self.max_trades_per_day})"

        if self._ledger.open_positions >= self.max_open_positions:
            return False, (
                f"max open positions reached ({self._ledger.open_positions} >= {self.max_open_positions})"
            )

        logger.info("Risk approved: %s %s $%.2f", asset_class, symbol, dollar_amount)
        return True, "approved"

    def record_trade(self, loss: float = 0.0) -> None:
        self._ledger.reset_if_new_day(self._clock)
        self._ledger.trade_count += 1
        self._ledger.realised_loss += abs(loss)
        if self._ledger.realised_loss >= self.effective_max_daily_loss:
            self.engage_kill_switch("DAILY_LOSS_BREACHED")

    def record_fill_pnl(self, realized_pnl: float) -> None:
        """Record a realized fill outcome. Negative PnL accrues to the daily loss.

        This is the single funnel from actual broker fills into the daily-loss limit
        and kill switch. ``record_trade`` keeps the historical (loss-only) signature for
        callers that only know the loss magnitude.
        """
        self._ledger.reset_if_new_day(self._clock)
        self._ledger.trade_count += 1
        if realized_pnl < 0:
            self._ledger.realised_loss += abs(realized_pnl)
        if self._ledger.realised_loss >= self.effective_max_daily_loss:
            self.engage_kill_switch("DAILY_LOSS_BREACHED")

    def set_open_positions(self, count: int) -> None:
        self._ledger.open_positions = count

    # ── ledger sync (SQLite is the single source of truth) ──────────────
    def sync_ledger(self, *, trade_count: int | None = None, realised_loss: float | None = None,
                    open_positions: int | None = None, trade_date: date | str | None = None) -> None:
        """Hydrate the in-memory ledger from a persisted (SQLite) snapshot."""
        if trade_date is not None:
            if isinstance(trade_date, str):
                trade_date = date.fromisoformat(trade_date)
            self._ledger.trade_date = trade_date
        if trade_count is not None:
            self._ledger.trade_count = int(trade_count)
        if realised_loss is not None:
            self._ledger.realised_loss = float(realised_loss)
        if open_positions is not None:
            self._ledger.open_positions = int(open_positions)
        if self._ledger.realised_loss >= self.effective_max_daily_loss:
            self.engage_kill_switch("DAILY_LOSS_BREACHED")

    def ledger_snapshot(self) -> dict:
        return {
            "trade_date": self._ledger.trade_date.isoformat(),
            "trade_count": self._ledger.trade_count,
            "realised_loss": self._ledger.realised_loss,
            "open_positions": self._ledger.open_positions,
        }

    @property
    def session_day(self) -> date:
        return self._clock.session_day()

    # ── kill switch ──────────────────────────────────────────────────────
    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def kill_switch_reasons(self) -> list[str]:
        return list(self._kill_switch_reasons)

    def engage_kill_switch(self, reason: str = "MANUAL") -> None:
        self._kill_switch_active = True
        if reason and reason not in self._kill_switch_reasons:
            self._kill_switch_reasons.append(reason)
        logger.error("Kill switch ENGAGED: %s", reason)

    def reset_kill_switch(self) -> None:
        self._kill_switch_active = False
        self._kill_switch_reasons = []
