"""Stock strategy skill — tool implementations.

Tools:
  - fetch_market_data: Yahoo Finance OHLCV data
  - compute_indicator: RSI, MACD, Bollinger Bands, SMA, EMA
  - generate_chart: Candlestick + indicator charts (mplfinance PNG + plotext terminal)
  - run_backtest: Execute a Python strategy on historical data
  - write_strategy: Save strategy rules + results to file
  - compare_strategies: Rank saved strategies by metrics
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


# ── fetch_market_data ─────────────────────────────────────────────────

async def fetch_market_data(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
) -> str:
    """Fetch OHLCV market data from Yahoo Finance."""
    try:
        import yfinance as yf
    except ImportError:
        return json.dumps({"error": "yfinance not installed. Run: uv add yfinance"})

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            return json.dumps({"error": f"No data found for {symbol}"})

        latest = df.iloc[-1]
        summary = {
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "data_points": len(df),
            "date_range": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
            "latest": {
                "date": df.index[-1].strftime("%Y-%m-%d"),
                "open": round(float(latest["Open"]), 2),
                "high": round(float(latest["High"]), 2),
                "low": round(float(latest["Low"]), 2),
                "close": round(float(latest["Close"]), 2),
                "volume": int(latest["Volume"]),
            },
            "stats": {
                "period_high": round(float(df["High"].max()), 2),
                "period_low": round(float(df["Low"].min()), 2),
                "avg_volume": int(df["Volume"].mean()),
                "price_change_pct": round(
                    float((df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100), 2
                ),
            },
        }

        # Last 10 rows to save context
        recent = df.tail(10).copy()
        recent.index = recent.index.strftime("%Y-%m-%d")
        recent_data = []
        for date, row in recent.iterrows():
            recent_data.append({
                "date": date,
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        summary["recent_data"] = recent_data
        return json.dumps(summary, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to fetch data for {symbol}: {str(e)}"})


# ── compute_indicator ─────────────────────────────────────────────────

async def compute_indicator(
    symbol: str,
    indicator: str,
    period: str = "6mo",
    **params: Any,
) -> str:
    """Compute a technical indicator for a symbol.

    Supported indicators: RSI, MACD, SMA, EMA, BOLLINGER
    """
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
    except ImportError:
        return json.dumps({"error": "Dependencies not installed."})

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval="1d")
        if df.empty:
            return json.dumps({"error": f"No data for {symbol}"})

        close = df["Close"]
        indicator_upper = indicator.upper().strip()
        result: dict[str, Any] = {"symbol": symbol, "indicator": indicator_upper}

        if indicator_upper == "RSI":
            n = int(params.get("window", 14))
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).rolling(window=n).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(window=n).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            latest_rsi = round(float(rsi.iloc[-1]), 2)

            result["params"] = {"window": n}
            result["latest_value"] = latest_rsi
            result["signal"] = (
                "oversold (potential buy)" if latest_rsi < 30
                else "overbought (potential sell)" if latest_rsi > 70
                else "neutral"
            )
            # Last 5 values
            result["recent"] = [
                {"date": rsi.index[i].strftime("%Y-%m-%d"), "value": round(float(rsi.iloc[i]), 2)}
                for i in range(-5, 0) if not pd.isna(rsi.iloc[i])
            ]

        elif indicator_upper == "MACD":
            fast = int(params.get("fast", 12))
            slow = int(params.get("slow", 26))
            signal_period = int(params.get("signal", 9))

            ema_fast = close.ewm(span=fast).mean()
            ema_slow = close.ewm(span=slow).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal_period).mean()
            histogram = macd_line - signal_line

            result["params"] = {"fast": fast, "slow": slow, "signal": signal_period}
            result["latest"] = {
                "macd": round(float(macd_line.iloc[-1]), 4),
                "signal": round(float(signal_line.iloc[-1]), 4),
                "histogram": round(float(histogram.iloc[-1]), 4),
            }
            # Crossover detection
            if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0:
                result["signal"] = "bullish crossover (buy signal)"
            elif histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0:
                result["signal"] = "bearish crossover (sell signal)"
            elif histogram.iloc[-1] > 0:
                result["signal"] = "bullish (MACD above signal)"
            else:
                result["signal"] = "bearish (MACD below signal)"

        elif indicator_upper in ("SMA", "EMA"):
            n = int(params.get("window", 50))
            if indicator_upper == "SMA":
                ma = close.rolling(window=n).mean()
            else:
                ma = close.ewm(span=n).mean()

            latest_ma = round(float(ma.iloc[-1]), 2)
            latest_price = round(float(close.iloc[-1]), 2)

            result["params"] = {"window": n}
            result["latest_value"] = latest_ma
            result["latest_price"] = latest_price
            result["signal"] = (
                f"price above {indicator_upper}({n}) — bullish"
                if latest_price > latest_ma
                else f"price below {indicator_upper}({n}) — bearish"
            )

        elif indicator_upper in ("BOLLINGER", "BB"):
            n = int(params.get("window", 20))
            num_std = float(params.get("std", 2.0))

            sma = close.rolling(window=n).mean()
            std = close.rolling(window=n).std()
            upper = sma + num_std * std
            lower = sma - num_std * std

            latest_price = round(float(close.iloc[-1]), 2)
            result["params"] = {"window": n, "std": num_std}
            result["latest"] = {
                "upper": round(float(upper.iloc[-1]), 2),
                "middle": round(float(sma.iloc[-1]), 2),
                "lower": round(float(lower.iloc[-1]), 2),
                "price": latest_price,
            }
            # Band width for squeeze detection
            band_width = round(float((upper.iloc[-1] - lower.iloc[-1]) / sma.iloc[-1] * 100), 2)
            result["band_width_pct"] = band_width

            if latest_price < float(lower.iloc[-1]):
                result["signal"] = "price below lower band — potential buy (oversold)"
            elif latest_price > float(upper.iloc[-1]):
                result["signal"] = "price above upper band — potential sell (overbought)"
            elif band_width < 5:
                result["signal"] = "squeeze detected — volatility expansion expected"
            else:
                result["signal"] = "price within bands — neutral"

        else:
            return json.dumps({
                "error": f"Unknown indicator: {indicator}. Supported: RSI, MACD, SMA, EMA, BOLLINGER"
            })

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to compute {indicator} for {symbol}: {str(e)}"})


# ── generate_chart ────────────────────────────────────────────────────

async def generate_chart(
    symbol: str,
    period: str = "6mo",
    indicators: str = "sma_20,sma_50,volume",
    output_path: str = "",
    chart_type: str = "candle",
) -> str:
    """Generate a candlestick chart with indicators. Saves as PNG."""
    try:
        _configure_matplotlib_env()
        import matplotlib
        matplotlib.use("Agg")
        import yfinance as yf
        import mplfinance as mpf
    except ImportError:
        return json.dumps({"error": "mplfinance not installed."})

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval="1d")
        if df.empty:
            return json.dumps({"error": f"No data for {symbol}"})

        # Parse indicators
        addplots = []
        indicator_list = [i.strip().lower() for i in indicators.split(",")]

        for ind in indicator_list:
            if ind.startswith("sma_"):
                n = int(ind.split("_")[1])
                ma = df["Close"].rolling(window=n).mean()
                addplots.append(mpf.make_addplot(ma, label=f"SMA({n})"))
            elif ind.startswith("ema_"):
                n = int(ind.split("_")[1])
                ma = df["Close"].ewm(span=n).mean()
                addplots.append(mpf.make_addplot(ma, label=f"EMA({n})"))
            elif ind == "rsi":
                delta = df["Close"].diff()
                gain = delta.where(delta > 0, 0.0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                addplots.append(mpf.make_addplot(rsi, panel=2, ylabel="RSI", label="RSI(14)"))
            # volume is handled by mplfinance directly

        if output_path:
            filepath = Path(output_path)
            filepath.parent.mkdir(parents=True, exist_ok=True)
        else:
            charts_dir = Path("charts")
            charts_dir.mkdir(exist_ok=True)
            filename = f"{symbol}_{period}.png"
            filepath = charts_dir / filename

        style = mpf.make_mpf_style(base_mpf_style="charles", rc={"font.size": 8})
        mpf.plot(
            df,
            type=chart_type,
            style=style,
            title=f"\n{symbol} — {period}",
            volume="volume" in indicator_list,
            addplot=addplots if addplots else None,
            savefig=str(filepath),
            figsize=(12, 8),
        )

        return json.dumps({
            "chart_saved": str(filepath),
            "symbol": symbol,
            "period": period,
            "indicators": indicator_list,
            "data_points": len(df),
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to generate chart: {str(e)}"})


def _configure_matplotlib_env() -> None:
    cache_dir = Path(tempfile.gettempdir()) / "apex_matplotlib"
    cache_dir.mkdir(parents=True, exist_ok=True)
    import os
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))


# ── run_backtest ──────────────────────────────────────────────────────

async def run_backtest(
    symbol: str,
    strategy_code: str,
    period: str = "1y",
    initial_capital: float = 10000.0,
) -> str:
    """Run a backtest on historical data using a Python strategy.

    The strategy_code should define a function `signal(row, prev_row)` that returns:
      "BUY", "SELL", or "HOLD"

    Each row has: open, high, low, close, volume, sma_20, sma_50, rsi, macd, macd_signal
    """
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
    except ImportError:
        return json.dumps({"error": "Dependencies not installed."})

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval="1d")
        if df.empty:
            return json.dumps({"error": f"No data for {symbol}"})

        # Pre-compute common indicators for the strategy to use
        df["sma_20"] = df["Close"].rolling(20).mean()
        df["sma_50"] = df["Close"].rolling(50).mean()

        # RSI
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()

        df = df.dropna().copy()
        df.columns = [c.lower() for c in df.columns]

        # Execute the strategy in a restricted namespace
        namespace: dict[str, Any] = {}
        exec(strategy_code, {"__builtins__": {}}, namespace)

        if "signal" not in namespace:
            return json.dumps({"error": "strategy_code must define a `signal(row, prev_row)` function"})

        signal_fn = namespace["signal"]

        # Run simulation
        capital = initial_capital
        position = 0  # shares held
        trades: list[dict] = []
        portfolio_values = []

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            try:
                sig = signal_fn(row, prev_row)
            except Exception:
                sig = "HOLD"

            price = float(row["close"])

            if sig == "BUY" and position == 0:
                position = capital / price
                capital = 0
                trades.append({"date": str(df.index[i].date()), "action": "BUY", "price": round(price, 2)})
            elif sig == "SELL" and position > 0:
                capital = position * price
                position = 0
                trades.append({"date": str(df.index[i].date()), "action": "SELL", "price": round(price, 2)})

            portfolio_value = capital + position * price
            portfolio_values.append(portfolio_value)

        # Final value
        final_price = float(df.iloc[-1]["close"])
        final_value = capital + position * final_price

        # Metrics
        returns = pd.Series(portfolio_values).pct_change().dropna()
        total_return = (final_value / initial_capital - 1) * 100
        sharpe = float(returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0

        # Max drawdown
        peak = pd.Series(portfolio_values).cummax()
        drawdown = (pd.Series(portfolio_values) - peak) / peak
        max_drawdown = float(drawdown.min()) * 100

        # Win rate
        buy_sell_pairs = []
        for i in range(0, len(trades) - 1, 2):
            if i + 1 < len(trades):
                buy_sell_pairs.append(trades[i + 1]["price"] - trades[i]["price"])
        wins = sum(1 for p in buy_sell_pairs if p > 0)
        win_rate = (wins / len(buy_sell_pairs) * 100) if buy_sell_pairs else 0

        # Buy and hold comparison
        bnh_return = (final_price / float(df.iloc[0]["close"]) - 1) * 100

        result = {
            "symbol": symbol,
            "period": period,
            "initial_capital": initial_capital,
            "final_value": round(final_value, 2),
            "total_return_pct": round(total_return, 2),
            "buy_and_hold_return_pct": round(bnh_return, 2),
            "alpha_pct": round(total_return - bnh_return, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_drawdown, 2),
            "total_trades": len(trades),
            "win_rate_pct": round(win_rate, 1),
            "trades": trades[:20],  # Limit to save context
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Backtest failed: {str(e)}"})


# ── write_strategy ────────────────────────────────────────────────────

async def write_strategy(
    name: str,
    description: str,
    rules: str,
    backtest_results: str = "",
) -> str:
    """Save a trading strategy to a file."""
    try:
        strategies_dir = Path("strategies")
        strategies_dir.mkdir(exist_ok=True)

        filename = f"{name.lower().replace(' ', '_')}.md"
        filepath = strategies_dir / filename

        content = f"# Strategy: {name}\n\n"
        content += f"## Description\n{description}\n\n"
        content += f"## Rules\n{rules}\n\n"
        if backtest_results:
            content += f"## Backtest Results\n{backtest_results}\n"

        filepath.write_text(content, encoding="utf-8")

        return json.dumps({
            "saved": str(filepath),
            "name": name,
            "size_bytes": len(content),
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to save strategy: {str(e)}"})


# ── compare_strategies ────────────────────────────────────────────────

async def compare_strategies(
    strategy_names: str = "",
) -> str:
    """Compare saved strategy files. Lists all strategies if no names given."""
    try:
        strategies_dir = Path("strategies")
        if not strategies_dir.exists():
            return json.dumps({"error": "No strategies directory found. Save a strategy first."})

        files = list(strategies_dir.glob("*.md"))
        if not files:
            return json.dumps({"error": "No saved strategies found."})

        strategies = []
        for f in files:
            content = f.read_text(encoding="utf-8")
            strategies.append({
                "name": f.stem,
                "file": str(f),
                "size": len(content),
                "preview": content[:500],
            })

        return json.dumps({
            "strategies_found": len(strategies),
            "strategies": strategies,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Failed to compare strategies: {str(e)}"})
