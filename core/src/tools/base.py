"""Base class and registry for built-in tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.core.models import ToolDef, ToolGroup, ToolLoadingStrategy, ToolParameter
from config import settings

# Global registry of built-in tool classes
_BUILTIN_TOOL_CLASSES: list[type[BuiltinTool]] = []


class BuiltinTool(ABC):
    """Base class for built-in tools that are always available."""

    name: str
    description: str
    parameters: list[ToolParameter]
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    requires_confirmation: bool = True
    is_networked: bool = False
    mutates_state: bool = True
    is_destructive: bool = False
    tool_group: ToolGroup = ToolGroup.CORE
    loading_strategy: ToolLoadingStrategy = ToolLoadingStrategy.ALWAYS
    feature_flag: str | None = None
    shell_command_arg: str | None = None
    path_access: str | None = None
    compliance_scope: str | None = None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""
        ...

    def to_tool_def(self) -> ToolDef:
        return ToolDef(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            is_read_only=self.is_read_only,
            is_concurrency_safe=self.is_concurrency_safe,
            requires_confirmation=self.requires_confirmation,
            is_networked=self.is_networked,
            mutates_state=self.mutates_state,
            is_destructive=self.is_destructive,
            tool_group=self.tool_group,
            loading_strategy=self.loading_strategy,
            feature_flag=self.feature_flag,
            visible=self.loading_strategy != ToolLoadingStrategy.RUNTIME_INJECTED,
            shell_command_arg=self.shell_command_arg,
            path_access=self.path_access,
            compliance_scope=self.compliance_scope,
        )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-register concrete subclasses."""
        super().__init_subclass__(**kwargs)
        # Only register if the class has no abstract methods (is concrete)
        if not getattr(cls, "__abstractmethods__", None):
            _BUILTIN_TOOL_CLASSES.append(cls)


def _import_builtin_modules() -> None:
    """Import tool modules to trigger subclass registration."""
    import tools.filesystem  # noqa: F401
    import tools.shell  # noqa: F401
    import tools.web  # noqa: F401
    import tools.rag  # noqa: F401


def _is_feature_enabled(flag: str | None) -> bool:
    if not flag:
        return True
    if flag == "enable_rag":
        return settings.enable_rag
    return True


def assemble_tool_pool(include_runtime_injected: bool = False) -> list[BuiltinTool]:
    """Assemble built-in tools with policy-aware surfacing and stable ordering."""
    # Import tool modules to trigger subclass registration
    _import_builtin_modules()

    tools = [cls() for cls in _BUILTIN_TOOL_CLASSES]
    filtered = [
        tool for tool in tools
        if _is_feature_enabled(tool.feature_flag)
        and (
            include_runtime_injected
            or tool.loading_strategy != ToolLoadingStrategy.RUNTIME_INJECTED
        )
    ]
    order = {
        ToolGroup.CORE: 0,
        ToolGroup.SKILL: 1,
        ToolGroup.RETRIEVAL: 2,
        ToolGroup.RUNTIME: 3,
        ToolGroup.ADMIN: 4,
    }
    return sorted(filtered, key=lambda tool: (order.get(tool.tool_group, 99), tool.name))


def get_all_builtin_tools() -> list[BuiltinTool]:
    """Backward-compatible built-in tool assembly."""
    return assemble_tool_pool(include_runtime_injected=True)
