"""Tests for extended-hours config validation (#2, #3)."""

from backend.config_validation import validate_extended_hours_config


def _cfg(**alpaca_overrides):
    cfg = {
        "alpaca": {"allow_extended_hours": False, "extended_hours_data_feed": "sip",
                   "marketable_limit_offset_pct": 0.2},
        "scheduler": {"interval_seconds": 60},
        "stocks_in_play_orb_v1": {"extended_hours_signals": "rth_only"},
    }
    cfg["alpaca"].update(alpaca_overrides)
    return cfg


def test_valid_defaults():
    assert validate_extended_hours_config(_cfg()) == []


def test_extended_hours_with_iex_warns():
    errors = validate_extended_hours_config(_cfg(allow_extended_hours=True, extended_hours_data_feed="iex"))
    assert any("sip" in e for e in errors)


def test_bad_feed():
    errors = validate_extended_hours_config(_cfg(extended_hours_data_feed="tradingview"))
    assert any("iex" in e or "sip" in e for e in errors)


def test_offset_out_of_range():
    errors = validate_extended_hours_config(_cfg(marketable_limit_offset_pct=50))
    assert any("marketable_limit_offset_pct" in e for e in errors)


def test_bad_interval():
    cfg = _cfg()
    cfg["scheduler"]["interval_seconds"] = 0
    errors = validate_extended_hours_config(cfg)
    assert any("interval_seconds" in e for e in errors)


def test_bad_signal_mode():
    cfg = _cfg()
    cfg["stocks_in_play_orb_v1"]["extended_hours_signals"] = "always"
    errors = validate_extended_hours_config(cfg)
    assert any("extended_hours_signals" in e for e in errors)
