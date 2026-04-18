"""Tests for the complete memory system: archive, planner, memory tools, budget."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from agent.session.archive import SessionArchive
from agent.context.manager import ContextManager, PinnedFact
from tools.planner import PlanManager, VALID_TRANSITIONS, MAX_CREATES


# ── SessionArchive ──────────────────────────────────────────────────────


@pytest.fixture
def archive(tmp_path):
    db_path = str(tmp_path / "test_archive.db")
    a = SessionArchive(db_path=db_path)
    a.create_session(session_id="s1", model="test", context_strategy="truncate")
    return a


def test_archive_emit_and_read_events(archive):
    archive.emit_event("s1", "user_message_added", {"content": "hello world"})
    archive.emit_event("s1", "tool_finished", {"name": "read_file", "content": "file data here"})
    events = archive.get_events("s1")
    assert len(events) == 2
    assert events[0]["type"] == "user_message_added"
    assert events[1]["type"] == "tool_finished"
    assert events[0]["seq"] == 1
    assert events[1]["seq"] == 2


def test_archive_positional_read(archive):
    archive.emit_event("s1", "user_message_added", {"content": "msg1"})
    archive.emit_event("s1", "user_message_added", {"content": "msg2"})
    archive.emit_event("s1", "user_message_added", {"content": "msg3"})
    events = archive.get_events("s1", after=1)
    assert len(events) == 2
    assert events[0]["payload"]["content"] == "msg2"


def test_archive_session_isolation(archive):
    archive.create_session(session_id="s2", model="test", context_strategy="truncate")
    archive.emit_event("s1", "user_message_added", {"content": "session 1 data"})
    archive.emit_event("s2", "user_message_added", {"content": "session 2 data"})
    events_s1 = archive.get_events("s1")
    events_s2 = archive.get_events("s2")
    assert len(events_s1) == 1
    assert len(events_s2) == 1
    assert events_s1[0]["payload"]["content"] == "session 1 data"
    assert events_s2[0]["payload"]["content"] == "session 2 data"


def test_archive_recall_bm25(archive):
    archive.emit_event("s1", "tool_finished", {
        "name": "fetch_market_data",
        "content": "AAPL RSI(14) = 34.2 oversold, MACD = -1.23, Bollinger bands tight",
    })
    archive.emit_event("s1", "tool_finished", {
        "name": "web_search",
        "content": "Latest news about renewable energy and solar panels",
    })
    results = archive.recall("s1", "AAPL RSI oversold")
    assert len(results) >= 1
    assert "AAPL" in results[0]["fragment"]


def test_archive_recall_no_match(archive):
    archive.emit_event("s1", "user_message_added", {"content": "hello"})
    results = archive.recall("s1", "nonexistent_term_xyz")
    assert len(results) == 0


def test_archive_recall_session_isolation(archive):
    archive.create_session(session_id="s2", model="test", context_strategy="truncate")
    archive.emit_event("s1", "tool_finished", {"name": "read", "content": "secret data in s1"})
    archive.emit_event("s2", "tool_finished", {"name": "read", "content": "public data in s2"})
    results = archive.recall("s2", "secret data")
    assert len(results) == 0  # s1's data must not appear in s2's recall


# ── PlanManager ─────────────────────────────────────────────────────────


def test_plan_write_basic():
    pm = PlanManager()
    result = pm.write([
        {"id": "t1", "title": "Read sources", "phase": "read"},
        {"id": "t2", "title": "Write report", "phase": "write", "depends_on": ["t1"]},
    ])
    assert "2 tasks" in result
    assert len(pm.tasks) == 2


def test_plan_update_valid_transition():
    pm = PlanManager()
    pm.write([{"id": "t1", "title": "Read"}])
    assert "in_progress" in pm.update("t1", "in_progress")
    assert "done" in pm.update("t1", "done")
    assert pm.tasks["t1"].status == "done"


def test_plan_update_invalid_transition():
    pm = PlanManager()
    pm.write([{"id": "t1", "title": "Read"}])
    result = pm.update("t1", "done")  # pending → done (skipping in_progress)
    assert "Error" in result


def test_plan_done_is_done():
    pm = PlanManager()
    pm.write([{"id": "t1", "title": "Read"}])
    pm.update("t1", "in_progress")
    pm.update("t1", "done")
    # Try to revert via replan
    result = pm.write([{"id": "t1", "title": "Read", "status": "pending"}])
    assert "Error" in result
    assert "done" in result


def test_plan_root_immutability():
    pm = PlanManager()
    pm.write([{"id": "t1", "title": "Root"}, {"id": "t2", "title": "Sub"}])
    result = pm.write([{"id": "t2", "title": "Only sub"}])  # removes t1
    assert "Error" in result
    assert "root" in result.lower()


def test_plan_dependency_enforcement():
    pm = PlanManager()
    pm.write([
        {"id": "t1", "title": "Read"},
        {"id": "t2", "title": "Write", "depends_on": ["t1"]},
    ])
    result = pm.update("t2", "in_progress")  # t1 not done yet
    assert "Error" in result
    assert "t1" in result


def test_plan_replan_budget():
    pm = PlanManager()
    for i in range(MAX_CREATES):
        result = pm.write([{"id": "t1", "title": f"Plan v{i+1}"}])
        assert "Error" not in result
    result = pm.write([{"id": "t1", "title": "One too many"}])
    assert "Error" in result
    assert "budget" in result.lower()


def test_plan_view():
    pm = PlanManager()
    pm.write([
        {"id": "t1", "title": "Read sources", "phase": "read"},
        {"id": "t2", "title": "Write report", "depends_on": ["t1"]},
    ])
    pm.update("t1", "in_progress")
    view = pm.view()
    assert "t1" in view
    assert "t2" in view
    assert "in_progress" in view


def test_plan_restore_from_events():
    pm = PlanManager()
    events = [
        {"type": "plan_created", "payload": {
            "tasks": [
                {"id": "t1", "title": "Read", "status": "done", "phase": "read",
                 "acceptance": "", "depends_on": [], "note": "done"},
                {"id": "t2", "title": "Write", "status": "in_progress", "phase": "write",
                 "acceptance": "", "depends_on": ["t1"], "note": ""},
            ],
            "create_count": 1,
        }},
        {"type": "plan_task_updated", "payload": {
            "task_id": "t2", "status": "done", "note": "written",
        }},
    ]
    pm.restore_from_events(events)
    assert pm.tasks["t1"].status == "done"
    assert pm.tasks["t2"].status == "done"
    assert pm.create_count == 1


# ── ContextManager — pinned facts with LRU ──────────────────────────────


def test_pin_fact():
    cm = ContextManager(strategy_name="truncate", model="deepseek-chat")
    cm.pin_fact("AAPL RSI = 34.2")
    assert len(cm.pinned_facts) == 1
    assert cm.pinned_facts[0].text == "AAPL RSI = 34.2"


def test_pin_fact_deduplication():
    cm = ContextManager(strategy_name="truncate", model="deepseek-chat")
    cm.pin_fact("AAPL RSI = 34.2")
    cm.pin_fact("AAPL RSI = 34.2 oversold")  # substring of existing
    assert len(cm.pinned_facts) == 1  # not duplicated


def test_pin_fact_lru_eviction():
    cm = ContextManager(strategy_name="truncate", model="deepseek-chat")
    cm.pinned_facts_cap = 3
    cm.pin_fact("fact 1")
    cm._current_turn = 1
    cm.pin_fact("fact 2")
    cm._current_turn = 2
    cm.pin_fact("fact 3")
    cm._current_turn = 3
    evicted = cm.pin_fact("fact 4")  # should evict "fact 1" (oldest)
    assert evicted is not None
    assert evicted.text == "fact 1"
    assert len(cm.pinned_facts) == 3
    texts = [f.text for f in cm.pinned_facts]
    assert "fact 1" not in texts
    assert "fact 4" in texts


def test_forget_fact():
    cm = ContextManager(strategy_name="truncate", model="deepseek-chat")
    cm.pin_fact("AAPL RSI = 34.2")
    cm.pin_fact("NovaGreen: 35%")
    removed = cm.forget_fact("novagreen")
    assert removed == "NovaGreen: 35%"
    assert len(cm.pinned_facts) == 1


def test_forget_fact_not_found():
    cm = ContextManager(strategy_name="truncate", model="deepseek-chat")
    cm.pin_fact("AAPL RSI = 34.2")
    removed = cm.forget_fact("nonexistent")
    assert removed is None
    assert len(cm.pinned_facts) == 1


def test_get_pinned_text():
    cm = ContextManager(strategy_name="truncate", model="deepseek-chat")
    cm.pin_fact("AAPL RSI = 34.2", tags=["market"])
    cm.pin_fact("NovaGreen: 35%")
    text = cm.get_pinned_text()
    assert "AAPL RSI = 34.2" in text
    assert "NovaGreen: 35%" in text
    assert "[market]" in text
    assert "2/30 slots" in text
