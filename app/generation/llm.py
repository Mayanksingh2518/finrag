"""Provider-agnostic LLM calls with structured output, caching, rate limiting and fallback.

    llm = build_llm()
    parsed, meta = llm.generate(messages, GeneratedAnswer)

Providers are tried in order (default: local Ollama, then Groq, then Gemini). Each call:
- asks for JSON matching a pydantic model (strict JSON schema),
- is served from an on-disk cache when the same request was made before
  (free tiers are small, and evals repeat the same prompts),
- waits when the provider's rate-limit headers say the token budget is spent,
- retries 429/5xx with backoff, then falls through to the next provider.
API keys are only ever sent to their own provider and never logged.
"""

import copy
import hashlib
import json
import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}


class LLMError(RuntimeError):
    """A provider failed for this request (after its own retries)."""


class RetryableError(LLMError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    cached: bool = False
    attempts: list[str] = field(default_factory=list)  # "groq: 429", ... for providers that failed first


def strict_json_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema in the strict form providers accept: $refs inlined, every property
    required, no additional properties, no titles/defaults."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class Provider(Protocol):
    name: str
    model: str

    def complete(self, messages: Sequence[Message], schema: dict, schema_name: str) -> LLMResponse: ...


class TokenRateLimiter:
    """Tracks the provider's remaining tokens-per-minute from response headers and waits
    before a call that would exceed it (cheaper than eating a 429)."""

    def __init__(self, sleep=time.sleep, clock=time.monotonic):
        self._remaining: int | None = None
        self._reset_at = 0.0
        self._sleep, self._clock = sleep, clock
        self._lock = threading.Lock()

    def wait_for(self, tokens_needed: int) -> float:
        with self._lock:
            now = self._clock()
            if self._remaining is not None and self._remaining < tokens_needed and now < self._reset_at:
                delay = self._reset_at - now
                logger.info("Rate limit: waiting %.1f s for %d tokens", delay, tokens_needed)
                self._sleep(delay)
                self._remaining = None
                return delay
            return 0.0

    def update(self, remaining: int | None, reset_in_s: float | None) -> None:
        with self._lock:
            if remaining is not None:
                self._remaining = remaining
            if reset_in_s is not None:
                self._reset_at = self._clock() + reset_in_s


def _parse_duration(value: str | None) -> float | None:
    """Groq reset headers look like '4.207s', '1m2.5s' or '850ms'."""
    if not value:
        return None
    total, num = 0.0, ""
    i = 0
    while i < len(value):
        ch = value[i]
        if ch.isdigit() or ch == ".":
            num += ch
        elif value.startswith("ms", i):
            total += float(num or 0) / 1000
            num = ""
            i += 1
        elif ch in "hms":
            total += float(num or 0) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
        i += 1
    return total + (float(num) if num else 0.0)


def _estimate_tokens(messages: Sequence[Message]) -> int:
    return sum(len(m["content"]) for m in messages) // 4 + 400  # + room for the answer


class GroqProvider:
    """OpenAI-compatible chat completions with strict JSON schema output."""

    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, timeout_s: float = 90.0, client: httpx.Client | None = None,
                 limiter: TokenRateLimiter | None = None, max_tokens: int = 1500):
        self.model = model
        self._key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)
        self.limiter = limiter or TokenRateLimiter()
        self.max_tokens = max_tokens

    def complete(self, messages: Sequence[Message], schema: dict, schema_name: str) -> LLMResponse:
        self.limiter.wait_for(_estimate_tokens(messages))
        body = {
            "model": self.model,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        }
        if "gpt-oss" in self.model:
            body["reasoning_effort"] = "low"
        start = time.perf_counter()
        try:
            res = self._client.post(self.URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            raise RetryableError(f"groq network error: {type(e).__name__}") from None
        self.limiter.update(
            int(res.headers["x-ratelimit-remaining-tokens"]) if "x-ratelimit-remaining-tokens" in res.headers else None,
            _parse_duration(res.headers.get("x-ratelimit-reset-tokens")),
        )
        if res.status_code == 429 or res.status_code >= 500:
            raise RetryableError(f"groq HTTP {res.status_code}", _parse_duration(res.headers.get("retry-after")))
        if res.status_code != 200:
            raise LLMError(f"groq HTTP {res.status_code}: {res.text[:300]}")
        data = res.json()
        usage = data.get("usage", {})
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            provider=self.name,
            model=data.get("model", self.model),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
                        (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)),
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )


class GeminiProvider:
    """Gemini through the Interactions API (the only route that serves 3.x models to new keys)."""

    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(self, api_key: str, model: str, timeout_s: float = 90.0, client: httpx.Client | None = None):
        self.model = model
        self._key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)

    def complete(self, messages: Sequence[Message], schema: dict, schema_name: str) -> LLMResponse:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in messages if m["role"] != "system")
        body = {
            "model": self.model,
            "input": f"{system}\n\n{turns}" if system else turns,
            "response_format": {"type": "text", "mime_type": "application/json", "schema": schema},
        }
        start = time.perf_counter()
        try:
            res = self._client.post(self.URL, json=body, headers={"x-goog-api-key": self._key})
        except httpx.HTTPError as e:
            raise RetryableError(f"gemini network error: {type(e).__name__}") from None
        if res.status_code == 429 or res.status_code >= 500:
            raise RetryableError(f"gemini HTTP {res.status_code}")
        if res.status_code != 200:
            raise LLMError(f"gemini HTTP {res.status_code}: {res.text[:300]}")
        data = res.json()
        if data.get("status") != "completed":
            raise RetryableError(f"gemini interaction status {data.get('status')}")
        text = "".join(
            part.get("text", "")
            for step in data.get("steps", []) if step.get("type") == "model_output"
            for part in step.get("content", []) if part.get("type") == "text"
        )
        usage = data.get("usage", {})
        return LLMResponse(
            text=text, provider=self.name, model=data.get("model", self.model),
            usage=Usage(usage.get("total_input_tokens", 0), usage.get("total_output_tokens", 0),
                        usage.get("total_thought_tokens", 0)),
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )


class OllamaProvider:
    """Local model through Ollama's /api/chat with a JSON-schema `format` (no keys, no rate limits).

    `num_ctx` must be set explicitly: Ollama's default context window is smaller than FinRAG's
    prompts and would silently truncate the sources.
    """

    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_s: float = 180.0, num_ctx: int = 8192,
                 client: httpx.Client | None = None):
        self.model = model
        self.url = base_url.rstrip("/") + "/api/chat"
        self.num_ctx = num_ctx
        self._client = client or httpx.Client(timeout=timeout_s)

    def complete(self, messages: Sequence[Message], schema: dict, schema_name: str) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
            "keep_alive": "30m",
        }
        start = time.perf_counter()
        try:
            res = self._client.post(self.url, json=body)
        except httpx.ConnectError:
            # Not running: fail over to the next provider immediately instead of retrying.
            raise LLMError("ollama is not running (start it with `brew services start ollama`)") from None
        except httpx.HTTPError as e:
            raise RetryableError(f"ollama {type(e).__name__}") from None
        if res.status_code == 404:
            raise LLMError(f"ollama model {self.model!r} not found (run `ollama pull {self.model}`)")
        if res.status_code >= 500:
            raise RetryableError(f"ollama HTTP {res.status_code}")
        if res.status_code != 200:
            raise LLMError(f"ollama HTTP {res.status_code}: {res.text[:300]}")
        data = res.json()
        return LLMResponse(
            text=data["message"]["content"], provider=self.name, model=self.model,
            usage=Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)),
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )


class ResponseCache:
    """One JSON file per request hash. Deterministic prompts (temperature 0) make reruns free."""

    def __init__(self, directory: Path):
        self.dir = directory

    @staticmethod
    def key(provider: str, model: str, messages: Sequence[Message], schema: dict) -> str:
        raw = json.dumps([provider, model, list(messages), schema], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> LLMResponse | None:
        path = self.dir / f"{key[:2]}/{key}.json"
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse(text=d["text"], provider=d["provider"], model=d["model"], usage=Usage(**d["usage"]),
                           latency_ms=d["latency_ms"], cached=True)

    def put(self, key: str, response: LLMResponse) -> None:
        path = self.dir / f"{key[:2]}/{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v for k, v in asdict(response).items() if k not in ("cached", "attempts")}),
                       encoding="utf-8")
        tmp.replace(path)


class LLM:
    def __init__(self, providers: Sequence[Provider], cache: ResponseCache | None = None, max_retries: int = 3,
                 sleep=time.sleep):
        if not providers:
            raise LLMError("No LLM providers configured (set GROQ_API_KEY and/or GEMINI_API_KEY in .env)")
        self.providers = list(providers)
        self.cache = cache
        self.max_retries = max_retries
        self._sleep = sleep

    def generate(self, messages: Sequence[Message], output: type[T]) -> tuple[T, LLMResponse]:
        schema = strict_json_schema(output)
        attempts: list[str] = []
        for provider in self.providers:
            key = ResponseCache.key(provider.name, provider.model, messages, schema)
            if self.cache and (hit := self.cache.get(key)):
                try:
                    hit.attempts = attempts
                    return output.model_validate_json(hit.text), hit
                except ValidationError:
                    pass  # stale/corrupt entry: call the provider again
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = provider.complete(messages, schema, output.__name__)
                    parsed = output.model_validate_json(response.text)
                except RetryableError as e:
                    attempts.append(f"{provider.name}: {e}")
                    if attempt == self.max_retries:
                        break
                    delay = e.retry_after if e.retry_after is not None else 2.0 * 2 ** (attempt - 1)
                    self._sleep(min(delay, 60.0))
                    continue
                except ValidationError as e:
                    attempts.append(f"{provider.name}: invalid JSON ({e.error_count()} errors)")
                    break
                except LLMError as e:
                    attempts.append(f"{provider.name}: {e}")
                    break
                response.attempts = attempts
                if self.cache:
                    self.cache.put(key, response)
                return parsed, response
            logger.warning("LLM provider %s failed; trying next. %s", provider.name, attempts[-1:])
        raise LLMError("All LLM providers failed: " + "; ".join(attempts))


def build_llm(settings=None) -> LLM:
    from app.config import get_settings

    settings = settings or get_settings()
    providers: list[Provider] = []
    for name in (p.strip() for p in settings.llm_providers.split(",") if p.strip()):
        if name == "groq" and settings.groq_api_key:
            providers.append(GroqProvider(settings.groq_api_key, settings.groq_model, settings.llm_timeout_s))
        elif name == "gemini" and settings.gemini_api_key:
            providers.append(GeminiProvider(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_s))
        elif name == "ollama" and settings.ollama_model:
            providers.append(OllamaProvider(settings.ollama_base_url, settings.ollama_model, num_ctx=settings.ollama_num_ctx))
    return LLM(providers, ResponseCache(settings.llm_cache_dir))
