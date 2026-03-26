"""Application configuration via environment variables and .env file."""

from __future__ import annotations

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


def get_model_config(model: str) -> ModelConfig:
    """Get context window config for a model, falling back to defaults."""
    return MODEL_CONTEXT_WINDOWS.get(model, ModelConfig())


class Settings(BaseSettings):
    """Global application settings loaded from environment / .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # API keys
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")

    # Default model for agent runs
    default_model: str = Field(default="deepseek/deepseek-chat")

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

    # Paths
    charts_dir: str = Field(default="charts")
    strategies_dir: str = Field(default="strategies")
    results_dir: str = Field(default="results")


settings = Settings()
