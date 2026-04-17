"""Plan tools — todo_write, todo_update, todo_view.

The plan is a structured task list the model creates for multi-step tasks.
It lives in Zone 1 (always pinned in context) and is persisted as session
events for crash recovery.

Runtime-enforced constraints (not prompt-dependent):
  - Status progression: pending → in_progress → done|blocked
  - Done is done: completed tasks cannot revert
  - Root-goal immutability: first task cannot be deleted
  - Dependency enforcement: can't start a task before deps are done
  - Replan budget: max 3 full todo_write calls per session
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.core.models import ToolDef, ToolGroup, ToolParameter
from tools.base import BuiltinTool


VALID_STATUSES = {"pending", "in_progress", "done", "blocked"}

VALID_TRANSITIONS = {
    "pending": ["in_progress"],
    "in_progress": ["done", "blocked"],
    "blocked": ["in_progress"],
    "done": [],  # terminal
}

VALID_PHASES = {"read", "write", "compute", "verify", "open"}

MAX_CREATES = 3


@dataclass
class PlanTask:
    id: str
    title: str
    status: str = "pending"
    phase: str = "open"
    acceptance: str = ""
    depends_on: list[str] = field(default_factory=list)
    note: str = ""


class PlanManager:
    """Manages the plan state with runtime-enforced constraints."""

    def __init__(self) -> None:
        self.tasks: dict[str, PlanTask] = {}
        self.create_count: int = 0
        self._root_id: str | None = None

    def write(self, tasks: list[dict[str, Any]]) -> str:
        """Create or replace the plan. Enforces done-is-done and root immutability."""
        self.create_count += 1
        if self.create_count > MAX_CREATES:
            return (
                f"Error: replan budget exceeded ({MAX_CREATES} max). "
                "Surface the problem to the user instead of replanning."
            )

        for task_dict in tasks:
            tid = task_dict.get("id", "")
            old = self.tasks.get(tid)
            if old and old.status == "done" and task_dict.get("status") != "done":
                return f"Error: task '{tid}' is already done and cannot be reverted."

        if self._root_id is not None:
            new_ids = {t.get("id") for t in tasks}
            if self._root_id not in new_ids:
                return f"Error: root task '{self._root_id}' cannot be removed from the plan."

        new_tasks: dict[str, PlanTask] = {}
        for task_dict in tasks:
            phase = task_dict.get("phase", "open")
            if phase not in VALID_PHASES:
                phase = "open"
            status = task_dict.get("status", "pending")
            old = self.tasks.get(task_dict["id"])
            if old and old.status == "done":
                status = "done"
            new_tasks[task_dict["id"]] = PlanTask(
                id=task_dict["id"],
                title=task_dict.get("title", ""),
                status=status,
                phase=phase,
                acceptance=task_dict.get("acceptance", ""),
                depends_on=task_dict.get("depends_on", []),
                note=task_dict.get("note", ""),
            )

        self.tasks = new_tasks
        if self._root_id is None and tasks:
            self._root_id = tasks[0]["id"]

        return f"Plan updated: {len(self.tasks)} tasks ({self.create_count}/{MAX_CREATES} creates used)."

    def update(self, task_id: str, status: str, note: str = "") -> str:
        """Update a task's status. Enforces transitions and dependencies."""
        task = self.tasks.get(task_id)
        if task is None:
            return f"Error: unknown task '{task_id}'."

        if status not in VALID_STATUSES:
            return f"Error: invalid status '{status}'. Use: {', '.join(sorted(VALID_STATUSES))}."

        allowed = VALID_TRANSITIONS.get(task.status, [])
        if status not in allowed:
            return f"Error: cannot move '{task_id}' from '{task.status}' to '{status}'."

        if status == "in_progress":
            for dep_id in task.depends_on:
                dep = self.tasks.get(dep_id)
                if dep and dep.status != "done":
                    return f"Error: dependency '{dep_id}' ({dep.title}) must be done first."

        task.status = status
        if note:
            task.note = note
        return f"Task '{task_id}' → {status}."

    def view(self) -> str:
        """Render current plan as markdown."""
        if not self.tasks:
            return "No plan created yet. Call todo_write to create one."

        status_icons = {
            "done": "\u2705",
            "in_progress": "\u23f3",
            "pending": "\u23f8\ufe0f",
            "blocked": "\u26d4",
        }
        lines = [f"## Current Plan ({self.create_count}/{MAX_CREATES} creates used)\n"]
        for task in self.tasks.values():
            icon = status_icons.get(task.status, "?")
            dep_str = ""
            if task.depends_on and task.status in ("pending", "blocked"):
                dep_str = f" (depends: {', '.join(task.depends_on)})"
            acc_str = ""
            if task.acceptance and task.status != "done":
                acc_str = f'\n     acceptance: "{task.acceptance}"'
            note_str = ""
            if task.note:
                note_str = f"\n     note: {task.note}"
            lines.append(f"  {icon} {task.id}: {task.title} [{task.status}]{dep_str}{acc_str}{note_str}")
        return "\n".join(lines)

    def get_in_progress_tasks(self) -> list[PlanTask]:
        return [t for t in self.tasks.values() if t.status == "in_progress"]

    def get_current_phase(self) -> str:
        in_progress = self.get_in_progress_tasks()
        if not in_progress:
            return "open"
        return in_progress[0].phase

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "tasks": [
                {
                    "id": t.id, "title": t.title, "status": t.status,
                    "phase": t.phase, "acceptance": t.acceptance,
                    "depends_on": t.depends_on, "note": t.note,
                }
                for t in self.tasks.values()
            ],
            "create_count": self.create_count,
        }

    def restore_from_events(self, events: list[dict[str, Any]]) -> None:
        """Replay plan events to restore state (used by wake)."""
        for ev in events:
            if ev["type"] == "plan_created":
                payload = ev["payload"]
                self.create_count = payload.get("create_count", self.create_count)
                self.tasks = {}
                for t in payload.get("tasks", []):
                    self.tasks[t["id"]] = PlanTask(**t)
                if not self._root_id and self.tasks:
                    self._root_id = next(iter(self.tasks))
            elif ev["type"] == "plan_task_updated":
                p = ev["payload"]
                task = self.tasks.get(p.get("task_id"))
                if task:
                    task.status = p.get("status", task.status)
                    task.note = p.get("note", task.note)


# ── Tool wrappers ───────────────────────────────────────────────────────


class TodoWriteTool(BuiltinTool):
    name = "todo_write"
    description = (
        "Create or replace the task plan. Each task needs: id, title. "
        "Optional: phase (read/write/compute/verify/open), acceptance (what done looks like), "
        "depends_on (list of task ids). Max 3 creates per session."
    )
    parameters = [
        ToolParameter(
            name="tasks",
            type="string",
            description='JSON array of task objects: [{"id":"t1","title":"Read sources","phase":"read","acceptance":"all files read","depends_on":[]}]',
        ),
    ]
    is_read_only = False
    requires_confirmation = False
    mutates_state = False  # session state, not world state
    tool_group = ToolGroup.ADMIN

    _plan_manager: PlanManager | None = None

    async def execute(self, **kwargs: Any) -> str:
        if self._plan_manager is None:
            return "Error: plan manager not initialized."
        import json
        try:
            tasks = json.loads(kwargs["tasks"])
        except (json.JSONDecodeError, KeyError) as exc:
            return f"Error: invalid tasks JSON: {exc}"
        if not isinstance(tasks, list):
            return "Error: tasks must be a JSON array."
        return self._plan_manager.write(tasks)


class TodoUpdateTool(BuiltinTool):
    name = "todo_update"
    description = (
        "Update a task's status. Valid transitions: "
        "pending→in_progress, in_progress→done|blocked, blocked→in_progress."
    )
    parameters = [
        ToolParameter(name="task_id", type="string", description="Task ID to update"),
        ToolParameter(
            name="status", type="string",
            description="New status",
            enum=["in_progress", "done", "blocked"],
        ),
        ToolParameter(name="note", type="string", description="Optional progress note", required=False),
    ]
    is_read_only = False
    requires_confirmation = False
    mutates_state = False
    tool_group = ToolGroup.ADMIN

    _plan_manager: PlanManager | None = None

    async def execute(self, **kwargs: Any) -> str:
        if self._plan_manager is None:
            return "Error: plan manager not initialized."
        return self._plan_manager.update(
            kwargs["task_id"], kwargs["status"], kwargs.get("note", ""),
        )


class TodoViewTool(BuiltinTool):
    name = "todo_view"
    description = "View the current task plan with statuses."
    parameters = []
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    mutates_state = False
    tool_group = ToolGroup.ADMIN

    _plan_manager: PlanManager | None = None

    async def execute(self, **kwargs: Any) -> str:
        if self._plan_manager is None:
            return "No plan manager available."
        return self._plan_manager.view()


def register_plan_tools(plan_manager: PlanManager) -> list[tuple[ToolDef, Any]]:
    """Create plan tool instances bound to a PlanManager and return (ToolDef, handler) pairs."""
    tools = []
    for cls in (TodoWriteTool, TodoUpdateTool, TodoViewTool):
        instance = cls()
        instance._plan_manager = plan_manager
        tools.append((instance.to_tool_def(), instance.execute))
    return tools
