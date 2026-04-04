"""Local-first research orchestration with optional web fallback."""

from __future__ import annotations

import re
import httpx

from rag_service.rag_store import get_store
from rag_service.retrieval import DEFAULT_COLLECTION, query_index
from services.research_models import EvidenceBundle, EvidenceItem
from services.web_search import search_web


class SearchOrchestrator:
    """Gather evidence from local retrieval and, when needed, from the web."""

    def __init__(self, collection: str = DEFAULT_COLLECTION) -> None:
        self.collection = collection

    async def gather(
        self,
        query: str,
        *,
        prefer_web: bool = False,
        allow_web_fallback: bool = True,
    ) -> EvidenceBundle:
        bundle = EvidenceBundle(query=query)

        if not prefer_web:
            self._gather_local(bundle, query)

        needs_web = prefer_web or (
            allow_web_fallback and (not bundle.used_local or bundle.local_confidence < 0.4)
        )
        if needs_web:
            await self._gather_web(bundle, query)

        return bundle

    def _gather_local(self, bundle: EvidenceBundle, query: str) -> None:
        store = get_store()
        bundle.add_stage("local_search_started")
        if not store.collection_exists(self.collection) or store.count(self.collection) == 0:
            return

        try:
            result = query_index(query, collection=self.collection, top_k=3)
        except Exception:
            return

        matches = result.get("results", [])
        if not matches:
            return

        bundle.used_local = True
        bundle.add_stage("local_search_finished")
        bundle.local_confidence = float(matches[0].get("score", 0.0))
        for item in matches:
            snippet = item["text"].strip().replace("\n", " ")
            summary = snippet[:220] + ("..." if len(snippet) > 220 else "")
            bundle.items.append(
                EvidenceItem(
                    source_type="local",
                    source_label=f"{item['source']}:{item['start_line']}-{item['end_line']}",
                    summary=summary,
                    content=item["text"],
                    score=float(item.get("score", 0.0)),
                )
            )

    async def _gather_web(self, bundle: EvidenceBundle, query: str) -> None:
        bundle.add_stage("web_search_started")
        search_results = await search_web(query, max_results=3)
        if not search_results:
            return

        bundle.used_web = True
        for result in search_results[:2]:
            content = await self._fetch_page(result["url"])
            if not content:
                continue
            summary = content[:240] + ("..." if len(content) > 240 else "")
            bundle.items.append(
                EvidenceItem(
                    source_type="web",
                    source_label=result["title"],
                    summary=summary,
                    content=content,
                    score=0.2,
                    url=result["url"],
                )
            )
        bundle.add_stage("web_search_finished")

    async def _fetch_page(self, url: str, max_chars: int = 1800) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Relay/0.1"})
                resp.raise_for_status()
        except Exception:
            return None

        text = resp.text
        if "html" in resp.headers.get("content-type", ""):
            text = self._strip_html(text)
        text = text.strip()
        if not text:
            return None
        return text[:max_chars]

    def _strip_html(self, html: str) -> str:
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"\s+", " ", html).strip()
        return html
