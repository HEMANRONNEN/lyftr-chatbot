"""LiteLLM gateway: key pool, automatic failover and built-in response caching."""
import logging
from dataclasses import dataclass

import litellm
from litellm import Cache

from .config import Settings

log = logging.getLogger("gateway")

SIMULATABLE_STATUSES = {429, 500, 502, 503}


class AllProvidersUnavailable(Exception):
    """Every key in the pool failed (rate limit, quota, 5xx, network...)."""


@dataclass
class LLMResult:
    reply: str
    resolution_source: str  # LIVE_INFERENCE | LLM_CACHE
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, 'key_2': 500}. Bad pairs are ignored."""
    rules: dict[str, int] = {}
    if not header:
        return rules
    for pair in header.split(","):
        if "=" not in pair:
            continue
        key_id, _, status = pair.partition("=")
        key_id, status = key_id.strip(), status.strip()
        if key_id and status.isdigit() and int(status) in SIMULATABLE_STATUSES:
            rules[key_id] = int(status)
    return rules


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.keys = settings.api_keys
        self.model = settings.model
        # LiteLLM built-in in-memory cache. Cache key = model + full message list.
        litellm.cache = Cache(type="local")
        litellm.suppress_debug_info = True

    def _call(self, key: str, messages: list[dict], use_cache: bool):
        kwargs = dict(
            model=self.model,
            messages=messages,
            api_key=key,
            timeout=self.settings.request_timeout,
            num_retries=0,  # we do our own key-level failover
            max_tokens=self.settings.max_output_tokens,
            caching=use_cache,
        )
        if self.settings.mock_response:
            kwargs["mock_response"] = self.settings.mock_response
        return litellm.completion(**kwargs)

    def complete(self, messages: list[dict], simulate: dict[str, int] | None = None) -> LLMResult:
        simulate = simulate or {}
        # A simulated request must hit a real provider with a surviving key,
        # so the cache is bypassed for it.
        use_cache = not simulate
        failures = 0

        for index, key in enumerate(self.keys, start=1):
            key_id = f"key_{index}"
            forced = simulate.get(key_id) or simulate.get("*")
            if forced:
                log.warning("%s: simulated failure %s", key_id, forced)
                failures += 1
                continue
            try:
                response = self._call(key, messages, use_cache)
                reply = (response.choices[0].message.content or "").strip()
                if not reply:
                    raise ValueError("empty completion")
            except Exception as exc:  # any provider problem -> try the next key
                log.warning("%s failed: %s", key_id, type(exc).__name__)
                failures += 1
                continue

            hidden = getattr(response, "_hidden_params", None) or {}
            cache_hit = bool(hidden.get("cache_hit"))
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            if not input_tokens:
                input_tokens = litellm.token_counter(model=self.model, messages=messages)
            if not output_tokens:
                output_tokens = litellm.token_counter(model=self.model, text=reply)

            return LLMResult(
                reply=reply,
                resolution_source="LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
                model=getattr(response, "model", None) or self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                key_id=None if cache_hit else key_id,
                fallback_attempts=0 if cache_hit else failures,
            )

        raise AllProvidersUnavailable()
