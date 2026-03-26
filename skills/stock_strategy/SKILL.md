# Stock & Crypto Analysis

## When to Use
- User asks about stock/crypto prices, analysis, or trading strategies
- User mentions ticker symbols (AAPL, BTC-USD, etc.)
- User wants technical indicators, charts, backtesting, or portfolio analysis

## Workflow
1. **Fetch data** — Use `fetch_market_data` to get OHLCV data for the requested symbol
2. **Compute indicators** — Use `compute_indicator` for RSI, MACD, Bollinger Bands, SMA/EMA
3. **Analyze** — Look for patterns: oversold/overbought, crossovers, divergences, support/resistance
4. **Visualize** — Use `generate_chart` to create candlestick charts with indicator overlays
5. **Strategy** — If asked, use `run_backtest` to test a strategy on historical data
6. **Report** — Summarize findings with specific numbers, dates, and actionable signals

## Rules
- ALWAYS use real data from tools — never make up prices or indicator values
- Show your reasoning: "RSI is 34.2 which is below 35 oversold threshold"
- When building strategies, ALWAYS backtest before recommending
- Include risk metrics: max drawdown, Sharpe ratio, win rate
- Be clear about limitations: past performance ≠ future results

## Available Tools
- `fetch_market_data(symbol, period, interval)` — Yahoo Finance OHLCV data
- `compute_indicator(symbol, indicator, params)` — Technical indicators (Phase 2)
- `generate_chart(symbol, indicators, signals)` — Candlestick + indicator charts (Phase 2)
- `run_backtest(strategy_code)` — Execute and evaluate a trading strategy (Phase 2)
- `write_strategy(name, rules, results)` — Save a strategy to file (Phase 2)
- `compare_strategies(names)` — Compare multiple strategies (Phase 2)

## Common Patterns
- **Momentum**: RSI < 30 + MACD crossover = potential buy
- **Mean Reversion**: Price below lower Bollinger Band + RSI < 35 = potential buy
- **Trend Following**: Price > SMA(50) > SMA(200) = uptrend confirmation
