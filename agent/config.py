"""Application configuration via environment variables and .env file."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ModelConfig(BaseModel):
    """Per-model context window settings."""

    max_tokens: int = 128_000
    reserved_for_output: int = 4096

    @property
    def input_budget(self) -> int:
        return self.max_tokens - self.reserved_for_output


# Known model context windows
MODEL_CONTEXT_WINDOWS: dict[str, ModelConfig] = {
    # Anthropic
    "anthropic/claude-sonnet-4-20250514": ModelConfig(max_tokens=200_000, reserved_for_output=8192),
    "anthropic/claude-haiku-4-5-20251001": ModelConfig(max_tokens=200_000, reserved_for_output=8192),
    "anthropic/claude-opus-4-0-20250514": ModelConfig(max_tokens=200_000, reserved_for_output=8192),
    # OpenAI
    "gpt-4o": ModelConfig(max_tokens=128_000, reserved_for_output=4096),
    "gpt-4o-mini": ModelConfig(max_tokens=128_000, reserved_for_output=4096),
    # Google
    "gemini/gemini-1.5-pro": ModelConfig(max_tokens=1_000_000, reserved_for_output=8192),
    "gemini/gemini-1.5-flash": ModelConfig(max_tokens=1_000_000, reserved_for_output=8192),
    # DeepSeek
    "deepseek/deepseek-chat": ModelConfig(max_tokens=64_000, reserved_for_output=4096),
    "deepseek/deepseek-reasoner": ModelConfig(max_tokens=64_000, reserved_for_output=4096),
}

MODEL_PROVIDER_ENV: dict[str, str] = {
    "anthropic/claude-sonnet-4-20250514": "ANTHROPIC_API_KEY",
    "anthropic/claude-haiku-4-5-20251001": "ANTHROPIC_API_KEY",
    "anthropic/claude-opus-4-0-20250514": "ANTHROPIC_API_KEY",
    "gpt-4o": "OPENAI_API_KEY",
    "gpt-4o-mini": "OPENAI_API_KEY",
    "gemini/gemini-1.5-pro": "GOOGLE_API_KEY",
    "gemini/gemini-1.5-flash": "GOOGLE_API_KEY",
    "deepseek/deepseek-chat": "DEEPSEEK_API_KEY",
    "deepseek/deepseek-reasoner": "DEEPSEEK_API_KEY",
}


def get_model_config(model: str) -> ModelConfig:
    """Get context window config for a model, falling back to defaults."""
    return MODEL_CONTEXT_WINDOWS.get(model, ModelConfig())


def get_model_provider_env(model: str) -> str | None:
    """Return the required API key env var for a model, if known."""
    return MODEL_PROVIDER_ENV.get(model)


class Settings(BaseSettings):
    """Global application settings loaded from environment / .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # API keys
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    hf_token: str = Field(default="", alias="HF_TOKEN")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # Embedding / reranking provider: "siliconflow" or "huggingface"
    embedding_provider: str = Field(default="siliconflow", alias="EMBEDDING_PROVIDER")

    # SiliconFlow settings (preferred — no cold start, free bge-m3)
    siliconflow_api_key: str = Field(default="", alias="SILICONFLOW_API_KEY")
    siliconflow_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        alias="SILICONFLOW_BASE_URL",
    )
    siliconflow_embedding_model: str = Field(
        default="BAAI/bge-m3",
        alias="SILICONFLOW_EMBEDDING_MODEL",
    )
    siliconflow_rerank_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        alias="SILICONFLOW_RERANK_MODEL",
    )

    # HuggingFace settings (fallback)
    hf_embedding_model: str = Field(
        default="intfloat/multilingual-e5-large",
        alias="HF_EMBEDDING_MODEL",
    )
    hf_embedding_url: str = Field(default="", alias="HF_EMBEDDING_URL")
    hf_rerank_model: str = Field(
        default="sentence-transformers/msmarco-distilbert-base-tas-b",
        alias="HF_RERANK_MODEL",
    )
    hf_rerank_url: str = Field(default="", alias="HF_RERANK_URL")
    rag_rerank_mode: str = Field(default="auto", alias="RAG_RERANK_MODE")
    rag_rerank_min_candidates: int = Field(default=8, alias="RAG_RERANK_MIN_CANDIDATES")
    rag_rerank_max_candidates: int = Field(default=100, alias="RAG_RERANK_MAX_CANDIDATES")

    # Default model for agent runs
    default_model: str = Field(default="deepseek/deepseek-chat")
    response_language: str = Field(
        default="English",
        description="Default assistant response language, e.g. English or Chinese",
    )

    # Agent loop
    max_steps: int = Field(default=20, description="Max tool-call steps per run")
    timeout_seconds: int = Field(default=300, description="Max wall-clock time per run")

    # Context management
    context_strategy: str = Field(
        default="truncate",
        description="Context strategy: truncate | summary | tiered",
    )

    # Compressor model (cheap/fast model for summarization)
    compressor_model: str = Field(default="gpt-4o-mini")

    # Retrieval / knowledge base
    enable_rag: bool = Field(default=True, description="Enable retrieval and knowledge-base tools")

    # Paths
    charts_dir: str = Field(default="charts")
    strategies_dir: str = Field(default="strategies")
    results_dir: str = Field(default="results")

    # Sandbox
    sandbox_backend: str = Field(
        default="auto",
        description="Sandbox backend: auto | docker | local",
    )
    sandbox_docker_image: str = Field(
        default="python:3.11-slim",
        description="Docker image for provisioned session sandboxes",
    )
    sandbox_network: str = Field(
        default="none",
        description="Docker network mode for sandboxed runs",
    )
    sandbox_memory: str = Field(
        default="256m",
        description="Memory limit for provisioned sandbox sessions",
    )
    sandbox_cpus: float = Field(
        default=0.5,
        description="CPU limit for provisioned sandbox sessions",
    )
    sandbox_require_isolation: bool = Field(
        default=False,
        description=(
            "When True, fail closed if strong isolation (Docker) is unavailable "
            "instead of falling back to LocalSandbox. Set this in production "
            "environments where LocalSandbox is not an acceptable security posture."
        ),
    )


settings = Settings()


# Export provider keys loaded from .env into os.environ so third-party libraries
# (litellm, huggingface_hub, tavily, etc.) can find them. pydantic-settings only
# populates the Settings object; libraries read os.environ directly. Shell-exported
# values win — we never overwrite an existing os.environ entry.
_EXPORTED_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "HF_TOKEN",
    "TAVILY_API_KEY",
    "SILICONFLOW_API_KEY",
)
for _key in _EXPORTED_ENV_KEYS:
    _value = getattr(settings, _key.lower(), "")
    if _value and not os.environ.get(_key):
        os.environ[_key] = _value


def is_model_available(model: str) -> tuple[bool, str | None]:
    """Check whether the configured environment supports the given model."""
    required_env = get_model_provider_env(model)
    if required_env is None:
        return True, None
    value = getattr(settings, required_env.lower(), "")
    if value:
        return True, required_env
    return False, required_env


def list_known_models() -> list[str]:
    """Return known model ids in stable display order."""
    return list(MODEL_CONTEXT_WINDOWS.keys())
