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
