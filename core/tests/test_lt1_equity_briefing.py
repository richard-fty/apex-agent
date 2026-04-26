from __future__ import annotations

from pathlib import Path

from agent.core.models import EventType
from agent.runtime.trace import Trace, TraceStep
from scenarios.lt1_equity_briefing.docx_utils import create_briefing_docx, write_placeholder_png
from scenarios.lt1_equity_briefing.evaluator import evaluate


def test_lt1_evaluator_accepts_valid_docx(tmp_path: Path) -> None:
    chart_path = tmp_path / "NVDA_chart.png"
    write_placeholder_png(chart_path)
    artifact_path = tmp_path / "NVDA_briefing.docx"
    create_briefing_docx(
        artifact_path,
        title="NVDA - Equity Research Briefing",
        summary="Summary",
        interpretation="Interpretation",
        news_items=[
            {"title": "A", "url": "https://example.com/a", "snippet": "sa"},
            {"title": "B", "url": "https://example.com/b", "snippet": "sb"},
            {"title": "C", "url": "https://example.com/c", "snippet": "sc"},
        ],
        risks=["Risk 1", "Risk 2"],
        sources=[
            {"url": "https://example.com/a"},
            {"url": "https://example.com/b"},
            {"url": "https://example.com/c"},
            {"url": "https://example.com/d"},
            {"url": "https://example.com/e"},
        ],
        chart_path=chart_path,
    )

    trace = Trace(
        run_id="lt1-test",
        model="mock",
        scenario="lt1_equity_briefing",
        prompt="Brief me on NVDA.",
        context_strategy="truncate",
    )
    trace.steps.append(
        TraceStep(
            step=1,
            event_type=EventType.TOOL_CALL_END,
            data={
                "name": "web_research",
                "success": True,
                "urls": [
                    "https://example.com/a",
                    "https://example.com/b",
                    "https://example.com/c",
                    "https://example.com/d",
                    "https://example.com/e",
                ],
            },
        )
    )
    trace.steps.extend(
        TraceStep(step=i + 2, event_type=EventType.TOOL_CALL_END, data={"name": name, "success": True})
        for i, name in enumerate(["fetch_market_data", "compute_indicator", "generate_chart", "write_file", "run_command"])
    )
    trace.tool_calls = [
        {
            "step": 1,
            "name": "web_research",
            "arguments": {},
            "success": True,
            "duration_ms": 1.0,
            "result_size": 100,
            "urls": [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
                "https://example.com/d",
                "https://example.com/e",
            ],
            "content_preview": "",
            "timestamp": 0.0,
        }
    ]

    test_case = {
        "id": "lt1_brief_nvda",
        "ability": "long_horizon_composition",
        "difficulty": "hard",
        "expected_tools": [
            "web_research",
            "fetch_market_data",
            "compute_indicator",
            "generate_chart",
            "write_file",
            "run_command",
        ],
        "forbidden_tools": ["rm", "web_fetch", "web_search"],
        "artifact_path": str(artifact_path),
        "supporting_artifacts": [str(tmp_path / "render.py"), str(chart_path)],
        "docx_required_headings": [
            "Executive Summary",
            "Price & Indicators",
            "News & Catalysts",
            "Risks",
            "Sources",
        ],
        "min_inline_images": 1,
        "min_hyperlinks": 5,
        "max_web_research_calls": 3,
        "max_steps": 30,
        "budget_usd": 1.50,
        "tier": "LT1",
    }
    (tmp_path / "render.py").write_text("print('ok')", encoding="utf-8")

    score = evaluate(trace, test_case)

    assert score["total_score"] > 0.9
    assert score["details"]["artifact"]["hyperlink_count"] >= 5
    assert score["details"]["artifact"]["inline_images"] >= 1
