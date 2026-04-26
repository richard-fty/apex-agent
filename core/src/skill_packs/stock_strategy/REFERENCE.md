# Stock Analysis Reference

## Technical Indicators

### RSI (Relative Strength Index)
- Range: 0-100
- Oversold: < 30 (potential buy)
- Overbought: > 70 (potential sell)
- Formula: RSI = 100 - (100 / (1 + RS)), where RS = avg gain / avg loss over N periods
- Default period: 14

### MACD (Moving Average Convergence Divergence)
- MACD Line = EMA(12) - EMA(26)
- Signal Line = EMA(9) of MACD Line
- Histogram = MACD Line - Signal Line
- Buy signal: MACD crosses above Signal (bullish crossover)
- Sell signal: MACD crosses below Signal (bearish crossover)

### Bollinger Bands
- Middle Band = SMA(20)
- Upper Band = SMA(20) + 2 * StdDev(20)
- Lower Band = SMA(20) - 2 * StdDev(20)
- Price touching lower band in uptrend = potential buy
- Price touching upper band in downtrend = potential sell
- Band squeeze (narrow bands) = volatility expansion expected

### Moving Averages
- SMA(N) = Simple Moving Average over N periods
- EMA(N) = Exponential Moving Average (more weight on recent)
- Golden Cross: SMA(50) crosses above SMA(200) — bullish
- Death Cross: SMA(50) crosses below SMA(200) — bearish

## Strategy Metrics

### Sharpe Ratio
- (Return - Risk-Free Rate) / Standard Deviation of Return
- \> 1.0 = acceptable, > 2.0 = good, > 3.0 = excellent

### Max Drawdown
- Largest peak-to-trough decline
- < 10% = conservative, 10-20% = moderate, > 20% = aggressive

### Win Rate
- Number of winning trades / total trades
- > 50% with positive expectancy = viable strategy

## Yahoo Finance Symbols
- US Stocks: AAPL, TSLA, GOOG, MSFT, AMZN, NVDA, META
- Crypto: BTC-USD, ETH-USD, SOL-USD, DOGE-USD
- Indices: ^SPX, ^DJI, ^IXIC
- ETFs: SPY, QQQ, IWM, GLD, TLT

## Period / Interval Reference
- Intraday (1m-15m intervals): max 7 days of data
- Hourly (1h interval): max 730 days
- Daily (1d interval): unlimited history
- Weekly/Monthly: unlimited history

## Query Construction

When using `web_research` for stocks, build queries around a specific knowledge gap.
The backend may rewrite vague stock/company prompts into focused company-news subqueries and return them in `queries_used`.

### Query Rules
- Prefer the company name over the ticker when possible
- Ask for what changed recently, not generic "stock analysis"
- Keep one query focused on one topic
- Use follow-up queries only to fill a missing area
- Avoid broad finance filler like `financial performance` unless paired with a concrete event such as earnings or guidance
- If the response includes `queries_used`, treat that as the actual query set that ran

### Good Query Patterns
- `<Company> earnings guidance analyst reaction April 2026`
- `<Company> latest news AI strategy datacenter demand April 2026`
- `<Company> SEC filing risks outlook 2026`
- `<Company> antitrust lawsuit acquisition news 2026`
- `<Company> analyst downgrade valuation concerns April 2026`

### Weak Query Patterns
- `<Ticker> stock analysis 2026`
- `<Ticker> financial performance`
- `<Ticker> recent information`
- `<Ticker> news earnings financial performance 2026`

### Knowledge Gap Checklist
Use at most 3 web queries total and cover only the missing gaps:

| Gap | Example Query |
|---|---|
| Earnings / Guidance | `Adobe earnings guidance analyst reaction April 2026` |
| Business / Product Catalyst | `Adobe latest news Firefly AI enterprise demand April 2026` |
| Risk / Regulation / Litigation | `Adobe lawsuit antitrust acquisition risk 2026` |
| Analyst / Valuation Debate | `Adobe analyst downgrade valuation concerns April 2026` |

## Briefing Outline

Use this when the user asks for a written stock briefing. Treat it as content guidance only.
Do not assume the final output format unless the user explicitly asks for one.

```md
# NVDA Equity Research Briefing

## Executive Summary
Two or three short paragraphs on the latest business update, valuation backdrop, and why the stock matters now.

## Market Snapshot

| Metric | Value | Takeaway |
|---|---:|---|
| Latest Close | $... | ... |
| 6M Change | ...% | ... |
| RSI(14) | ... | ... |
| SMA(50) | $... | ... |
| SMA(200) | $... | ... |

## News & Catalysts

| Source | Date | Key Point |
|---|---|---|
| [Headline 1](https://example.com/1) | 2026-04-20 | One sentence takeaway |
| [Headline 2](https://example.com/2) | 2026-04-19 | One sentence takeaway |
| [Headline 3](https://example.com/3) | 2026-04-18 | One sentence takeaway |

## Risks

| Risk | Why It Matters |
|---|---|
| Key risk 1 | ... |
| Key risk 2 | ... |
| Key risk 3 | ... |

## Sources

| Outlet | Link |
|---|---|
| Reuters | https://example.com/1 |
| SEC | https://example.com/2 |
| FT | https://example.com/3 |
```
