"""Stock strategy skill pack — metadata and tool registration."""

from __future__ import annotations

from agent.models import ToolDef, ToolParameter
from skills.base import SkillPack, ToolHandler
from skills.stock_strategy.tools import (
    fetch_market_data,
    compute_indicator,
    generate_chart,
    run_backtest,
    write_strategy,
    compare_strategies,
)


class StockStrategySkill(SkillPack):
    @property
    def name(self) -> str:
        return "stock_strategy"

    @property
    def description(self) -> str:
        return "Stock and crypto analysis — fetch market data, compute indicators, backtest strategies"

    @property
    def keywords(self) -> list[str]:
        return [
            "stock", "stocks", "crypto", "cryptocurrency", "bitcoin", "ethereum",
            "aapl", "tsla", "goog", "msft", "amzn", "btc", "eth", "sol",
            "rsi", "macd", "bollinger", "moving average", "sma", "ema",
            "trading", "strategy", "backtest", "portfolio", "invest",
            "price", "chart", "candlestick", "indicator", "signal",
            "analyze", "ticker", "symbol", "market",
        ]

    def get_tools(self) -> list[tuple[ToolDef, ToolHandler]]:
        return [
            # fetch_market_data
            (
                ToolDef(
                    name="fetch_market_data",
                    description="Fetch OHLCV market data from Yahoo Finance. Returns summary stats and recent prices.",
                    parameters=[
                        ToolParameter(name="symbol", type="string", description="Ticker symbol (e.g. AAPL, BTC-USD)"),
                        ToolParameter(name="period", type="string", description="Data period", required=False,
                                      enum=["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"], default="6mo"),
                        ToolParameter(name="interval", type="string", description="Data interval", required=False,
                                      enum=["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"], default="1d"),
                    ],
                ),
                fetch_market_data,
            ),
            # compute_indicator
            (
                ToolDef(
                    name="compute_indicator",
                    description="Compute a technical indicator (RSI, MACD, SMA, EMA, BOLLINGER) for a symbol. Returns latest value and signal.",
                    parameters=[
                        ToolParameter(name="symbol", type="string", description="Ticker symbol"),
                        ToolParameter(name="indicator", type="string", description="Indicator name",
                                      enum=["RSI", "MACD", "SMA", "EMA", "BOLLINGER"]),
                        ToolParameter(name="period", type="string", description="Data period", required=False, default="6mo"),
                        ToolParameter(name="window", type="integer", description="Lookback window (default: varies by indicator)", required=False),
                        ToolParameter(name="fast", type="integer", description="MACD fast period (default: 12)", required=False),
                        ToolParameter(name="slow", type="integer", description="MACD slow period (default: 26)", required=False),
                    ],
                ),
                compute_indicator,
            ),
            # generate_chart
            (
                ToolDef(
                    name="generate_chart",
                    description="Generate a candlestick chart with indicators. Saves as PNG to charts/ directory.",
                    parameters=[
                        ToolParameter(name="symbol", type="string", description="Ticker symbol"),
                        ToolParameter(name="period", type="string", description="Data period", required=False, default="6mo"),
                        ToolParameter(name="indicators", type="string",
                                      description="Comma-separated indicators to overlay (e.g. 'sma_20,sma_50,volume,rsi')",
                                      required=False, default="sma_20,sma_50,volume"),
                        ToolParameter(name="chart_type", type="string", description="Chart type",
                                      required=False, enum=["candle", "ohlc", "line"], default="candle"),
                    ],
                ),
                generate_chart,
            ),
            # run_backtest
            (
                ToolDef(
                    name="run_backtest",
                    description=(
                        "Run a backtest on historical data. Provide Python code defining a "
                        "signal(row, prev_row) function returning 'BUY', 'SELL', or 'HOLD'. "
                        "Each row has: open, high, low, close, volume, sma_20, sma_50, rsi, macd, macd_signal."
                    ),
                    parameters=[
                        ToolParameter(name="symbol", type="string", description="Ticker symbol"),
                        ToolParameter(name="strategy_code", type="string",
                                      description="Python code defining signal(row, prev_row) function"),
                        ToolParameter(name="period", type="string", description="Data period", required=False, default="1y"),
                        ToolParameter(name="initial_capital", type="number", description="Starting capital",
                                      required=False, default=10000),
                    ],
                ),
                run_backtest,
            ),
            # write_strategy
            (
                ToolDef(
                    name="write_strategy",
                    description="Save a trading strategy to a markdown file in strategies/ directory.",
                    parameters=[
                        ToolParameter(name="name", type="string", description="Strategy name"),
                        ToolParameter(name="description", type="string", description="What the strategy does"),
                        ToolParameter(name="rules", type="string", description="Entry/exit rules in detail"),
                        ToolParameter(name="backtest_results", type="string",
                                      description="Backtest results summary", required=False),
                    ],
                ),
                write_strategy,
            ),
            # compare_strategies
            (
                ToolDef(
                    name="compare_strategies",
                    description="List and compare saved strategy files from the strategies/ directory.",
                    parameters=[
                        ToolParameter(name="strategy_names", type="string",
                                      description="Comma-separated strategy names to compare (empty = list all)",
                                      required=False, default=""),
                    ],
                ),
                compare_strategies,
            ),
        ]
