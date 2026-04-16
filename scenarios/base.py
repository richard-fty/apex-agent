"""Base class for benchmark scenarios."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.core.models import ToolDef
from harness.trace import Trace


class TestCase(ABC):
    """A single benchmark test case."""
    input: str
    expected_tools: list[str]
    metadata: dict[str, Any]


class Score(ABC):
    """Result of evaluating a trace against a test case."""
    value: float  # 0.0 to 1.0
    details: dict[str, Any]


class Scenario(ABC):
    """A benchmark scenario — defines tools, test cases, and evaluation."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def get_skill_names(self) -> list[str]:
        """Which skill packs this scenario requires."""
        ...

    @abstractmethod
    def get_test_cases(self) -> list[dict[str, Any]]:
        """Return benchmark test inputs."""
        ...

    @abstractmethod
    def evaluate(self, trace: Trace, test_case: dict[str, Any]) -> dict[str, Any]:
        """Grade the agent's performance on a test case."""
        ...
