# AI Trading Team README Handoff - 2026-05-24

## Source Of Truth

Use the Lumibot example strategy directly:

`/path/to/workspace/Development/lumibot/lumibot/example_strategies/ai_trading_team.py`

Do not copy the strategy into MarketingManager. This is Lumibot example code and should live in Lumibot.

## Verified Tear Sheet

Use the fixed tear sheet HTML:

`/path/to/workspace/Development/lumibot/docs/assets/ai-trading-team-example/AITradingTeamStrategy_2026-05-24_16-07_R6B0ul_tearsheet.html`

Original generated copy:

`/path/to/workspace/Development/lumibot/logs/AITradingTeamStrategy_2026-05-24_16-07_R6B0ul_tearsheet.html`

## Screenshot

Use Rob's cropped screenshot:

`/path/to/workspace/Development/lumibot/docs/assets/ai-trading-team-example/ai-trading-team-tearsheet-rob-crop-2026-05-24.png`

This was copied from:

`/path/to/workspace/Desktop/Screenshot 2026-05-24 at 4.49.13 PM.png`

Do not use regenerated screenshots or alternate crops.

Expected screenshot content:

- Title: `AITradingTeamStrategy Compared to SPY`
- Period: `6 Apr, 2026 - 21 May, 2026`
- Annual Return: `1,135,333.24%`
- Total Return: `216%`
- Max Drawdown: `-20.31%`
- RoMaD: `55,910.7`
- Sharpe: `7.63`
- Sortino: `15.92`
- Header shows `LumiBot 4.5.34` and `QuantStats (Lumiwealth Version) (v.1.1.4)`

## Backtest Metrics

- Benchmark: SPY
- Annual Return: `1,135,333.24%`
- Total Return: `216%`
- Max Drawdown: `-20.31%`
- RoMaD: `55,910.7`
- Sharpe: `7.63`
- Sortino: `15.92`

## README Notes

- Keep the README example short and copy-pasteable.
- Show the backtest code first.
- If live trading is mentioned, add a separate short snippet below the backtest example.
- Do not add benchmark, fees, budget, quiet logs, custom tools, model variables, or extra strategy knobs back into the main README example.
- The example intentionally has one parameter: `universe`.
