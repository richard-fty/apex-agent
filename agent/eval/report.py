"""Report generator — produces markdown comparison reports from benchmark results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from collections import defaultdict


def generate_report(results: list[dict[str, Any]], output_dir: str = "results") -> Path:
    """Generate a markdown benchmark report.

    Returns the path to the saved report file.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output / f"benchmark_{timestamp}.md"

    # Group results
    by_model: dict[str, list[dict]] = defaultdict(list)
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    by_case: dict[str, list[dict]] = defaultdict(list)

    for r in results:
        by_model[r.get("model", "?")].append(r)
        by_strategy[r.get("context_strategy", "?")].append(r)
        by_case[r.get("test_case_id", "?")].append(r)

    lines = [
        f"# Benchmark Report",
        f"",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## Configuration",
        f"",
        f"- Models: {', '.join(sorted(by_model.keys()))}",
        f"- Strategies: {', '.join(sorted(by_strategy.keys()))}",
        f"- Test cases: {len(by_case)}",
        f"- Total runs: {len(results)}",
        f"",
    ]

    # Summary table
    lines.append("## Results Summary")
    lines.append("")
    lines.append("| Model | Strategy | Test Case | Score | Steps | Tokens | Cost | Time |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for r in results:
        lines.append(
            f"| {r.get('model', '?')} "
            f"| {r.get('context_strategy', '?')} "
            f"| {r.get('test_case_id', '?')} "
            f"| {r.get('total_score', 0):.3f} "
            f"| {r.get('steps', '?')} "
            f"| {r.get('tokens', '?')} "
            f"| ${r.get('cost_usd', 0):.4f} "
            f"| {r.get('duration_seconds', 0):.1f}s |"
        )

    lines.append("")

    # Model comparison
    if len(by_model) > 1:
        lines.append("## Model Comparison")
        lines.append("")
        lines.append("| Model | Avg Score | Avg Tokens | Avg Cost | Avg Time | Total Cost |")
        lines.append("|---|---|---|---|---|---|")

        for model in sorted(by_model.keys()):
            mr = by_model[model]
            avg_score = sum(r.get("total_score", 0) for r in mr) / len(mr)
            avg_tokens = sum(r.get("tokens", 0) for r in mr) / len(mr)
            avg_cost = sum(r.get("cost_usd", 0) for r in mr) / len(mr)
            avg_time = sum(r.get("duration_seconds", 0) for r in mr) / len(mr)
            total_cost = sum(r.get("cost_usd", 0) for r in mr)

            lines.append(
                f"| {model} "
                f"| {avg_score:.3f} "
                f"| {avg_tokens:.0f} "
                f"| ${avg_cost:.4f} "
                f"| {avg_time:.1f}s "
                f"| ${total_cost:.4f} |"
            )

        lines.append("")

    # Strategy comparison
    if len(by_strategy) > 1:
        lines.append("## Strategy Comparison")
        lines.append("")
        lines.append("| Strategy | Avg Score | Avg Tokens | Avg Cost |")
        lines.append("|---|---|---|---|")

        for strategy in sorted(by_strategy.keys()):
            sr = by_strategy[strategy]
            avg_score = sum(r.get("total_score", 0) for r in sr) / len(sr)
            avg_tokens = sum(r.get("tokens", 0) for r in sr) / len(sr)
            avg_cost = sum(r.get("cost_usd", 0) for r in sr) / len(sr)

            lines.append(
                f"| {strategy} "
                f"| {avg_score:.3f} "
                f"| {avg_tokens:.0f} "
                f"| ${avg_cost:.4f} |"
            )

        lines.append("")

    # Per test case detail
    lines.append("## Per Test Case Detail")
    lines.append("")

    for case_id in sorted(by_case.keys()):
        case_results = by_case[case_id]
        lines.append(f"### {case_id}")
        lines.append("")

        for r in case_results:
            lines.append(f"**{r.get('model', '?')}** ({r.get('context_strategy', '?')})")
            lines.append(f"- Score: {r.get('total_score', 0):.3f}")

            scores = r.get("scores", {})
            if scores:
                for key, value in scores.items():
                    label = key.replace("_", " ").title()
                    lines.append(f"- {label}: {value:.3f}")

            details = r.get("details", {})
            if details.get("tools_missing"):
                lines.append(f"- Missing tools: {', '.join(details['tools_missing'])}")
            if details.get("content_missing"):
                lines.append(f"- Missing content: {', '.join(details['content_missing'])}")

            lines.append("")

    # Save report
    content = "\n".join(lines)
    report_path.write_text(content, encoding="utf-8")

    # Also save raw JSON
    json_path = output / f"benchmark_{timestamp}.json"
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    return report_path
