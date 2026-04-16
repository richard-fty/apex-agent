"""Built-in retrieval tools backed by the retrieval service layer."""

from __future__ import annotations

from typing import Any

from agent.core.models import ToolGroup, ToolLoadingStrategy, ToolParameter
from rag_service.retrieval import (
    DEFAULT_COLLECTION,
    DEFAULT_RETRIEVAL_MODE,
    INDEXABLE_EXTENSIONS,
    index_path,
    list_collections,
    query_index,
)
from tools.base import BuiltinTool


# ── Built-in tools ────────────────────────────────────────────────────────

class RagIndexTool(BuiltinTool):
    name = "rag_index"
    description = (
        "Index a file or directory into the RAG vector store for semantic search. "
        "Supports text, code, markdown, and config files. "
        "Use this to make documents searchable by meaning."
    )
    tool_group = ToolGroup.ADMIN
    loading_strategy = ToolLoadingStrategy.RUNTIME_INJECTED
    feature_flag = "enable_rag"
    requires_confirmation = True
    is_networked = True
    mutates_state = True
    path_access = "write"
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Path to a file or directory to index",
        ),
        ToolParameter(
            name="collection",
            type="string",
            description="Collection name to store chunks in (default: 'default')",
            required=False,
            default=DEFAULT_COLLECTION,
        ),
        ToolParameter(
            name="recursive",
            type="boolean",
            description="If path is a directory, index recursively (default: true)",
            required=False,
            default=True,
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        result = index_path(
            path=kwargs["path"],
            collection=kwargs.get("collection", DEFAULT_COLLECTION),
            recursive=kwargs.get("recursive", True),
        )
        return result["message"]


class RagQueryTool(BuiltinTool):
    name = "rag_query"
    description = (
        "Search the RAG vector store by semantic similarity. "
        "Returns the most relevant document chunks for a natural language query. "
        "Use this to find relevant code, documentation, or past analyses."
    )
    tool_group = ToolGroup.RETRIEVAL
    loading_strategy = ToolLoadingStrategy.FEATURE_GATED
    feature_flag = "enable_rag"
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    is_networked = True
    mutates_state = False
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Natural language search query",
        ),
        ToolParameter(
            name="collection",
            type="string",
            description="Collection to search (default: 'default')",
            required=False,
            default=DEFAULT_COLLECTION,
        ),
        ToolParameter(
            name="top_k",
            type="integer",
            description="Number of results to return (default: 5)",
            required=False,
            default=5,
        ),
        ToolParameter(
            name="where_source",
            type="string",
            description="Filter results to a specific source file path (optional)",
            required=False,
        ),
        ToolParameter(
            name="retrieval_mode",
            type="string",
            description="Retrieval strategy: vector, bm25, or hybrid (default: hybrid)",
            required=False,
            default=DEFAULT_RETRIEVAL_MODE,
        ),
    ]

    async def execute(self, **kwargs: Any) -> str:
        result = query_index(
            query=kwargs["query"],
            collection=kwargs.get("collection", DEFAULT_COLLECTION),
            top_k=kwargs.get("top_k", 5),
            where_source=kwargs.get("where_source"),
            retrieval_mode=kwargs.get("retrieval_mode", DEFAULT_RETRIEVAL_MODE),
        )
        return result["message"]


class RagListCollectionsTool(BuiltinTool):
    name = "rag_list_collections"
    description = (
        "List all RAG collections and their document counts. "
        "Use this to see what has been indexed."
    )
    tool_group = ToolGroup.RETRIEVAL
    loading_strategy = ToolLoadingStrategy.FEATURE_GATED
    feature_flag = "enable_rag"
    is_read_only = True
    is_concurrency_safe = True
    requires_confirmation = False
    mutates_state = False
    parameters = []

    async def execute(self, **kwargs: Any) -> str:
        return list_collections()["message"]
