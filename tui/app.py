"""Apex Agent TUI — clean, minimal design inspired by Claude Code.

No color borders. No labels. Clean whitespace. Spinner above prompt while thinking.

Usage:
    uv run python -m tui.app
    uv run python -m tui.app --model gpt-4o --budget 0.05
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

_DEBUG = os.environ.get("APEX_DEBUG", "").lower() in ("1", "true", "yes")
_ROOT_LEVEL = logging.DEBUG if _DEBUG else logging.ERROR
_NOISY_LEVEL = logging.INFO if _DEBUG else logging.ERROR
if _DEBUG:
    # Route logs to the Textual devtools console only — do NOT write to stderr,
    # which would leak onto the TUI screen.
    from textual.logging import TextualHandler
    logging.basicConfig(level=_ROOT_LEVEL, handlers=[TextualHandler()], force=True)
else:
    logging.basicConfig(level=_ROOT_LEVEL)
logging.getLogger("LiteLLM").setLevel(_NOISY_LEVEL)
logging.getLogger("httpx").setLevel(_NOISY_LEVEL)

from rich.markdown import Markdown
from rich.text import Text
from rich.table import Table

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Input, Static
from textual.reactive import reactive
from textual.timer import Timer

from agent.core.models import TokenUsage
from agent.runtime.shared_runner import RunnerEvent, SessionEventStream, SharedTurnRunner
from agent.session.engine import SessionEngine
from agent.policy.access_control import AccessController, get_policy
from agent.runtime.cost_tracker import CostTracker
from agent.runtime.guards import RuntimeConfig
from config import is_model_available, list_known_models, settings

_SKILL_MUTATING_TOOLS = {"load_skill", "unload_skill"}

# Spinner frames for the thinking indicator
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ThinkingIndicator(Static):
    """Animated spinner shown above the prompt while the agent is working."""

    DEFAULT_CSS = """
    ThinkingIndicator {
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """

    _frame = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._timer: Timer | None = None
        self._message = ""
        self._visible = False

    def show(self, message: str = "Thinking") -> None:
        self._message = message
        self._visible = True
        self._frame = 0
        self._timer = self.set_interval(0.08, self._tick)
        self._render_frame()

    def hide(self) -> None:
        self._visible = False
        if self._timer:
            self._timer.stop()
            self._timer = None
        self.update("")

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(_SPINNER_FRAMES)
        self._render_frame()

    def _render_frame(self) -> None:
        if self._visible:
            frame = _SPINNER_FRAMES[self._frame]
            self.update(f"  {frame} {self._message}")


class StreamingMarkdown(Static):
    """Re-renders markdown at throttled rate (~12fps) as tokens accumulate."""

    DEFAULT_CSS = """
    StreamingMarkdown {
        padding: 0 2;
        margin: 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buffer = ""
        self._dirty = False
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.08, self._flush)

    def _flush(self) -> None:
        if self._dirty and self._buffer.strip():
            try:
                self.update(Markdown(self._buffer))
            except Exception:
                self.update(self._buffer)
            self._dirty = False

    def append_token(self, token: str) -> None:
        self._buffer += token
        self._dirty = True

    def finalize(self) -> None:
        if self._timer:
            self._timer.stop()
        if self._buffer.strip():
            try:
                self.update(Markdown(self._buffer))
            except Exception:
                self.update(self._buffer)

    @property
    def full_text(self) -> str:
        return self._buffer


class MainOutput(VerticalScroll):
    """Main output — clean scrollable area. No borders, no chrome."""

    DEFAULT_CSS = """
    MainOutput {
        height: 1fr;
        padding: 0;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._streaming_widget: StreamingMarkdown | None = None

    def _append(self, widget: Static) -> None:
        self.mount(widget)
        self.scroll_end(animate=False)

    def user_msg(self, text: str) -> None:
        self._append(Static(
            Text.from_markup(f"\n[bold]You[/bold]  {text}\n"),
            classes="user-msg",
        ))

    def divider(self) -> None:
        self._append(Static(Text.from_markup("  [dim]···[/dim]"), classes="info"))

    def agent_thinking(self, text: str) -> None:
        if text:
            self._append(Static(
                Text.from_markup(f"[dim]{text}[/dim]"),
                classes="thinking",
            ))

    def stream_start(self) -> None:
        self._streaming_widget = StreamingMarkdown()
        self._append(self._streaming_widget)

    def stream_token(self, token: str) -> None:
        if self._streaming_widget is not None:
            self._streaming_widget.append_token(token)
            self.scroll_end(animate=False)

    def stream_end(self, full_text: str) -> None:
        if self._streaming_widget is not None:
            self._streaming_widget.finalize()
            self._streaming_widget = None
        self._append(Static(Text("")))

    def tool_call(self, name: str, args: dict, success: bool, duration_ms: float, preview: str) -> None:
        icon = "✓" if success else "✗"
        args_short = ", ".join(f"{k}={repr(v)[:28]}" for k, v in args.items()) or "no args"
        preview = preview.strip().replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:100] + "..."
        text = Text()
        text.append("\n  ")
        text.append(icon, style="green" if success else "red")
        text.append(f" {name}", style="bold")
        text.append(f" · {duration_ms:.0f}ms", style="dim")
        text.append("\n  ")
        text.append("args:", style="dim")
        text.append(f" {args_short}")
        text.append("\n  ")
        if preview:
            text.append(preview)
        else:
            text.append("No output", style="dim")
        text.append("\n")
        self._append(Static(text, classes="tool-call"))

    def tool_denied(self, name: str, reason: str) -> None:
        self._append(Static(Text.from_markup(
            f"\n  [red]⊘[/red] [bold]{name}[/bold]\n"
            f"  [dim]{reason}[/dim]\n"
        ), classes="tool-call"))

    def approval_card(self, tool_name: str, reason: str) -> None:
        self._append(Static(Text.from_markup(
            "\n"
            "  [bold yellow]Approval needed[/bold yellow]\n"
            f"  [bold]{tool_name}[/bold]\n"
            f"  [dim]{reason}[/dim]\n"
            "\n"
            "  [dim]/approve once  /approve_session  /deny  /deny_session[/dim]\n"
        ), classes="approval-card"))

    def info(self, text: str) -> None:
        self._append(Static(Text.from_markup(f"[dim]{text}[/dim]"), classes="info"))

    def system_msg(self, text: str) -> None:
        self._append(Static(Text.from_markup(f"\n[dim]{text}[/dim]\n"), classes="system"))

    def error_msg(self, text: str) -> None:
        self._append(Static(Text.from_markup(f"\n[red]{text}[/red]\n"), classes="error"))

    def show_metrics(self, model: str, strategy: str, turns: int, usage: TokenUsage,
                     cost: float, budget: float | None, skills: list[str], denied: int) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("", style="dim", width=14)
        table.add_column("")

        model_short = model.split("/")[-1] if "/" in model else model
        table.add_row("Model", model_short)
        table.add_row("Strategy", strategy)
        table.add_row("Turns", str(turns))
        table.add_row("Tokens", f"{usage.total_tokens:,}")
        table.add_row("Cost", f"${cost:.4f}")
        if budget is not None:
            table.add_row("Budget left", f"${budget - cost:.4f}")
        table.add_row("Skills", ", ".join(skills) if skills else "none")
        if denied:
            table.add_row("Denied", str(denied))

        self._append(Static(table))
        self._append(Static(Text("")))

    def show_models(self, current_model: str) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("", style="dim", width=36)
        table.add_column("")
        for model in list_known_models():
            available, required_env = is_model_available(model)
            status = "ready" if available else f"missing {required_env}"
            label = f"{model} (current)" if model == current_model else model
            table.add_row(label, status)
        self._append(Static(table))
        self._append(Static(Text("")))


class StatusBar(Static):
    """Minimal prompt-adjacent status line."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        color: $text-muted;
        padding: 0 2;
    }
    """

    def set(self, model: str, cost: float, tokens: int, skills: list[str], app_name: str) -> None:
        model_short = model.split("/")[-1] if "/" in model else model
        parts = [model_short, app_name, f"${cost:.4f}", f"{tokens:,} tokens"]
        if skills:
            parts.append(f"skills: {', '.join(skills)}")
        self.update(" · ".join(parts))


class ApprovalSelector(Static):
    """Prompt replacement used while waiting for approval."""

    DEFAULT_CSS = """
    ApprovalSelector {
        height: auto;
        padding: 0 2 1 2;
        color: $text;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._options: list[tuple[str, str]] = [
            ("approve_once", "Allow once"),
            ("approve_session", "Allow session"),
            ("deny", "Deny"),
            ("deny_session", "Deny session"),
        ]
        self._selected = 0
        self.display = False
        self._tool_name = ""
        self._reason = ""

    def show_request(self, tool_name: str, reason: str) -> None:
        self._tool_name = tool_name
        self._reason = reason
        self._selected = 0
        self.display = True
        self._refresh_content()

    def clear_request(self) -> None:
        self.display = False
        self._tool_name = ""
        self._reason = ""
        self.update("")

    def move_selection(self, delta: int) -> None:
        self._selected = (self._selected + delta) % len(self._options)
        self._refresh_content()

    def selected_action(self) -> str:
        return self._options[self._selected][0]

    def _refresh_content(self) -> None:
        lines = [
            f"[bold yellow]Approval needed[/bold yellow]  [bold]{self._tool_name}[/bold]",
            f"[dim]{self._reason}[/dim]",
            "[dim]Use left/right to choose, Enter to confirm.[/dim]",
        ]
        option_lines = []
        hotkeys = {
            "approve_once": "Y",
            "approve_session": "S",
            "deny": "N",
            "deny_session": "D",
        }
        for index, (action, label) in enumerate(self._options):
            marker = "›" if index == self._selected else " "
            style = "bold" if index == self._selected else "dim"
            option_lines.append(
                f"[{style}]{marker} [{hotkeys[action]}] {label}[/{style}]"
            )
        lines.append("  ".join(option_lines))
        self.update(Text.from_markup("\n".join(lines)))


class SlashCommandMenu(Static):
    """Lightweight slash command picker."""

    DEFAULT_CSS = """
    SlashCommandMenu {
        height: auto;
        padding: 0 2;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._commands: list[tuple[str, str]] = []
        self._selected = 0

    def show_commands(self, commands: list[tuple[str, str]], selected: int = 0) -> None:
        self._commands = commands
        self._selected = max(0, min(selected, len(commands) - 1)) if commands else 0
        if not commands:
            self.update("")
            return
        lines = []
        for index, (name, desc) in enumerate(commands[:8]):
            marker = "›" if index == self._selected else " "
            style = "bold" if index == self._selected else "dim"
            lines.append(f"[{style}]{marker} {name}[/{style}] [dim]{desc}[/dim]")
        self.update(Text.from_markup("\n".join(lines)))

    def clear_commands(self) -> None:
        self._commands = []
        self._selected = 0
        self.update("")

    def move_selection(self, delta: int) -> None:
        if not self._commands:
            return
        self._selected = (self._selected + delta) % len(self._commands[:8])
        self.show_commands(self._commands, self._selected)

    def selected_command(self) -> str | None:
        if not self._commands:
            return None
        return self._commands[self._selected][0]


class ApexAgentApp(App):
    """Clean, minimal TUI — inspired by Claude Code."""

    TITLE = "Apex Agent"
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }

    .user-msg {
        padding: 0 2;
    }

    .thinking {
        padding: 0 2;
    }

    .tool-call {
        padding: 0 2 0 2;
    }

    .info {
        padding: 0 2;
    }

    .system {
        padding: 0 2;
    }

    .error {
        padding: 0 2;
    }

    .approval-card {
        padding: 0 2;
    }

    #composer {
        height: auto;
        padding: 0 0 1 0;
        background: $background;
    }

    #prompt-input {
        margin: 0 2;
        border: none;
        background: $surface;
        padding: 0 1;
        color: $text;
    }

    #prompt-input:focus {
        border: none;
    }

    Footer {
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
    ]

    def __init__(
        self,
        model: str = "",
        strategy: str = "truncate",
        policy: str = "unrestricted",
        budget: float | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model = model or settings.default_model
        self._strategy = strategy
        self._policy_name = policy
        self._budget = budget
        self._init_session()

    def _init_session(self) -> None:
        self._session_engine = SessionEngine(model=self._model, context_strategy=self._strategy)
        self._dispatch = self._session_engine.dispatch
        self._skill_loader = self._session_engine.skill_loader
        self._context_mgr = self._session_engine.context_mgr
        self._access = AccessController(policy=get_policy(self._policy_name))
        self._cost_tracker = CostTracker(model=self._model, budget_usd=self._budget)
        self._runner = SharedTurnRunner(
            session_engine=self._session_engine,
            access_controller=self._access,
            cost_tracker=self._cost_tracker,
            model=self._model,
            runtime_config=RuntimeConfig(
                max_steps=settings.max_steps,
                timeout_seconds=settings.timeout_seconds,
            ),
        )
        self._total_usage = TokenUsage()
        self._turn_count = 0
        self._messages = self._session_engine.messages
        self._slash_commands: list[tuple[str, str]] = [
            ("/help", "show available commands"),
            ("/models", "list models and key readiness"),
            ("/model", "switch model"),
            ("/strategy", "switch context strategy"),
            ("/policy", "switch permission mode"),
            ("/skills", "show loaded and available skills"),
            ("/metrics", "show session metrics"),
            ("/reset", "reset the session"),
            ("/quit", "exit Apex Agent"),
        ]

    def compose(self) -> ComposeResult:
        yield MainOutput(id="main-output")
        with Container(id="composer"):
            yield ThinkingIndicator(id="thinking")
            yield ApprovalSelector(id="approval-selector")
            yield SlashCommandMenu(id="slash-menu")
            yield Input(placeholder="Ask Apex Agent anything or type /help", id="prompt-input")
            yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        self._update_status()
        self.query_one("#prompt-input", Input).focus()
        self._show_welcome()

    def _set_prompt_mode(self, mode: str) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        approval = self.query_one("#approval-selector", ApprovalSelector)
        slash_menu = self.query_one("#slash-menu", SlashCommandMenu)
        if mode == "approval":
            input_widget.display = False
            slash_menu.display = False
            approval.display = True
        else:
            approval.clear_request()
            approval.display = False
            input_widget.display = True
            slash_menu.display = True
            input_widget.focus()

    def _show_welcome(self) -> None:
        output = self.query_one("#main-output", MainOutput)
        model_short = self._model.split("/")[-1] if "/" in self._model else self._model

        output._append(Static(Text.from_markup(
            "\n"
            "  [bold]Apex Agent[/bold]\n"
            "\n"
            "  A personal terminal agent for research, files, shell, and the web.\n"
            "\n"
            f"  [dim]Model[/dim]   {model_short}\n"
            f"  [dim]Policy[/dim]  {self._policy_name}\n"
            "\n"
            "  [dim]Start with a question, or try:[/dim]\n"
            "  [dim]  summarize this repo[/dim]\n"
            "  [dim]  find where context is assembled[/dim]\n"
            "  [dim]  /help[/dim]\n"
        )))
        output.divider()

    def _update_status(self) -> None:
        self.query_one("#status-bar", StatusBar).set(
            self._model,
            self._cost_tracker.total_cost_usd,
            self._total_usage.total_tokens,
            self._skill_loader.get_loaded_skill_names(),
            "Apex Agent",
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if text.startswith("/"):
            await self._handle_command(text)
            return

        self.query_one("#main-output", MainOutput).user_msg(text)
        self._run_agent_turn(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        menu = self.query_one("#slash-menu", SlashCommandMenu)
        value = event.value.strip()
        if not value.startswith("/"):
            menu.clear_commands()
            return
        matches = [item for item in self._slash_commands if item[0].startswith(value) or value in item[0]]
        menu.show_commands(matches)

    def on_key(self, event) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        approval = self.query_one("#approval-selector", ApprovalSelector)
        menu = self.query_one("#slash-menu", SlashCommandMenu)

        if self._access.pending is not None:
            action_map = {
                "y": "approve_once",
                "s": "approve_session",
                "n": "deny",
                "d": "deny_session",
            }
            action = action_map.get(event.key)
            if action:
                approval.clear_request()
                event.prevent_default()
                self._resume_after_approval(action)
                return
            if event.key == "right":
                approval.move_selection(1)
                event.prevent_default()
                return
            if event.key == "left":
                approval.move_selection(-1)
                event.prevent_default()
                return
            if event.key == "enter":
                event.prevent_default()
                self._resume_after_approval(approval.selected_action())
                return

        if input_widget.display and input_widget.has_focus and input_widget.value.strip().startswith("/"):
            if event.key == "down":
                menu.move_selection(1)
                event.prevent_default()
                return
            if event.key == "up":
                menu.move_selection(-1)
                event.prevent_default()
                return
            if event.key == "tab":
                selected = menu.selected_command()
                if selected:
                    input_widget.value = selected + " "
                    menu.clear_commands()
                    input_widget.cursor_position = len(input_widget.value)
                event.prevent_default()
                return
            if event.key == "enter":
                selected = menu.selected_command()
                if selected and input_widget.value.strip() != selected:
                    input_widget.value = selected + " "
                    menu.clear_commands()
                    input_widget.cursor_position = len(input_widget.value)
                    event.prevent_default()
                    return

    @work(exclusive=True)
    async def _run_agent_turn(self, user_input: str) -> None:
        output = self.query_one("#main-output", MainOutput)
        thinking = self.query_one("#thinking", ThinkingIndicator)
        input_widget = self.query_one("#prompt-input", Input)
        approval = self.query_one("#approval-selector", ApprovalSelector)
        slash_menu = self.query_one("#slash-menu", SlashCommandMenu)

        self._set_prompt_mode("input")
        input_widget.disabled = True
        approval.clear_request()
        slash_menu.clear_commands()
        thinking.show("Thinking")

        self._turn_count += 1
        after = self._runner.start_turn_background(user_input)
        await self._consume_runner_events(
            SessionEventStream(
                self._runner.archive,
                self._runner.session_id,
            ).stream(
                after=after,
                stop_states={"waiting_approval", "completed", "failed", "cancelled"},
            ),
            output,
            thinking,
            input_widget,
        )

    @work(exclusive=True)
    async def _resume_after_approval(self, action: str) -> None:
        output = self.query_one("#main-output", MainOutput)
        thinking = self.query_one("#thinking", ThinkingIndicator)
        input_widget = self.query_one("#prompt-input", Input)
        approval = self.query_one("#approval-selector", ApprovalSelector)

        self._set_prompt_mode("input")
        input_widget.disabled = True
        approval.clear_request()
        thinking.show("Resuming after approval")
        after = self._runner.resume_pending_background(action)
        await self._consume_runner_events(
            SessionEventStream(
                self._runner.archive,
                self._runner.session_id,
            ).stream(
                after=after,
                stop_states={"waiting_approval", "completed", "failed", "cancelled"},
            ),
            output,
            thinking,
            input_widget,
        )

    async def _consume_runner_events(
        self,
        events: Any,
        output: MainOutput,
        thinking: ThinkingIndicator,
        input_widget: Input,
    ) -> None:
        streaming_started = False
        approval = self.query_one("#approval-selector", ApprovalSelector)
        try:
            async for event in events:
                event = event if isinstance(event, RunnerEvent) else RunnerEvent("error", {"message": "Invalid event"})
                data = event.data

                if event.type == "skill_auto_loaded":
                    self._update_status()
                elif event.type == "research_started":
                    thinking.show("Preparing research context")
                elif event.type == "local_search_started":
                    thinking.show("Checking local knowledge")
                elif event.type == "web_search_started":
                    thinking.show("Searching the web")
                elif event.type == "evidence_ready":
                    sources = []
                    if data["used_local"]:
                        sources.append("local")
                    if data["used_web"]:
                        sources.append("web")
                    source_text = ", ".join(sources) if sources else "none"
                    output.info(f"  Research context ready: {data['items']} evidence item(s) from {source_text}")
                elif event.type == "llm_call_started":
                    thinking.show(f"Calling model (step {data['step']})")
                elif event.type == "token":
                    if not streaming_started:
                        thinking.hide()
                        output.stream_start()
                        streaming_started = True
                    output.stream_token(data["text"])
                elif event.type == "usage":
                    usage = data["usage"]
                    self._total_usage.prompt_tokens += usage.prompt_tokens
                    self._total_usage.completion_tokens += usage.completion_tokens
                    self._total_usage.total_tokens += usage.total_tokens
                    self._update_status()
                elif event.type == "assistant_note":
                    if streaming_started:
                        output.stream_end(data["text"])
                        streaming_started = False
                    else:
                        output.agent_thinking(data["text"])
                elif event.type == "tool_started":
                    thinking.show(f"Running {data['name']}")
                elif event.type == "tool_denied":
                    thinking.hide()
                    output.tool_denied(data["name"], data["reason"])
                elif event.type == "approval_requested":
                    thinking.hide()
                    if streaming_started:
                        output.stream_end("")
                        streaming_started = False
                    self._set_prompt_mode("approval")
                    approval.show_request(data["tool_name"], data["reason"])
                    return
                elif event.type == "tool_finished":
                    thinking.hide()
                    output.tool_call(
                        data["name"],
                        data["arguments"],
                        data["success"],
                        data["duration_ms"],
                        data["content"][:100],
                    )
                elif event.type == "turn_finished":
                    if streaming_started:
                        output.stream_end(data["content"])
                        streaming_started = False
                    elif data["content"]:
                        output.stream_start()
                        output.stream_token(data["content"])
                        output.stream_end(data["content"])
                    output.divider()
                    break
                elif event.type == "error":
                    thinking.hide()
                    if streaming_started:
                        output.stream_end("")
                        streaming_started = False
                    output.error_msg(data["message"])
                    break
        except Exception as e:
            output.error_msg(str(e))
        finally:
            thinking.hide()
            if self._access.pending is None:
                self._set_prompt_mode("input")
            self._update_status()
            input_widget.disabled = False
            if input_widget.display:
                input_widget.focus()

    async def _handle_command(self, command: str) -> None:
        output = self.query_one("#main-output", MainOutput)
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            output.system_msg(
                "/model <name>      Switch model\n"
                "/models            List known models and key readiness\n"
                "/strategy <name>   Context strategy (truncate, summary, tiered)\n"
                "/policy <name>     Access policy (plan, default, accept_edits, auto, dont_ask, readonly, no_shell)\n"
                "/approve           Approve pending action once\n"
                "/approve_session   Approve pending action for this session\n"
                "/deny              Deny pending action\n"
                "/deny_session      Deny pending action for this session\n"
                "/budget <amount>   Set cost budget in USD\n"
                "/skills            List skills\n"
                "/metrics           Show session metrics\n"
                "/clear             Clear output\n"
                "/reset             Reset session\n"
                "/quit              Exit\n"
                "\n"
                "Ctrl+C quit · Ctrl+L clear"
            )
        elif cmd == "/model":
            if not arg:
                output.system_msg(f"Current: {self._model}")
            else:
                available, required_env = is_model_available(arg)
                if not available:
                    output.error_msg(f"Model '{arg}' requires {required_env}")
                    return
                self._model = arg
                self._init_session()
                output.system_msg(f"Model → {self._model}")
                self._update_status()
        elif cmd == "/models":
            output.show_models(self._model)
        elif cmd == "/strategy":
            if not arg:
                output.system_msg(f"Current: {self._strategy}")
            elif arg in ("truncate", "summary", "tiered"):
                self._strategy = arg
                self._init_session()
                output.system_msg(f"Strategy → {arg}")
            else:
                output.error_msg(f"Unknown: {arg}. Use truncate, summary, tiered")
        elif cmd == "/policy":
            if not arg:
                output.system_msg(f"Current: {self._policy_name}")
            else:
                try:
                    self._access = AccessController(policy=get_policy(arg))
                    self._policy_name = arg
                    self._runner.access_controller = self._access
                    output.system_msg(f"Policy → {arg}")
                except ValueError as e:
                    output.error_msg(str(e))
        elif cmd in {"/approve", "/approve_session", "/deny", "/deny_session"}:
            action_map = {
                "/approve": "approve_once",
                "/approve_session": "approve_session",
                "/deny": "deny",
                "/deny_session": "deny_session",
            }
            if self._access.pending is None:
                output.error_msg("No pending approval")
            else:
                self.query_one("#approval-selector", ApprovalSelector).clear_request()
                self._resume_after_approval(action_map[cmd])
        elif cmd == "/budget":
            if not arg:
                if self._budget:
                    output.system_msg(f"Budget: ${self._budget:.4f} (${self._budget - self._cost_tracker.total_cost_usd:.4f} left)")
                else:
                    output.system_msg("No budget set")
            else:
                try:
                    self._budget = float(arg)
                    self._cost_tracker.budget_usd = self._budget
                    output.system_msg(f"Budget → ${self._budget:.4f}")
                except ValueError:
                    output.error_msg(f"Invalid: {arg}")
        elif cmd == "/skills":
            loaded = self._skill_loader.get_loaded_skill_names()
            available = self._skill_loader.get_available_skill_names()
            output.system_msg(
                f"Available: {', '.join(available) or 'none'}\n"
                f"Loaded: {', '.join(loaded) or 'none'}"
            )
        elif cmd == "/metrics":
            output.show_metrics(
                self._model, self._strategy, self._turn_count,
                self._total_usage, self._cost_tracker.total_cost_usd,
                self._budget, self._skill_loader.get_loaded_skill_names(),
                len(self._access.denied_calls),
            )
        elif cmd == "/costs":
            summary = self._cost_tracker.summary()
            lines = "\n".join(f"  {k}: {v}" for k, v in summary.items())
            output.system_msg(f"Cost Summary\n{lines}")
        elif cmd == "/clear":
            self.query_one("#main-output", MainOutput).remove_children()
        elif cmd == "/reset":
            self._init_session()
            self.query_one("#main-output", MainOutput).remove_children()
            output = self.query_one("#main-output", MainOutput)
            output.system_msg("Session reset")
            self._update_status()
        elif cmd in ("/quit", "/exit", "/q"):
            self.exit()
        else:
            output.error_msg(f"Unknown: {cmd}. Type /help")

    def action_clear(self) -> None:
        self.query_one("#main-output", MainOutput).remove_children()

    def action_quit(self) -> None:
        self.exit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apex Agent TUI")
    parser.add_argument("--model", "-m", default=settings.default_model)
    parser.add_argument("--strategy", "-s", default=settings.context_strategy)
    parser.add_argument("--policy", "-p", default="unrestricted")
    parser.add_argument("--budget", type=float, default=None)
    args = parser.parse_args()

    app = ApexAgentApp(
        model=args.model, strategy=args.strategy,
        policy=args.policy, budget=args.budget,
    )
    app.run()


if __name__ == "__main__":
    main()
