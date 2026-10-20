"""Custom Lumibot-compatible strategies for the trading bot.

This package contains autonomous-capable strategy logic that integrates with
the FastAPI backend, risk engine, and Alpaca order workflow. All strategies
here follow a proposal-first design: they evaluate signals and emit proposals;
they never place live broker orders directly.
"""

from lumibot.custom_strategies import indicators  # noqa: F401

__all__ = ["indicators"]
