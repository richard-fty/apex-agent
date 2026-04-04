"""Shared data models for hidden runtime research routing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvidenceItem:
    """One normalized piece of supporting evidence."""

    source_type: str
    source_label: str
    summary: str
    content: str
    score: float = 0.0
    url: str | None = None


@dataclass
class EvidenceBundle:
    """Evidence gathered for the current user request."""

    query: str
    items: list[EvidenceItem] = field(default_factory=list)
    local_confidence: float = 0.0
    used_local: bool = False
    used_web: bool = False
    stages: list[str] = field(default_factory=list)

    def add_stage(self, stage: str) -> None:
        if stage not in self.stages:
            self.stages.append(stage)

    def to_injected_message(self, max_items: int = 5) -> str | None:
        if not self.items:
            return None
        lines = [
            "[Research context]",
            "Use the following evidence when it helps answer the user's request.",
        ]
        for item in self.items[:max_items]:
            line = f"- {item.source_type}: {item.source_label}"
            if item.score > 0:
                line += f" (score {item.score:.3f})"
            if item.url:
                line += f" [{item.url}]"
            lines.append(line)
            lines.append(f"  {item.summary}")
        return "\n".join(lines)


@dataclass
class ResearchContext:
    """Research decision and assembled evidence for one turn."""

    used: bool = False
    confidence: float = 0.0
    injected_message: str | None = None
    should_offer_runtime_tools: bool = False
    should_consider_web_fallback: bool = False
    route: str = "default"
    evidence: EvidenceBundle | None = None
