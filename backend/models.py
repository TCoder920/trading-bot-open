"""Pydantic models for the trading bot API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from lumibot.custom_strategies.orb_engine import ORB_DEFAULTS


class ConfigUpdate(BaseModel):
    key: str
    value: object


class ConfigBatchUpdate(BaseModel):
    updates: dict[str, object] = Field(default_factory=dict)


class OrderUpdate(BaseModel):
    notes: str | None = None
    broker_order_id: str | None = None
    execution_status: str | None = None


class OrderFailRequest(BaseModel):
    reason: str = "Execution failed"


class AccountSelect(BaseModel):
    account_number: str


class RiskSettingsUpdate(BaseModel):
    max_dollars_per_trade: float | None = None
    max_loss_per_trade: float | None = None
    max_daily_loss: float | None = None
    max_trades_per_day: int | None = None
    max_open_positions: int | None = None
    assigned_capital: float | None = None
    use_assigned_capital_limit: bool | None = None
    max_stock_order_notional: float | None = None


class WatchlistAdd(BaseModel):
    symbol: str
    asset_class: str = "stocks"


class WatchlistRemove(BaseModel):
    symbol: str
    asset_class: str = "stocks"


class StrategyCreate(BaseModel):
    name: str
    template: str
    enabled: bool = False
    config: dict = Field(default_factory=dict)


class StrategyUpdate(BaseModel):
    template: str | None = None
    enabled: bool | None = None
    config: dict | None = None


class OrderProposal(BaseModel):
    symbol: str
    side: str = "buy"
    quantity: float | None = None
    dollar_amount: float | None = None
    notional: float | None = None
    sizing_mode: str | None = None
    order_type: str = "market"
    time_in_force: str = "day"
    strategy: str | None = None
    strategy_id: str | None = None
    asset_class: str = "stocks"
    limit_price: float | None = None
    stop_price: float | None = None
    underlying_symbol: str | None = None
    option_type: str | None = None
    strike: float | None = None
    expiration: str | None = None
    premium: float | None = None
    quote_currency: str | None = None


class BacktestRequest(BaseModel):
    strategy_name: str
    symbols: list[str]
    start_date: str
    end_date: str
    starting_cash: float = 100000
    data_source: str = "alpaca"
    template: str | None = None
    params: dict = Field(default_factory=dict)


class OrbGenerateRequest(BaseModel):
    """Generate ORB proposals from supplied market-data snapshots (simulation)."""

    strategy_name: str | None = None
    config: dict = Field(default_factory=dict)
    snapshots: list[dict] = Field(default_factory=list)
    regime_state: str = "unknown"
    equity: float = 0.0
    now_time: str | None = None  # HH:MM ET; defaults to current entry window check skip


class OrbResetRequest(BaseModel):
    trade_date: str | None = None


STRATEGY_TEMPLATES = {
    "moving_average_crossover": {
        "label": "Moving Average Crossover",
        "description": "Buy when fast MA crosses above slow MA, sell on cross below.",
        "default_config": {
            "fast_period": 10,
            "slow_period": 50,
            "ma_type": "SMA",
            "timeframe": "1D",
            "data_source": "alpaca",
            "stop_loss_pct": 2.0,
            "take_profit_pct": 5.0,
            "max_holding_days": 30,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
    "rsi_mean_reversion": {
        "label": "RSI Mean Reversion",
        "description": "Buy when RSI is oversold, sell when overbought.",
        "default_config": {
            "rsi_period": 14,
            "oversold": 30,
            "overbought": 70,
            "timeframe": "1D",
            "data_source": "alpaca",
            "stop_loss_pct": 2.0,
            "take_profit_pct": 4.0,
            "max_holding_days": 15,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
    "vwap_reclaim": {
        "label": "VWAP Reclaim",
        "description": "Buy when price reclaims VWAP from below with volume confirmation.",
        "default_config": {
            "volume_threshold": 1.5,
            "confirmation_bars": 2,
            "timeframe": "5Min",
            "data_source": "alpaca",
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "max_holding_days": 1,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
    "vwap_rejection": {
        "label": "VWAP Rejection",
        "description": "Short when price rejects at VWAP from above with volume.",
        "default_config": {
            "volume_threshold": 1.5,
            "rejection_bars": 2,
            "timeframe": "5Min",
            "data_source": "alpaca",
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "max_holding_days": 1,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
    "opening_range_breakout": {
        "label": "Opening Range Breakout",
        "description": "Buy/sell on break of the first N-minute range after open.",
        "default_config": {
            "range_minutes": 30,
            "breakout_buffer_pct": 0.1,
            "timeframe": "5Min",
            "data_source": "alpaca",
            "stop_loss_pct": 1.5,
            "take_profit_pct": 3.0,
            "max_holding_days": 1,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
    "momentum_breakout": {
        "label": "Momentum Breakout",
        "description": "Buy on high-of-day breakout with relative volume surge.",
        "default_config": {
            "lookback_bars": 20,
            "rvol_threshold": 2.0,
            "price_change_pct": 2.0,
            "timeframe": "1D",
            "data_source": "alpaca",
            "stop_loss_pct": 3.0,
            "take_profit_pct": 6.0,
            "max_holding_days": 5,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
    "stocks_in_play_orb_v1": {
        "label": "Stocks In Play ORB v1",
        "description": (
            "Long-only opening-range-breakout for liquid US stocks/ETFs. Captures the "
            "first 5-minute opening range (09:30-09:35 ET), ranks 'in play' names by "
            "relative volume, and proposes long breakouts above the range with VWAP, "
            "spread, and SPY regime filters. Proposal-first: emits proposals for the "
            "Alpaca order workflow after risk approval, never direct live orders."
        ),
        "asset_class": "stocks",
        "long_only": True,
        "default_config": {
            **{k: v for k, v in ORB_DEFAULTS.items()},
            "data_source": "alpaca",
        },
        "param_help": {
            "opening_range_start": "Opening range window start (ET). v1: 09:30.",
            "opening_range_end": "Opening range window end (ET). v1: 09:35 (first 5 min).",
            "entry_window_start": "Earliest time new breakout entries are allowed (ET).",
            "entry_window_end": "Latest time new breakout entries are allowed (ET).",
            "flatten_time": "All positions are force-flattened at this time (ET).",
            "max_entries_per_symbol_per_day": "Hard cap on entries per symbol per day.",
            "min_price": "Minimum share price to qualify.",
            "max_price": "Maximum share price to qualify.",
            "min_avg_daily_dollar_volume": "Minimum average daily $ volume for liquidity.",
            "min_avg_share_volume_20d": "Minimum 20-day average share volume.",
            "min_daily_atr_14": "Minimum daily ATR(14) so there is enough range to trade.",
            "rvol_min": "Minimum first-5-min relative volume to be 'in play'.",
            "top_candidates": "Keep the top N symbols ranked by RVOL.",
            "allowed_asset_class": "Asset class allowed (stocks only in v1).",
            "breakout_buffer": "Absolute $ buffer above the range high. 0 = one tick.",
            "tick_size": "Minimum price increment used for the one-tick breakout buffer.",
            "require_above_vwap": "Require price above intraday VWAP to enter.",
            "spread_cap_abs": "Max allowed bid/ask spread in dollars.",
            "spread_cap_bps": "Max allowed spread in basis points of price (lower cap wins).",
            "enable_spy_regime_filter": "Only take longs when the SPY regime is risk-on.",
            "spy_daily_ema_period": "SPY daily EMA period for the regime filter (e.g. 200).",
            "allow_if_spy_above_daily_ema_200": "Risk-on means SPY above its daily EMA(200).",
            "enable_intraday_spy_vwap_filter": "Optional intraday SPY VWAP regime gate.",
            "atr_stop_factor": "Stop = entry - ATR14 * this factor (lower of this and OR-low).",
            "risk_per_trade_pct": "Percent of equity risked per trade (0.25 = 0.25%).",
            "max_position_notional_pct": "Max single position notional as % of equity.",
            "max_portfolio_gross_pct": "Max gross exposure as % of equity.",
            "max_volume_participation_pct": "Max share size as % of average volume.",
            "partial_at_R": "Take a partial profit at this R multiple.",
            "move_stop_to_breakeven_after_R": "Move stop to breakeven after this R multiple.",
            "exit_on_vwap_loss": "Exit remainder on a 5-min close back below VWAP.",
            "max_daily_loss_pct": "Daily loss kill-switch as % of equity.",
            "max_trades_per_day": "Max strategy entries per day.",
            "max_consecutive_losses": "Stop entering after this many losses in a row.",
            "max_quote_age_seconds": "Quotes older than this are stale (blocks live).",
            "max_bar_age_seconds": "Bars older than this are stale (blocks live).",
            "max_slippage_buffer_pct": "Allowed price drift before execution (kill-switch).",
            "data_source": "Backtest data source. Intraday ORB uses Alpaca minute data when credentials are configured.",
        },
    },
    "buy_and_hold": {
        "label": "Simple Buy and Hold",
        "description": "Buy and hold for testing. No exit signal.",
        "default_config": {
            "timeframe": "1D",
            "data_source": "alpaca",
            "stop_loss_pct": 0,
            "take_profit_pct": 0,
            "max_holding_days": 0,
            "position_sizing": "fixed_dollar",
            "dollar_amount": 100,
        },
    },
}

INDICATOR_DEFINITIONS = [
    {"key": "sma", "label": "SMA", "fields": [{"name": "period", "type": "int", "default": 20}], "tooltip": "Simple Moving Average over N periods."},
    {"key": "ema", "label": "EMA", "fields": [{"name": "period", "type": "int", "default": 12}], "tooltip": "Exponential Moving Average, weights recent prices more."},
    {"key": "rsi", "label": "RSI", "fields": [{"name": "period", "type": "int", "default": 14}, {"name": "oversold", "type": "float", "default": 30}, {"name": "overbought", "type": "float", "default": 70}], "tooltip": "Relative Strength Index. Measures momentum on 0-100 scale."},
    {"key": "vwap", "label": "VWAP", "fields": [], "tooltip": "Volume-Weighted Average Price. Intraday fair-value benchmark."},
    {"key": "macd", "label": "MACD", "fields": [{"name": "fast", "type": "int", "default": 12}, {"name": "slow", "type": "int", "default": 26}, {"name": "signal", "type": "int", "default": 9}], "tooltip": "Moving Average Convergence Divergence. Trend and momentum."},
    {"key": "bollinger", "label": "Bollinger Bands", "fields": [{"name": "period", "type": "int", "default": 20}, {"name": "std_dev", "type": "float", "default": 2.0}], "tooltip": "Price bands at N standard deviations from SMA."},
    {"key": "volume_threshold", "label": "Volume Threshold", "fields": [{"name": "min_volume", "type": "int", "default": 1000000}], "tooltip": "Minimum absolute volume to qualify a signal."},
    {"key": "rvol", "label": "Relative Volume", "fields": [{"name": "threshold", "type": "float", "default": 1.5}, {"name": "lookback", "type": "int", "default": 20}], "tooltip": "Current volume relative to N-period average."},
    {"key": "opening_range", "label": "Opening Range", "fields": [{"name": "range_minutes", "type": "int", "default": 30}], "tooltip": "High/low of the first N minutes after market open."},
    {"key": "price_change_pct", "label": "Price Change %", "fields": [{"name": "threshold", "type": "float", "default": 2.0}], "tooltip": "Minimum percentage price change to trigger signal."},
    {"key": "hod_breakout", "label": "High-of-Day Breakout", "fields": [{"name": "buffer_pct", "type": "float", "default": 0.1}], "tooltip": "Triggers when price breaks above the current session high."},
    {"key": "lod_breakdown", "label": "Low-of-Day Breakdown", "fields": [{"name": "buffer_pct", "type": "float", "default": 0.1}], "tooltip": "Triggers when price breaks below the current session low."},
]
