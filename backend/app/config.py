"""Runtime configuration, read from environment variables only."""
import os
from dataclasses import dataclass, field

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, concise assistant. Remember what the user said earlier "
    "in this conversation and answer clearly."
)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    api_keys: list[str] = field(default_factory=list)
    model: str = "gemini/gemini-2.0-flash"
    database_url: str = "sqlite:///./app.db"
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    enable_failure_simulation: bool = False
    default_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    request_timeout: float = 30.0
    max_history_messages: int = 40
    max_output_tokens: int = 1024
    # When set, LiteLLM returns this text instead of calling a provider.
    # Used by the test-suite and for key-less demos. Leave empty in production.
    mock_response: str = ""


def load_settings() -> Settings:
    return Settings(
        api_keys=_split(os.getenv("LLM_API_KEYS", "")),
        model=os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
        allowed_origins=_split(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")),
        enable_failure_simulation=_bool(os.getenv("ENABLE_FAILURE_SIMULATION")),
        default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        request_timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "40")),
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "1024")),
        mock_response=os.getenv("LLM_MOCK_RESPONSE", ""),
    )
