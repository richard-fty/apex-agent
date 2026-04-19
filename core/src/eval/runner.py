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
from pathlib import Path
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
from agent.runtime.guards import RuntimeConfig
from eval.comparator import (
    compare_against_baseline,
    compare_results,
    format_regression_gate,
    load_baseline,
    save_baseline,
)
from eval.report import generate_report
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
    use_mock: bool = False,
) -> dict[str, Any]:
    """Run a single model x test_case x strategy combination.
    
    Supports LT1 tier: kill at midpoint and wake() for continuation.
    Supports mock mode for CI testing without API costs.
    """
    from agent.runtime.managed_runtime import ManagedAgentRuntime
    from agent.runtime.wake import wake
    from agent.session.archive import SessionArchive
    
    runtime = RuntimeConfig(
        max_steps=test_case.get("max_steps", 20),
        timeout_seconds=timeout,
    )
    
    # Check for LT1 tier (long-task checkpoint/resume)
    tier = test_case.get("tier")
    if tier == "LT1":
        # LT1: Run until midpoint, kill, wake(), continue without duplicate work
        return await _run_lt1(scenario, model, test_case, strategy, runtime, use_mock=use_mock)

    if use_mock:
        # Mock mode: use deterministic responses without real API calls
        return await _run_mock(scenario, model, test_case, strategy, runtime)

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


async def _run_mock(
    scenario: Any,
    model: str,
    test_case: dict[str, Any],
    strategy: str,
    runtime: RuntimeConfig,
) -> dict[str, Any]:
    """Run a test case with mock LLM and mock tool responses (no API calls)."""
    from agent.session.engine import SessionEngine
    from agent.session.archive import SessionArchive
    from agent.runtime.orchestrator import SessionOrchestrator
    from agent.runtime.guards import RuntimeGuard
    from agent.runtime.trace import Trace
    from eval.mock_brain import MockBrain, inject_mock_brain
    from eval.mock_mode import MockToolRegistry
    
    console.print("  [dim]MOCK MODE: Using deterministic responses[/dim]")
    
    # Create archive and session
    archive = SessionArchive()
    session = SessionEngine(model=model, context_strategy=strategy)
    
    # Set up mock tool registry
    mock_registry = MockToolRegistry()
    from eval.mock_brain import MOCK_TOOL_RESPONSES
    for tool_name, response in MOCK_TOOL_RESPONSES.items():
        mock_registry.mock_static(tool_name, response)
    
    # Override session's dispatch with mock responses
    original_execute = session.dispatch.execute
    async def mock_execute(tool_call):
        from eval.mock_brain import get_mock_tool_response
        from agent.core.models import ToolResult
        import time
        
        tool_start = time.time()
        response = get_mock_tool_response(tool_call.name, tool_call.arguments)
        tool_ms = (time.time() - tool_start) * 1000
        
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            content=response,
            success=True,
            summary=response[:240],
        )
    
    # Inject mock execution
    session.dispatch.execute = mock_execute
    
    # Create orchestrator and runtime
    orchestrator = SessionOrchestrator(archive=archive)
    handle = orchestrator.create_runtime(
        session_engine=session,
        model=model,
        runtime_config=runtime,
    )
    
    # Inject mock brain
    inject_mock_brain(handle.runtime, test_case)
    
    # Create trace
    trace = Trace(
        run_id=f"mock_{test_case.get('id', 'unknown')}",
        model=model,
        scenario=scenario.name,
        prompt=test_case["input"],
        context_strategy=strategy,
    )
    
    # Run to completion
    guard = RuntimeGuard(runtime)
    await handle.runtime.run_to_completion(
        user_input=test_case["input"],
        guard=guard,
        trace=trace,
        callback=lambda e: None,
    )
    
    # Evaluate
    score = scenario.evaluate(trace, test_case)
    score["model"] = model
    score["context_strategy"] = strategy
    score["scenario"] = scenario.name
    score["mock_mode"] = True
    
    # Save trace
    trace.save("results")
    
    return score


async def _run_lt1(
    scenario: Any,
    model: str,
    test_case: dict[str, Any],
    strategy: str,
    runtime: RuntimeConfig,
    use_mock: bool = False,
) -> dict[str, Any]:
    """LT1 tier: checkpoint at midpoint, wake(), continue without duplicate work."""
    import tempfile
    from agent.runtime.loop import create_session
    from agent.runtime.guards import RuntimeGuard
    
    mode_str = "MOCK " if use_mock else ""
    console.print(f"  [dim]LT1: {mode_str}Running with checkpoint/resume...[/dim]")
    
    # Create a temporary archive for this LT1 run
    with tempfile.TemporaryDirectory() as tmpdir:
        archive = SessionArchive(db_path=f"{tmpdir}/lt1_archive.db")
        
        # Create initial runtime with archive
        rt = create_session(
            user_input=test_case["input"],
            model=model,
            context_strategy=strategy,
            runtime_config=runtime,
            archive=archive,
        )
        
        # Inject mock components if in mock mode
        if use_mock:
            from eval.mock_brain import inject_mock_brain, get_mock_tool_response
            from agent.core.models import ToolResult
            import time
            
            # Inject mock brain
            inject_mock_brain(rt, test_case)
            
            # Set up mock tool execution
            original_execute = rt.session_engine.dispatch.execute
            async def mock_lt1_execute(tool_call):
                tool_start = time.time()
                response = get_mock_tool_response(tool_call.name, tool_call.arguments)
                tool_ms = (time.time() - tool_start) * 1000
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=response,
                    success=True,
                    summary=response[:240],
                )
            rt.session_engine.dispatch.execute = mock_lt1_execute
        
        max_steps = test_case.get("max_steps", 20)
        kill_step = max_steps // 2  # Kill at midpoint
        
        # Run until kill_step
        step_count = 0
        events_before = []
        
        async for event in rt.start_turn(test_case["input"], guard=RuntimeGuard(runtime)):
            events_before.append(event)
            if event.type == "step":
                step_count = event.data.get("step", 0)
                if step_count >= kill_step:
                    console.print(f"  [dim]LT1: Killing at step {step_count}...[/dim]")
                    break
        
        # Persist state
        rt._persist_session()
        session_id = rt.session.session_id
        
        # Get tool calls before wake
        events_before_wake = archive.get_events(session_id)
        tool_calls_before = [
            e for e in events_before_wake 
            if e.get("type") == "tool_finished"
        ]
        console.print(f"  [dim]LT1: {len(tool_calls_before)} tool calls before wake[/dim]")
        
        # Simulate crash and wake
        rt2 = wake(archive, session_id, runtime_config=runtime)
        
        # Inject mock components into woken runtime if in mock mode
        if use_mock:
            from eval.mock_brain import inject_mock_brain, get_mock_tool_response
            from agent.core.models import ToolResult
            import time
            
            # Inject mock brain with continuation behavior
            inject_mock_brain(rt2, test_case)
            
            # Set up mock tool execution for continuation
            async def mock_lt2_execute(tool_call):
                tool_start = time.time()
                response = get_mock_tool_response(tool_call.name, tool_call.arguments)
                tool_ms = (time.time() - tool_start) * 1000
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    content=response,
                    success=True,
                    summary=response[:240],
                )
            rt2.session_engine.dispatch.execute = mock_lt2_execute
        
        # Continue from where we left off
        events_after = []
        async for event in rt2.start_turn("continue", guard=RuntimeGuard(runtime)):
            events_after.append(event)
        
        # Get final tool calls
        events_after_wake = archive.get_events(session_id)
        tool_calls_after = [
            e for e in events_after_wake 
            if e.get("type") == "tool_finished"
        ]
        
        # Verify no duplicate tool calls
        unique_tools = set()
        duplicates = []
        for tc in tool_calls_after:
            tool_name = tc.get("payload", {}).get("tool_name")
            if tool_name in unique_tools:
                duplicates.append(tool_name)
            unique_tools.add(tool_name)
        
        # Build trace from final state
        from agent.runtime.trace import Trace
        trace = Trace(
            test_case_id=test_case.get("id", "lt1"),
            model=model,
            context_strategy=strategy,
        )
        trace.events = events_after_wake
        trace.outcome = rt2.session.state.value
        trace.step_count = len([e for e in events_after_wake if e.get("type") == "step"])
        
        # Evaluate
        score = scenario.evaluate(trace, test_case)
        score["model"] = model
        score["context_strategy"] = strategy
        score["scenario"] = scenario.name
        score["lt1_checkpoint_step"] = kill_step
        score["lt1_tool_calls_before_wake"] = len(tool_calls_before)
        score["lt1_tool_calls_total"] = len(tool_calls_after)
        score["lt1_duplicate_calls"] = len(duplicates)
        score["lt1_success"] = len(duplicates) == 0 and rt2.session.state.value == "completed"
        
        if duplicates:
            console.print(f"  [bold red]LT1 FAILED: Duplicate tool calls: {duplicates}[/bold red]")
        else:
            console.print(f"  [dim]LT1: Success - {len(tool_calls_after)} total tool calls, no duplicates[/dim]")
        
        trace.save("results")
        return score


async def run_benchmark(
    scenario: Any,
    models: list[str],
    test_cases: list[dict[str, Any]],
    strategies: list[str],
    timeout: int = 300,
    use_mock: bool = False,
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
                    score = await run_single(scenario, model, case, strategy, timeout, use_mock=use_mock)
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
    parser.add_argument(
        "--baseline", default=None,
        help="Path to a saved baseline JSON for regression gating",
    )
    parser.add_argument(
        "--update-baseline", action="store_true",
        help="Write the current results to --baseline after the run completes",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use mock LLM and tool responses (no API calls, for CI testing)",
    )
    args = parser.parse_args()
    
    # Check for mock mode via environment variable or CLI flag
    use_mock = args.mock or os.environ.get("APEX_MOCK_LLM", "").lower() in ("1", "true", "yes")
    if use_mock:
        console.print("[bold yellow]MOCK MODE: Using deterministic responses (no API calls)[/bold yellow]")

    models = [m.strip() for m in args.models.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",")]
    case_ids = [c.strip() for c in args.cases.split(",")] if args.cases else None
    scenario, test_cases = load_test_cases(args.scenario, case_ids)

    if not test_cases:
        console.print("[bold red]No test cases found.[/bold red]")
        return

    # Run benchmark
    results = await run_benchmark(scenario, models, test_cases, strategies, args.timeout, use_mock=use_mock)

    # Print results table
    console.print()
    print_results_table(results)

    # Print comparison if multiple models/strategies
    if len(models) > 1 or len(strategies) > 1:
        console.print()
        comparison = compare_results(results)
        for line in comparison:
            console.print(line)

    if args.baseline:
        console.print()
        baseline = load_baseline(args.baseline) if Path(args.baseline).exists() else []
        gate = compare_against_baseline(results, baseline)
        for line in format_regression_gate(gate):
            console.print(line)
        if args.update_baseline:
            baseline_path = save_baseline(
                results, 
                args.baseline,
                scenario=scenario.name,
                model=models[0] if models else "unknown",
                strategy=strategies[0] if strategies else "unknown"
            )
            console.print(f"[dim]Baseline updated at {baseline_path}[/dim]")
        elif not gate["passed"]:
            raise SystemExit(1)
    elif args.update_baseline:
        raise SystemExit("--update-baseline requires --baseline")

    # Generate and save report
    report_path = generate_report(results, args.output)
    console.print(f"\n[dim]Report saved to {report_path}[/dim]")


if __name__ == "__main__":
    asyncio.run(main())
