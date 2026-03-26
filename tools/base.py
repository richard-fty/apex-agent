"""Base class and registry for built-in tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.models import ToolDef, ToolParameter

# Global registry of built-in tool classes
_BUILTIN_TOOL_CLASSES: list[type[BuiltinTool]] = []


class BuiltinTool(ABC):
    """Base class for built-in tools that are always available."""

    name: str
    description: str
    parameters: list[ToolParameter]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""
        ...

    def to_tool_def(self) -> ToolDef:
        return ToolDef(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register concrete subclasses."""
        super().__init_subclass__(**kwargs)
        # Only register if the class has no abstract methods (is concrete)
        if not getattr(cls, "__abstractmethods__", None):
            _BUILTIN_TOOL_CLASSES.append(cls)


def get_all_builtin_tools() -> list[BuiltinTool]:
    """Instantiate and return all registered built-in tools.

    Note: This only returns filesystem/shell/web tools.
    Skill meta-tools are registered separately via SkillMetaTools.
    """
    # Import tool modules to trigger subclass registration
    import tools.filesystem  # noqa: F401
    import tools.shell  # noqa: F401
    import tools.web  # noqa: F401

    return [cls() for cls in _BUILTIN_TOOL_CLASSES]
