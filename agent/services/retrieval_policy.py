"""Hidden runtime research policy for local-first search and KB writes."""

from __future__ import annotations

from rag_service.retrieval import DEFAULT_COLLECTION
from services.research_models import ResearchContext
from services.search_orchestrator import SearchOrchestrator


_RETRIEVAL_HINTS = (
    "what", "where", "how", "why", "explain", "summary", "summarize",
    "find", "look up", "documentation", "docs", "report", "analysis",
    "之前", "总结", "解释", "哪里", "文档", "资料", "分析",
)
_INGEST_HINTS = (
    "index", "ingest", "knowledge base", "knowledgebase", "remember",
    "save this", "add to knowledge", "纳入知识", "记住", "索引", "知识库",
)

_WEB_FIRST_HINTS = (
    "latest", "recent", "today", "news", "current", "compare", "vs", "versus",
    "最近", "最新", "对比", "比较", "新闻", "当前",
)
_WEB_FALLBACK_HINTS = (
    "latest", "recent", "today", "news", "current", "compare", "vs", "versus",
    "source", "sources", "citation", "citations", "research", "investigate",
    "最近", "最新", "对比", "比较", "新闻", "当前", "来源", "调研", "研究",
)


class ResearchPolicy:
    """Decide when to gather hidden research evidence and expose write tools."""

    def __init__(self, collection: str = DEFAULT_COLLECTION) -> None:
        self.collection = collection
        self.orchestrator = SearchOrchestrator(collection=collection)

    async def evaluate(self, user_input: str) -> ResearchContext:
        text = (user_input or "").strip()
        if not text:
            return ResearchContext()

        if self._should_surface_runtime_tools(text):
            return ResearchContext(should_offer_runtime_tools=True, route="ingest")

        if not self._should_attempt_retrieval(text):
            return ResearchContext()

        evidence = await self.orchestrator.gather(
            text,
            prefer_web=self._should_prefer_web(text),
            allow_web_fallback=self._should_consider_web_fallback(text),
        )
        return ResearchContext(
            used=bool(evidence.items),
            confidence=evidence.local_confidence,
            injected_message=evidence.to_injected_message(),
            should_consider_web_fallback=evidence.used_web,
            route="research" if evidence.items else "default",
            evidence=evidence,
        )

    def _should_attempt_retrieval(self, text: str) -> bool:
        lowered = text.lower()
        if len(lowered) < 12:
            return False
        return any(hint in lowered for hint in _RETRIEVAL_HINTS) or "?" in lowered

    def _should_surface_runtime_tools(self, text: str) -> bool:
        lowered = text.lower()
        return any(hint in lowered for hint in _INGEST_HINTS)

    def _should_prefer_web(self, text: str) -> bool:
        lowered = text.lower()
        return any(hint in lowered for hint in _WEB_FIRST_HINTS)

    def _should_consider_web_fallback(self, text: str) -> bool:
        lowered = text.lower()
        return any(hint in lowered for hint in _WEB_FALLBACK_HINTS)


RetrievalPolicy = ResearchPolicy
RetrievalContext = ResearchContext


# ---------------------------------------------------------------------------
# Module-level routing predicate helpers
# Exposed for T3.2 contract tests — same logic as the class methods.
# ---------------------------------------------------------------------------

def _should_attempt_retrieval_for(text: str) -> bool:
    lowered = (text or "").lower()
    if len(lowered) < 12:
        return False
    return any(hint in lowered for hint in _RETRIEVAL_HINTS) or "?" in lowered


def _should_ingest_for(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _INGEST_HINTS)


def _should_prefer_web_for(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _WEB_FIRST_HINTS)
