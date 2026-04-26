# Stock & Crypto Analysis

## When to Use
- User asks about stock/crypto prices, analysis, or trading strategies
- User mentions ticker symbols (AAPL, BTC-USD, etc.)
- User wants technical indicators, charts, backtesting, or portfolio analysis

## Workflow
0. **Briefing mode** — If the user asks to "brief me on <TICKER>", "research <TICKER>", or "write a report on <TICKER>":
   a. Build a company-aware query before calling `web_research`.
      Use the company name if you know it, not just the ticker.
      Bad: `"ADBE stock analysis earnings financial performance 2026"`
      Better: `"Adobe earnings guidance analyst reactions April 2026"`
   b. Make the first query narrow and news-oriented, aimed at one knowledge gap.
      Examples: latest earnings, guidance changes, product/news catalysts, regulatory/legal issues, analyst revisions.
   c. Call `web_research` once with that focused query unless you clearly need a follow-up query.
      Note: the backend may automatically rewrite vague stock/company prompts into a few more focused company-news queries.
      If `web_research` returns `queries_used`, treat those as the actual coverage plan that was searched.
   d. If the first query leaves a gap, use up to two follow-up queries, each covering one missing area only.
      Example follow-up gaps:
      - earnings / guidance
      - product launches / AI strategy / demand
      - regulation / litigation / acquisition news
      - analyst downgrades / valuation debate
   e. Call `fetch_market_data(symbol=<TICKER>, period="6mo", interval="1d")`.
   f. Call `compute_indicator` for RSI(14), SMA(50), and SMA(200) as needed for the briefing.
   g. For written briefings, structure the report around markdown tables for valuation, indicators, catalysts, risks, and sources.
   h. Summarize the findings clearly in chat unless the user explicitly asks for a file deliverable.
   i. If the user asks for a file, prefer markdown unless they explicitly ask for another format.
1. **Check prior work only if explicitly asked** — Use `rag_query` only when the user asks for prior local notes, earlier reports, or previously saved strategies
2. **Fetch data** — Use `fetch_market_data` to get OHLCV data for the requested symbol
3. **Compute indicators** — Use `compute_indicator` for RSI, MACD, Bollinger Bands, SMA/EMA
4. **Analyze** — Look for patterns: oversold/overbought, crossovers, divergences, support/resistance
5. **Present clearly** — Prefer markdown tables and concise bullet conclusions for visual structure
6. **Strategy** — If asked, use `run_backtest` to test a strategy on historical data
7. **Report** — Summarize findings with specific numbers, dates, and actionable signals
8. **Index results optionally** — Use `rag_index` only if the user wants the analysis saved for future recall

## Rules
- Do not call `rag_query` by default for stock requests; it is usually empty unless the user previously saved something relevant
- In briefing mode, prefer `web_research` over separate `web_search` and `web_fetch` calls
- In briefing mode, keep `web_research` calls to at most 3 total
- In briefing mode, do not use vague ticker-only queries like `"<TICKER> stock analysis 2026"`
- Prefer company-name queries tied to one information gap, such as earnings, guidance, analyst reactions, product news, or legal/regulatory updates
- Prefer recent-news phrasing over generic finance phrasing; ask for what changed, not just broad "analysis"
- If `web_research` returns `queries_used`, use that to judge which knowledge gaps are already covered before issuing another web query
- Prefer Tavily snippets first; only request `fetch_top` when the snippets are clearly insufficient
- For written briefings, prefer markdown tables over generated charts unless the user explicitly asks for a chart
- Do not default to generating a PDF report for stock briefings
- ALWAYS use real data from tools — never make up prices or indicator values
- Show your reasoning: "RSI is 34.2 which is below 35 oversold threshold"
- When building strategies, ALWAYS backtest before recommending
- Include risk metrics: max drawdown, Sharpe ratio, win rate
- Be clear about limitations: past performance ≠ future results

## Available Tools
- `fetch_market_data(symbol, period, interval)` — Yahoo Finance OHLCV data
- `compute_indicator(symbol, indicator, params)` — Technical indicators (Phase 2)
- `run_backtest(strategy_code)` — Execute and evaluate a trading strategy (Phase 2)
- `write_strategy(name, rules, results)` — Save a strategy to file (Phase 2)
- `compare_strategies(names)` — Compare multiple strategies (Phase 2)

## Common Patterns
- **Momentum**: RSI < 30 + MACD crossover = potential buy
- **Mean Reversion**: Price below lower Bollinger Band + RSI < 35 = potential buy
- **Trend Following**: Price > SMA(50) > SMA(200) = uptrend confirmation
