from __future__ import annotations

from eval.comparator import compare_against_baseline, compare_t2_abilities


def test_compare_against_baseline_passes_for_small_changes() -> None:
    baseline = [
        {
            "scenario": "core_agent",
            "test_case_id": "case1",
            "model": "m1",
            "context_strategy": "truncate",
            "total_score": 0.90,
            "cost_usd": 0.10,
            "accuracy": 0.95,
        }
    ]
    current = [
        {
            "scenario": "core_agent",
            "test_case_id": "case1",
            "model": "m1",
            "context_strategy": "truncate",
            "total_score": 0.87,
            "cost_usd": 0.105,
            "accuracy": 0.93,
        }
    ]

    report = compare_against_baseline(current, baseline)
    assert report["passed"] is True
    assert report["regressions"] == []


def test_compare_against_baseline_flags_score_and_cost_regressions() -> None:
    baseline = [
        {
            "scenario": "core_agent",
            "test_case_id": "case1",
            "model": "m1",
            "context_strategy": "truncate",
            "total_score": 0.90,
            "cost_usd": 0.10,
            "accuracy": 0.95,
        }
    ]
    current = [
        {
            "scenario": "core_agent",
            "test_case_id": "case1",
            "model": "m1",
            "context_strategy": "truncate",
            "total_score": 0.70,
            "cost_usd": 0.20,
            "accuracy": 0.80,
        }
    ]

    report = compare_against_baseline(current, baseline)
    assert report["passed"] is False
    assert any("score dropped" in issue for issue in report["regressions"])
    assert any("mean cost increased" in issue for issue in report["regressions"])


def test_compare_t2_abilities_flags_weighted_drop_and_cliff() -> None:
    baseline = [
        {"ability": "goal_retention", "difficulty": "easy", "total_score": 0.9},
        {"ability": "goal_retention", "difficulty": "medium", "total_score": 0.9},
        {"ability": "goal_retention", "difficulty": "hard", "total_score": 0.85},
    ]
    current = [
        {"ability": "goal_retention", "difficulty": "easy", "total_score": 0.85},
        {"ability": "goal_retention", "difficulty": "medium", "total_score": 0.80},
        {"ability": "goal_retention", "difficulty": "hard", "total_score": 0.20},
    ]

    report = compare_t2_abilities(current, baseline)

    assert any("dropped" in issue for issue in report["regressions"])
    assert any("new cliff" in issue for issue in report["regressions"])
