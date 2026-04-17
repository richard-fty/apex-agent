"""Apex Agent — CLI entry point with interactive REPL.

Usage:
    uv run python main.py                          # Interactive mode (like Claude Code)
    uv run python main.py "Analyze AAPL"            # Single-shot mode
    uv run python main.py --model deepseek/deepseek-chat "Analyze AAPL"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

# Suppress noisy logs from libraries
logging.basicConfig(level=logging.ERROR)
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

import litellm
litellm.suppress_debug_info = True
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from agent.core.models import TokenUsage
from agent.runtime.shared_runner import SharedTurnRunner
from agent.session.engine import SessionEngine
from agent.policy.access_control import AccessController, AccessPolicy, get_policy, PRESET_POLICIES
from agent.runtime.cost_tracker import CostTracker
from agent.runtime.guards import RuntimeConfig
from config import is_model_available, list_known_models, settings

console = Console()

class AgentSession:
    """Persistent agent session — maintains state across conversation turns."""

    def __init__(
        self,
        model: str,
        context_strategy: str,
        runtime_config: RuntimeConfig,
        access_policy: AccessPolicy | None = None,
        cost_budget: float | None = None,
    ) -> None:
        self.model = model
        self.context_strategy = context_strategy
        self.runtime_config = runtime_config

        self.session_engine = SessionEngine(model=model, context_strategy=context_strategy)
        self.dispatch = self.session_engine.dispatch
        self.skill_loader = self.session_engine.skill_loader
        self.context_mgr = self.session_engine.context_mgr

        # Harness: access control
        self.access_controller = AccessController(
            policy=access_policy or AccessPolicy()
        )

        # Harness: cost tracker
        self.cost_tracker = CostTracker(model=model, budget_usd=cost_budget)
        self.runner = SharedTurnRunner(
            session_engine=self.session_engine,
            access_controller=self.access_controller,
            cost_tracker=self.cost_tracker,
            model=self.model,
            runtime_config=self.runtime_config,
        )

        self.messages = self.session_engine.messages

        # Cumulative metrics
        self.total_usage = TokenUsage()
        self.turn_count = 0

    def _approve_interactively(self) -> str:
        """Prompt the user to approve, deny, or save a session rule."""
        while True:
            choice = console.input(
                "[bold yellow]Approve?[/bold yellow] "
                "[a]pprove once / approve [s]ession / [d]eny / deny ses[s]ion: "
            ).strip().lower()
            if choice in {"a", "approve", "approve_once"}:
                return "approve_once"
            if choice in {"session", "approve_session"}:
                return "approve_session"
            if choice in {"d", "deny"}:
                return "deny"
            if choice in {"ds", "deny_session"}:
                return "deny_session"
            console.print("[dim]Choose: a, session, d, or ds[/dim]")

    async def run_turn(self, user_input: str) -> str | None:
        """Process one user turn — may involve multiple LLM calls + tool calls."""
        self.turn_count += 1
        assistant_content = ""

        async def consume(events: Any) -> bool:
            nonlocal assistant_content
            async for event in events:
                data = event.data
                if event.type == "skill_auto_loaded":
                    continue
                elif event.type == "llm_call_started":
                    console.print(
                        f"[dim]  LLM call (step {data['step']}, "
                        f"{data['message_count']} msgs, "
                        f"{data['tool_count']} tools)...[/dim]"
                    )
                elif event.type == "usage":
                    usage = data["usage"]
                    self.total_usage.prompt_tokens += usage.prompt_tokens
                    self.total_usage.completion_tokens += usage.completion_tokens
                    self.total_usage.total_tokens += usage.total_tokens
                    self.total_usage.cost_usd += usage.cost_usd
                    console.print(
                        f"[dim]  Response in {data['duration_ms']:.0f}ms "
                        f"(in:{usage.prompt_tokens} out:{usage.completion_tokens} "
                        f"${usage.cost_usd:.4f})[/dim]"
                    )
                elif event.type == "assistant_note":
                    if data["text"]:
                        console.print(f"\n{data['text']}")
                elif event.type == "tool_started":
                    args_short = ", ".join(f"{k}={repr(v)[:40]}" for k, v in data["arguments"].items())
                    console.print(f"  [yellow]● {data['name']}[/yellow]({args_short})")
                elif event.type == "tool_denied":
                    console.print(f"  [red]✗[/red] {data['reason']}")
                elif event.type == "tool_finished":
                    icon = "[green]✓[/green]" if data["success"] else "[red]✗[/red]"
                    preview = data["content"][:100].replace("\n", " ")
                    console.print(f"  {icon} ({data['duration_ms']:.0f}ms) {preview}")
                elif event.type == "approval_requested":
                    console.print(
                        f"  [yellow]?[/yellow] approval needed for "
                        f"[bold]{data['tool_name']}[/bold]: {data['reason']}"
                    )
                    resolution = self._approve_interactively()
                    return await consume(self.runner.resume_pending(resolution))
                elif event.type == "turn_finished":
                    assistant_content = data["content"] or assistant_content
                    return True
                elif event.type == "error":
                    console.print(f"\n[bold red]{data['message']}[/bold red]")
                    return False
            return True

        await consume(self.runner.start_turn(user_input))
        return assistant_content or None

    def print_status(self) -> None:
        """Print session status bar."""
        loaded = self.skill_loader.get_loaded_skill_names()
        skills_str = ", ".join(loaded) if loaded else "none"
        denied = len(self.access_controller.denied_calls)
        denied_str = f" | [red]Denied: {denied}[/red]" if denied else ""
        budget_str = ""
        if self.cost_tracker.budget_usd is not None:
            remaining = self.cost_tracker.budget_usd - self.cost_tracker.total_cost_usd
            budget_str = f" | Budget: ${remaining:.4f} left"
        console.print(
            f"[dim]Model: {self.model} | "
            f"Skills: {skills_str} | "
            f"Turns: {self.turn_count} | "
            f"Tokens: {self.total_usage.total_tokens} | "
            f"Cost: ${self.cost_tracker.total_cost_usd:.4f}"
            f"{budget_str}{denied_str}[/dim]"
        )

    def print_models(self) -> None:
        """Print known models and whether their API keys are configured."""
        table = Table(title="Models", border_style="blue")
        table.add_column("Model", style="bold")
        table.add_column("Status")
        table.add_column("Requirement")
        for model in list_known_models():
            available, required_env = is_model_available(model)
            status = "[green]ready[/green]" if available else "[yellow]missing key[/yellow]"
            requirement = required_env or "-"
            label = f"{model} [dim](current)[/dim]" if model == self.model else model
            table.add_row(label, status, requirement)
        console.print(table)

    def switch_model(self, model: str) -> tuple[bool, str]:
        """Switch to a new model if the required provider key is available."""
        available, required_env = is_model_available(model)
        if not available:
            return False, f"Model '{model}' requires {required_env}."

        self.model = model
        self.session_engine = SessionEngine(model=model, context_strategy=self.context_strategy)
        self.dispatch = self.session_engine.dispatch
        self.skill_loader = self.session_engine.skill_loader
        self.context_mgr = self.session_engine.context_mgr
        self.cost_tracker = CostTracker(model=model, budget_usd=self.cost_tracker.budget_usd)
        self.runner = SharedTurnRunner(
            session_engine=self.session_engine,
            access_controller=self.access_controller,
            cost_tracker=self.cost_tracker,
            model=self.model,
            runtime_config=self.runtime_config,
        )
        self.messages = self.session_engine.messages
        return True, f"Model → {model}"


async def interactive_mode(
    model: str,
    strategy: str,
    runtime: RuntimeConfig,
    access_policy: AccessPolicy | None = None,
    cost_budget: float | None = None,
) -> None:
    """Interactive REPL — chat with the agent like Claude Code."""
    policy_name = "custom" if access_policy and access_policy.blocked_tools else "unrestricted"
    budget_str = f"${cost_budget:.2f}" if cost_budget else "unlimited"
    console.print(Panel(
        f"[bold]Apex Agent[/bold] — Interactive Mode\n"
        f"Model: {model} | Strategy: {strategy}\n"
        f"Policy: {policy_name} | Budget: {budget_str}\n"
        f"Commands: /status, /skills, /models, /model <name>, /costs, /access, /quit",
        border_style="magenta",
    ))

    session = AgentSession(model, strategy, runtime, access_policy, cost_budget)

    while True:
        try:
            console.print()
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye.[/dim]")
            break
        elif user_input.lower() == "/status":
            session.print_status()
            continue
        elif user_input.lower() == "/skills":
            loaded = session.skill_loader.get_loaded_skill_names()
            available = session.skill_loader.get_available_skill_names()
            console.print(f"Available: {', '.join(available)}")
            console.print(f"Loaded: {', '.join(loaded) if loaded else 'none'}")
            continue
        elif user_input.lower() == "/models":
            session.print_models()
            continue
        elif user_input.lower().startswith("/model"):
            _, _, arg = user_input.partition(" ")
            arg = arg.strip()
            if not arg:
                console.print(f"Current: {session.model}")
            else:
                ok, message = session.switch_model(arg)
                console.print(message if ok else f"[red]{message}[/red]")
            continue
        elif user_input.lower() == "/costs":
            summary = session.cost_tracker.summary()
            table = Table(title="Cost Summary", border_style="blue")
            table.add_column("Metric", style="bold")
            table.add_column("Value")
            for k, v in summary.items():
                table.add_row(k, str(v))
            console.print(table)
            continue
        elif user_input.lower() == "/access":
            summary = session.access_controller.summary()
            console.print(f"Total calls: {summary['total_calls']}")
            console.print(f"Call counts: {summary['call_counts']}")
            if summary['denied_calls']:
                console.print(f"[red]Denied: {summary['denied_calls']}[/red]")
            else:
                console.print("No denied calls")
            continue

        # Run agent turn
        console.print()
        output = await session.run_turn(user_input)

        if output:
            console.print()
            console.print(Panel(
                Markdown(output),
                title="[bold green]Agent[/bold green]",
                border_style="green",
            ))

        session.print_status()


async def single_shot_mode(
    prompt: str,
    model: str,
    strategy: str,
    runtime: RuntimeConfig,
    access_policy: AccessPolicy | None = None,
    cost_budget: float | None = None,
) -> None:
    """Single-shot mode — one prompt, one response."""
    available, required_env = is_model_available(model)
    if not available:
        console.print(f"[red]Model '{model}' requires {required_env}.[/red]")
        return
    console.print(Panel(f"[bold]{prompt}[/bold]", title="[bold magenta]Apex Agent[/bold magenta]", border_style="magenta"))

    session = AgentSession(model, strategy, runtime, access_policy, cost_budget)
    output = await session.run_turn(prompt)

    if output:
        console.print()
        console.print(Panel(
            Markdown(output),
            title="[bold green]Agent Output[/bold green]",
            border_style="green",
        ))

    session.print_status()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Apex Agent CLI")
    parser.add_argument("prompt", nargs="?", default=None, help="User prompt (omit for interactive mode)")
    parser.add_argument("--model", "-m", default=settings.default_model, help="LiteLLM model ID")
    parser.add_argument("--strategy", "-s", default=settings.context_strategy, help="Context strategy")
    parser.add_argument("--max-steps", type=int, default=settings.max_steps, help="Max steps per turn")
    parser.add_argument("--timeout", type=int, default=settings.timeout_seconds, help="Timeout per turn")
    parser.add_argument("--policy", "-p", default="unrestricted",
                        help=f"Access policy: {', '.join(PRESET_POLICIES.keys())}")
    parser.add_argument("--budget", type=float, default=None,
                        help="Cost budget in USD (e.g. 0.05)")
    args = parser.parse_args()

    runtime = RuntimeConfig(max_steps=args.max_steps, timeout_seconds=args.timeout)
    access_policy = get_policy(args.policy)

    if args.prompt:
        await single_shot_mode(args.prompt, args.model, args.strategy, runtime, access_policy, args.budget)
    else:
        await interactive_mode(args.model, args.strategy, runtime, access_policy, args.budget)


if __name__ == "__main__":
    asyncio.run(main())
