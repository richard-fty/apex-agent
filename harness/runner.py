"""Benchmark runner — run model x scenario x strategy matrix.

Usage:
    uv run python -m harness.runner
    uv run python -m harness.runner --models deepseek/deepseek-chat,gpt-4o
    uv run python -m harness.runner --cases single_stock_analysis,chart_generation
    uv run python -m harness.runner --strategies truncate,summary,tiered
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any

logging.basicConfig(level=logging.ERROR)
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

import litellm
litellm.suppress_debug_info = True

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from agent.runtime.loop import run_agent
from harness.runtime import RuntimeConfig
from harness.comparator import compare_results
from harness.report import generate_report
from scenarios.registry import get_scenario, list_scenarios
from config import settings

console = Console()


def load_test_cases(
    scenario_name: str,
    case_ids: list[str] | None = None,
) -> tuple[Any, list[dict[str, Any]]]:
    """Load test cases from a named scenario."""
    scenario = get_scenario(scenario_name)
    cases = scenario.get_test_cases()
    if case_ids:
        cases = [c for c in cases if c.get("id") in case_ids]
    return scenario, cases


async def run_single(
    scenario: Any,
    model: str,
    test_case: dict[str, Any],
    strategy: str,
    timeout: int = 300,
) -> dict[str, Any]:
    """Run a single model x test_case x strategy combination."""
    runtime = RuntimeConfig(
        max_steps=test_case.get("max_steps", 20),
        timeout_seconds=timeout,
    )

    trace = await run_agent(
        user_input=test_case["input"],
        model=model,
        context_strategy=strategy,
        runtime_config=runtime,
    )

    # Evaluate
    score = scenario.evaluate(trace, test_case)
    score["model"] = model
    score["context_strategy"] = strategy
    score["scenario"] = scenario.name

    # Save trace
    trace.save("results")

    return score


async def run_benchmark(
    scenario: Any,
    models: list[str],
    test_cases: list[dict[str, Any]],
    strategies: list[str],
    timeout: int = 300,
) -> list[dict[str, Any]]:
    """Run the full benchmark matrix."""
    total = len(models) * len(test_cases) * len(strategies)
    results: list[dict[str, Any]] = []

    console.print(Panel(
        f"Models: {', '.join(models)}\n"
        f"Scenario: {scenario.name}\n"
        f"Test cases: {len(test_cases)}\n"
        f"Strategies: {', '.join(strategies)}\n"
        f"Total runs: {total}",
        title="[bold cyan]Benchmark Runner[/bold cyan]",
        border_style="cyan",
    ))

    run_num = 0
    for model in models:
        for strategy in strategies:
            for case in test_cases:
                run_num += 1
                case_id = case.get("id", "?")
                console.print(
                    f"\n[bold]Run {run_num}/{total}:[/bold] "
                    f"{model} | {strategy} | {case_id}"
                )
                console.print(f"[dim]  Prompt: {case['input'][:80]}...[/dim]")

                start = time.time()
                try:
                    score = await run_single(scenario, model, case, strategy, timeout)
                    elapsed = time.time() - start

                    # Print quick result
                    total_score = score["total_score"]
                    color = "green" if total_score >= 0.7 else "yellow" if total_score >= 0.4 else "red"
                    console.print(
                        f"  [{color}]Score: {total_score:.3f}[/{color}] | "
                        f"Steps: {score['steps']} | "
                        f"Tokens: {score['tokens']} | "
                        f"Cost: ${score['cost_usd']:.4f} | "
                        f"Time: {elapsed:.1f}s"
                    )

                    results.append(score)

                except Exception as e:
                    console.print(f"  [bold red]Error: {e}[/bold red]")
                    results.append({
                        "test_case_id": case_id,
                        "model": model,
                        "context_strategy": strategy,
                        "total_score": 0.0,
                        "error": str(e),
                    })

    return results


def print_results_table(results: list[dict[str, Any]]) -> None:
    """Print results as a Rich table."""
    table = Table(title="Benchmark Results", border_style="blue")
    table.add_column("Model", style="bold")
    table.add_column("Strategy")
    table.add_column("Test Case")
    table.add_column("Score", justify="right")
    table.add_column("Steps", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Time", justify="right")

    for r in results:
        score = r.get("total_score", 0)
        color = "green" if score >= 0.7 else "yellow" if score >= 0.4 else "red"
        table.add_row(
            r.get("model", "?"),
            r.get("context_strategy", "?"),
            r.get("test_case_id", "?"),
            f"[{color}]{score:.3f}[/{color}]",
            str(r.get("steps", "?")),
            str(r.get("tokens", "?")),
            f"${r.get('cost_usd', 0):.4f}",
            f"{r.get('duration_seconds', 0):.1f}s",
        )

    console.print(table)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Benchmark Runner")
    parser.add_argument(
        "--scenario", default="stock_strategy",
        help=f"Scenario name: {', '.join(list_scenarios())}",
    )
    parser.add_argument(
        "--models", default=settings.default_model,
        help="Comma-separated model IDs (e.g. deepseek/deepseek-chat,gpt-4o)",
    )
    parser.add_argument(
        "--cases", default=None,
        help="Comma-separated test case IDs (default: all)",
    )
    parser.add_argument(
        "--strategies", default="truncate",
        help="Comma-separated context strategies (e.g. truncate,summary,tiered)",
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Timeout per run in seconds",
    )
    parser.add_argument(
        "--output", default="results",
        help="Output directory for results",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",")]
    case_ids = [c.strip() for c in args.cases.split(",")] if args.cases else None
    scenario, test_cases = load_test_cases(args.scenario, case_ids)

    if not test_cases:
        console.print("[bold red]No test cases found.[/bold red]")
        return

    # Run benchmark
    results = await run_benchmark(scenario, models, test_cases, strategies, args.timeout)

    # Print results table
    console.print()
    print_results_table(results)

    # Print comparison if multiple models/strategies
    if len(models) > 1 or len(strategies) > 1:
        console.print()
        comparison = compare_results(results)
        for line in comparison:
            console.print(line)

    # Generate and save report
    report_path = generate_report(results, args.output)
    console.print(f"\n[dim]Report saved to {report_path}[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
