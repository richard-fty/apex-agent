"""Comparator — side-by-side comparison and regression gating for benchmark results."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


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

    ability_scores = summarize_t2_abilities(results)
    if ability_scores:
        lines.append("[bold]T2 Ability Summary[/bold]")
        lines.append("=" * 70)
        for ability, stats in sorted(ability_scores.items()):
            lines.append(
                f"  {ability:<30} "
                f"Weighted: {stats['weighted']:.3f} | "
                f"Easy: {stats['easy']:.3f} | "
                f"Medium: {stats['medium']:.3f} | "
                f"Hard: {stats['hard']:.3f} | "
                f"Cliff: {stats['cliff']:.3f}"
            )
        lines.append("")

    return lines


def load_baseline(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    # Handle both old format (list) and new format (dict with "results" key)
    if isinstance(data, dict):
        return data.get("results", [])
    return data


def save_baseline(results: list[dict[str, Any]], path: str | Path, scenario: str = "unknown", model: str = "unknown", strategy: str = "unknown") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    data = {
        "scenario": scenario,
        "model": model,
        "strategy": strategy,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "results": results,
        "aggregate": {
            "num_cases": len(results),
        }
    }
    target.write_text(json.dumps(data, indent=2, default=str))
    return target


def compare_against_baseline(
    results: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    *,
    max_score_drop: float = 0.05,
    max_t3_drop_pct: float = 0.05,
    max_cost_increase_pct: float = 0.10,
) -> dict[str, Any]:
    """Compare benchmark results to a saved baseline and gate regressions.

    The comparison is keyed by (scenario, test_case_id, model, context_strategy).
    It enforces:
    - no score drop larger than ``max_score_drop``
    - no T3 metric drop larger than ``max_t3_drop_pct`` for shared metrics
    - no mean cost increase above ``max_cost_increase_pct``
    """

    base_by_key = {_result_key(item): item for item in baseline}
    current_by_key = {_result_key(item): item for item in results}

    missing = sorted(key for key in base_by_key if key not in current_by_key)
    added = sorted(key for key in current_by_key if key not in base_by_key)
    regressions: list[str] = []

    shared_keys = sorted(set(base_by_key) & set(current_by_key))
    for key in shared_keys:
        current = current_by_key[key]
        previous = base_by_key[key]

        score_drop = previous.get("total_score", 0.0) - current.get("total_score", 0.0)
        if score_drop > max_score_drop:
            regressions.append(
                f"{_format_key(key)} score dropped by {score_drop:.3f} "
                f"({previous.get('total_score', 0.0):.3f} -> {current.get('total_score', 0.0):.3f})"
            )

        for metric in ("accuracy", "goal_retention", "tool_selection"):
            if metric in previous and metric in current and previous[metric] > 0:
                drop_pct = (previous[metric] - current[metric]) / previous[metric]
                if drop_pct > max_t3_drop_pct:
                    regressions.append(
                        f"{_format_key(key)} {metric} dropped by {drop_pct * 100:.1f}% "
                        f"({previous[metric]:.3f} -> {current[metric]:.3f})"
                    )

    baseline_cost = _average([item.get("cost_usd", 0.0) for item in baseline])
    current_cost = _average([item.get("cost_usd", 0.0) for item in results])
    cost_increase_pct = 0.0
    if baseline_cost > 0:
        cost_increase_pct = (current_cost - baseline_cost) / baseline_cost
        if cost_increase_pct > max_cost_increase_pct:
            regressions.append(
                f"mean cost increased by {cost_increase_pct * 100:.1f}% "
                f"(${baseline_cost:.4f} -> ${current_cost:.4f})"
            )

    ability_report = compare_t2_abilities(results, baseline)
    regressions.extend(ability_report["regressions"])

    passed = not regressions and not missing
    return {
        "passed": passed,
        "missing": missing,
        "added": added,
        "regressions": regressions,
        "baseline_mean_cost": baseline_cost,
        "current_mean_cost": current_cost,
        "cost_increase_pct": cost_increase_pct,
        "ability_scores": ability_report["current"],
        "baseline_ability_scores": ability_report["baseline"],
    }


def format_regression_gate(report: dict[str, Any]) -> list[str]:
    lines = ["[bold]Regression Gate[/bold]", "=" * 70]
    status = "[green]PASS[/green]" if report["passed"] else "[red]FAIL[/red]"
    lines.append(f"  Status: {status}")
    if report["missing"]:
        lines.append("  Missing baseline keys:")
        for key in report["missing"]:
            lines.append(f"    - {_format_key(key)}")
    if report["regressions"]:
        lines.append("  Regressions:")
        for issue in report["regressions"]:
            lines.append(f"    - {issue}")
    if report["added"]:
        lines.append("  New result keys:")
        for key in report["added"]:
            lines.append(f"    - {_format_key(key)}")
    ability_scores = report.get("ability_scores", {})
    if ability_scores:
        lines.append("  T2 ability scores:")
        for ability, stats in sorted(ability_scores.items()):
            lines.append(
                "    - "
                f"{ability}: weighted {stats['weighted']:.3f} "
                f"(easy {stats['easy']:.3f}, medium {stats['medium']:.3f}, hard {stats['hard']:.3f})"
            )
    lines.append(
        f"  Mean cost: ${report['baseline_mean_cost']:.4f} -> ${report['current_mean_cost']:.4f}"
    )
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


def summarize_t2_abilities(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Compute weighted T2 ability scores with easy/medium/hard breakdowns."""
    by_ability: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for result in results:
        ability = result.get("ability")
        difficulty = result.get("difficulty")
        if not ability or difficulty not in {"easy", "medium", "hard"}:
            continue
        by_ability[ability][difficulty].append(float(result.get("total_score", 0.0)))

    summary: dict[str, dict[str, float]] = {}
    for ability, buckets in by_ability.items():
        easy = _average(buckets.get("easy", []))
        medium = _average(buckets.get("medium", []))
        hard = _average(buckets.get("hard", []))
        weighted = (easy * 0.2) + (medium * 0.3) + (hard * 0.5)
        summary[ability] = {
            "easy": easy,
            "medium": medium,
            "hard": hard,
            "weighted": weighted,
            "cliff": medium - hard,
        }
    return summary


def compare_t2_abilities(
    results: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    *,
    max_weighted_drop: float = 0.05,
    max_new_cliff: float = 0.4,
) -> dict[str, Any]:
    current = summarize_t2_abilities(results)
    previous = summarize_t2_abilities(baseline)
    regressions: list[str] = []

    for ability in sorted(set(previous) & set(current)):
        weighted_drop = previous[ability]["weighted"] - current[ability]["weighted"]
        if weighted_drop > max_weighted_drop:
            regressions.append(
                f"T2 ability {ability} dropped by {weighted_drop:.3f} "
                f"({previous[ability]['weighted']:.3f} -> {current[ability]['weighted']:.3f})"
            )

        baseline_cliff = previous[ability]["cliff"]
        current_cliff = current[ability]["cliff"]
        if current_cliff > max_new_cliff and current_cliff > baseline_cliff:
            regressions.append(
                f"T2 ability {ability} introduced a new cliff: "
                f"medium-hard gap {current_cliff:.3f} "
                f"({current[ability]['medium']:.3f} -> {current[ability]['hard']:.3f})"
            )

    return {
        "baseline": previous,
        "current": current,
        "regressions": regressions,
    }


def _result_key(result: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        result.get("scenario", "unknown"),
        result.get("test_case_id", "unknown"),
        result.get("model", "unknown"),
        result.get("context_strategy", "unknown"),
    )


def _format_key(key: tuple[str, str, str, str]) -> str:
    scenario, case_id, model, strategy = key
    return f"{scenario}/{case_id} [{model} | {strategy}]"


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
