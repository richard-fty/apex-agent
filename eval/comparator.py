"""Comparator — side-by-side comparison of benchmark results across models/strategies."""

from __future__ import annotations

from typing import Any
from collections import defaultdict


def compare_results(results: list[dict[str, Any]]) -> list[str]:
    """Compare results across models and strategies.

    Returns formatted comparison lines for display.
    """
    if not results:
        return ["No results to compare."]

    # Group by model
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        model = r.get("model", "unknown")
        by_model[model].append(r)

    # Group by strategy
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        strategy = r.get("context_strategy", "unknown")
        by_strategy[strategy].append(r)

    lines: list[str] = []

    # Model comparison
    if len(by_model) > 1:
        lines.append("[bold]Model Comparison[/bold]")
        lines.append("=" * 70)

        for model, model_results in sorted(by_model.items()):
            stats = _compute_aggregate(model_results)
            lines.append(
                f"  {model:<40} "
                f"Avg Score: {stats['avg_score']:.3f} | "
                f"Avg Tokens: {stats['avg_tokens']:.0f} | "
                f"Avg Cost: ${stats['avg_cost']:.4f} | "
                f"Avg Time: {stats['avg_time']:.1f}s"
            )

        # Winner
        best_model = max(by_model.keys(), key=lambda m: _compute_aggregate(by_model[m])["avg_score"])
        cheapest_model = min(by_model.keys(), key=lambda m: _compute_aggregate(by_model[m])["avg_cost"])
        fastest_model = min(by_model.keys(), key=lambda m: _compute_aggregate(by_model[m])["avg_time"])

        lines.append("")
        lines.append(f"  [green]Best quality:[/green] {best_model}")
        lines.append(f"  [green]Cheapest:[/green] {cheapest_model}")
        lines.append(f"  [green]Fastest:[/green] {fastest_model}")
        lines.append("")

    # Strategy comparison
    if len(by_strategy) > 1:
        lines.append("[bold]Strategy Comparison[/bold]")
        lines.append("=" * 70)

        for strategy, strategy_results in sorted(by_strategy.items()):
            stats = _compute_aggregate(strategy_results)
            lines.append(
                f"  {strategy:<40} "
                f"Avg Score: {stats['avg_score']:.3f} | "
                f"Avg Tokens: {stats['avg_tokens']:.0f} | "
                f"Avg Cost: ${stats['avg_cost']:.4f}"
            )

        lines.append("")

    # Per test case breakdown
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        case_id = r.get("test_case_id", "unknown")
        by_case[case_id].append(r)

    if len(by_case) > 1:
        lines.append("[bold]Per Test Case[/bold]")
        lines.append("=" * 70)

        for case_id, case_results in sorted(by_case.items()):
            scores = [r.get("total_score", 0) for r in case_results]
            avg = sum(scores) / len(scores)
            best = max(case_results, key=lambda r: r.get("total_score", 0))
            lines.append(
                f"  {case_id:<30} "
                f"Avg: {avg:.3f} | "
                f"Best: {best.get('model', '?')} ({best.get('total_score', 0):.3f})"
            )

        lines.append("")

    return lines


def _compute_aggregate(results: list[dict[str, Any]]) -> dict[str, float]:
    """Compute aggregate stats for a group of results."""
    if not results:
        return {"avg_score": 0, "avg_tokens": 0, "avg_cost": 0, "avg_time": 0}

    scores = [r.get("total_score", 0) for r in results]
    tokens = [r.get("tokens", 0) for r in results]
    costs = [r.get("cost_usd", 0) for r in results]
    times = [r.get("duration_seconds", 0) for r in results]

    n = len(results)
    return {
        "avg_score": sum(scores) / n,
        "avg_tokens": sum(tokens) / n,
        "avg_cost": sum(costs) / n,
        "avg_time": sum(times) / n,
        "total_cost": sum(costs),
        "total_runs": n,
    }
