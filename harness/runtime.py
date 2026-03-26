"""Runtime controls — step limits, timeout, cancellation."""

from __future__ import annotations

import time


class RuntimeConfig:
    """Configuration for a single agent run."""

    def __init__(
        self,
        max_steps: int = 20,
        timeout_seconds: int = 120,
        max_retries_per_step: int = 2,
    ) -> None:
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.max_retries_per_step = max_retries_per_step


class RuntimeGuard:
    """Enforces runtime limits during an agent run."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.start_time = time.time()
        self.step_count = 0
        self.cancelled = False

    def check(self) -> str | None:
        """Check if any limit is exceeded. Returns error message or None."""
        if self.cancelled:
            return "Run cancelled by user"

        if self.step_count >= self.config.max_steps:
            return f"Step limit reached ({self.config.max_steps})"

        elapsed = time.time() - self.start_time
        if elapsed > self.config.timeout_seconds:
            return f"Timeout reached ({self.config.timeout_seconds}s)"

        return None

    def increment_step(self) -> None:
        self.step_count += 1

    def cancel(self) -> None:
        self.cancelled = True

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time
