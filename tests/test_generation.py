import json

import httpx
import pytest

from app.generation.answer import Answerer, confidence_of, render_citations
from app.generation.context import build_sources
from app.generation.llm import (
    LLM,
    GeminiProvider,
    GroqProvider,
    LLMError,
    LLMResponse,
    ResponseCache,
    RetryableError,
    TokenRateLimiter,
    _parse_duration,
    strict_json_schema,
)
from app.generation.schemas import Claim, GeneratedAnswer
from app.generation.verify import extract_numbers, verify_claims
from app.retrieval.bm25 import BM25Index
from app.retrieval.dense import DenseIndex
from app.retrieval.retriever import Retriever
from app.retrieval.store import ChunkStore
from app.retrieval.types import ScoredChunk, SearchFilters
from tests.test_retrieval import CHUNKS, FakeEmbedder, ReverseReranker, make_chunk

# ---------------- schema / parsing helpers ----------------


def test_strict_schema_inlines_refs_and_requires_everything():
    schema = strict_json_schema(GeneratedAnswer)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text and '"title"' not in text
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    item = schema["properties"]["claims"]["items"]
    assert item["required"] == ["text", "source_ids"] and item["additionalProperties"] is False


@pytest.mark.parametrize("raw,seconds", [("4.207s", 4.207), ("1m2.5s", 62.5), ("850ms", 0.85), ("7", 7.0), (None, None)])
def test_parse_rate_limit_durations(raw, seconds):
    assert _parse_duration(raw) == (pytest.approx(seconds) if seconds is not None else None)


def test_rate_limiter_waits_only_when_budget_is_spent():
    now = [100.0]
    slept = []
    limiter = TokenRateLimiter(sleep=slept.append, clock=lambda: now[0])
    assert limiter.wait_for(5000) == 0  # nothing known yet
    limiter.update(remaining=6000, reset_in_s=10)
    assert limiter.wait_for(5000) == 0
    limiter.update(remaining=1000, reset_in_s=4)
    assert limiter.wait_for(5000) == pytest.approx(4) and slept == [pytest.approx(4)]


# ---------------- LLM fallback / cache ----------------


class FakeProvider:
    def __init__(self, name, outputs):
        self.name, self.model = name, f"{name}-model"
        self.outputs = list(outputs)
        self.calls = 0

    def complete(self, messages, schema, schema_name):
        self.calls += 1
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return LLMResponse(text=out, provider=self.name, model=self.model)


ANSWER_JSON = json.dumps({"answer": "Up 14% [S1].", "claims": [{"text": "Services grew 14%.", "source_ids": ["S1"]}],
                          "abstained": False, "abstain_reason": ""})
MESSAGES = [{"role": "user", "content": "q"}]


def test_llm_retries_then_falls_back_to_next_provider(tmp_path):
    groq = FakeProvider("groq", [RetryableError("429", retry_after=0), RetryableError("429", retry_after=0)])
    gemini = FakeProvider("gemini", [ANSWER_JSON])
    llm = LLM([groq, gemini], ResponseCache(tmp_path), max_retries=2, sleep=lambda s: None)
    parsed, meta = llm.generate(MESSAGES, GeneratedAnswer)
    assert parsed.claims[0].source_ids == ["S1"] and meta.provider == "gemini"
    assert groq.calls == 2 and meta.attempts == ["groq: 429", "groq: 429"]


def test_llm_cache_serves_repeat_requests(tmp_path):
    groq = FakeProvider("groq", [ANSWER_JSON])
    llm = LLM([groq], ResponseCache(tmp_path))
    llm.generate(MESSAGES, GeneratedAnswer)
    parsed, meta = llm.generate(MESSAGES, GeneratedAnswer)
    assert meta.cached and groq.calls == 1 and parsed.answer.startswith("Up 14%")


def test_llm_invalid_json_moves_on_and_total_failure_raises(tmp_path):
    llm = LLM([FakeProvider("groq", ['{"answer": 1}']), FakeProvider("gemini", [LLMError("401")])], ResponseCache(tmp_path))
    with pytest.raises(LLMError, match="groq: invalid JSON.*gemini: 401"):
        llm.generate(MESSAGES, GeneratedAnswer)
    with pytest.raises(LLMError, match="No LLM providers"):
        LLM([])


# ---------------- HTTP providers (mocked transport) ----------------


def test_groq_request_shape_and_rate_limit_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"x-ratelimit-remaining-tokens": "1234", "x-ratelimit-reset-tokens": "3s"},
                              json={"model": "openai/gpt-oss-120b", "choices": [{"message": {"content": ANSWER_JSON}}],
                                    "usage": {"prompt_tokens": 50, "completion_tokens": 20,
                                              "completion_tokens_details": {"reasoning_tokens": 5}}})

    p = GroqProvider("secret", "openai/gpt-oss-120b", client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = p.complete(MESSAGES, strict_json_schema(GeneratedAnswer), "GeneratedAnswer")
    assert seen["auth"] == "Bearer secret"
    fmt = seen["body"]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert seen["body"]["reasoning_effort"] == "low" and seen["body"]["temperature"] == 0
    assert res.usage.reasoning_tokens == 5 and p.limiter._remaining == 1234


def test_groq_429_is_retryable_with_retry_after():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "2"})))
    with pytest.raises(RetryableError) as e:
        GroqProvider("k", "m", client=client).complete(MESSAGES, {}, "X")
    assert e.value.retry_after == 2


def test_groq_daily_limit_fails_over_without_retrying():
    body = {"error": {"message": "Rate limit reached for model `m` in organization `org_123` on tokens per day (TPD)"}}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, json=body)))
    with pytest.raises(LLMError) as e:
        GroqProvider("k", "m", client=client).complete(MESSAGES, {}, "X")
    assert not isinstance(e.value, RetryableError)
    assert "tokens per day" in str(e.value) and "org_123" not in str(e.value)


def test_gemini_interactions_response_is_parsed():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "k" and body["response_format"]["mime_type"] == "application/json"
        return httpx.Response(200, json={"status": "completed", "model": "gemini-3.8-flash",
                                         "steps": [{"type": "thought"}, {"type": "model_output", "content": [{"type": "text", "text": ANSWER_JSON}]}],
                                         "usage": {"total_input_tokens": 9, "total_output_tokens": 3, "total_thought_tokens": 7}})

    res = GeminiProvider("k", "gemini-3.8-flash", client=httpx.Client(transport=httpx.MockTransport(handler))).complete(
        [{"role": "system", "content": "s"}, *MESSAGES], {}, "X")
    assert json.loads(res.text)["answer"].startswith("Up") and res.usage.reasoning_tokens == 7


# ---------------- verification ----------------


def _sources(*texts):
    hits = [ScoredChunk(make_chunk(i, "AAPL", 2025, "Item 7", t), 0.9) for i, t in enumerate(texts)]
    return build_sources(hits, token_budget=10_000)


def test_numbers_extracted_with_units_and_years_ignored():
    nums = extract_numbers("In fiscal 2025 Services rose 14% to $109.2 billion (2,345 stores).")
    assert [(n.value, n.scale, n.percent) for n in nums] == [(14, 1, True), (109.2, 1e9, False), (2345, 1, False)]


def test_verifier_matches_figures_across_units_and_catches_inventions():
    sources = _sources("| Services | 109,158 | 14% | 96,169 |", "Revenue was $60.9 billion, up 126%.")
    claims = [
        Claim(text="Services net sales were $109.2 billion, up 14%.", source_ids=["S1"]),  # millions table -> billions
        Claim(text="Services net sales were $109,158 million.", source_ids=["S1"]),
        Claim(text="Revenue was $61 billion.", source_ids=["S2"]),  # rounded
        Claim(text="Services net sales were $120 billion.", source_ids=["S1"]),  # invented
        Claim(text="Revenue was $60.9 billion.", source_ids=["S1"]),  # wrong source
        Claim(text="Revenue grew strongly.", source_ids=["S9"]),  # source never shown
    ]
    status = [c.status for c in verify_claims(claims, sources)]
    assert status == ["supported", "supported", "supported", "unsupported_number", "unsupported_number", "invalid_citation"]


def test_render_citations_and_confidence():
    sources = _sources("Services net sales increased 14%.")
    assert render_citations("Up 14% [S1], see [S7].", sources) == "Up 14% [AAPL FY2025 p.1], see [S7]."
    ok = verify_claims([Claim(text="Up 14%.", source_ids=["S1"])], sources)
    bad = verify_claims([Claim(text="Up 15%.", source_ids=["S1"])], sources)
    assert confidence_of(ok, sources, False) == "high"
    assert confidence_of(ok + bad, sources, False) == "medium"
    assert confidence_of(bad, sources, False) == "low" and confidence_of([], sources, True) == "none"


def test_context_budget_skips_whole_chunks_and_numbers_sources():
    big = make_chunk(0, "AAPL", 2025, "Item 8", "x" * 10, "table")
    big.token_count = 900
    small = make_chunk(1, "AAPL", 2025, "Item 7", "y")
    sources = build_sources([ScoredChunk(big, 1.0), ScoredChunk(small, 0.5), ScoredChunk(small, 0.5)], token_budget=500)
    assert [(s.id, s.chunk.chunk_id) for s in sources] == [("S1", small.chunk_id)]


# ---------------- end to end with a fake LLM ----------------


class ScriptedLLM:
    def __init__(self, answer: GeneratedAnswer):
        self.answer = answer
        self.messages = None

    def generate(self, messages, output):
        self.messages = messages
        return self.answer, LLMResponse(text="", provider="fake", model="fake")


def _answerer(llm) -> Answerer:
    emb = FakeEmbedder()
    retriever = Retriever(ChunkStore(CHUNKS), BM25Index([c.embed_text for c in CHUNKS]),
                          DenseIndex(emb.embed_documents([c.embed_text for c in CHUNKS])), emb, ReverseReranker(),
                          candidates_per_retriever=5)
    return Answerer(retriever, llm, k=4)


def test_answerer_renders_verified_answer_with_page_citations():
    llm = ScriptedLLM(GeneratedAnswer(answer="Services revenue increased due to advertising [S1].",
                                      claims=[Claim(text="Services revenue increased due to advertising.", source_ids=["S1"])],
                                      abstained=False, abstain_reason=""))
    result = _answerer(llm).answer("Why did services revenue increase?", SearchFilters(("AAPL",), (2025,)))
    assert "Question: Why did services revenue increase?" in llm.messages[1]["content"] and "[S1]" in llm.messages[1]["content"]
    assert result.answer.endswith("[AAPL FY2025 p.1].") and not result.abstained
    assert result.claims[0].supported and result.cited_source_ids == ["S1"]


def test_answerer_abstains_when_no_claim_is_supported_or_nothing_matches():
    llm = ScriptedLLM(GeneratedAnswer(answer="Revenue was $999 billion [S1].",
                                      claims=[Claim(text="Revenue was $999 billion.", source_ids=["S1"])],
                                      abstained=False, abstain_reason=""))
    result = _answerer(llm).answer("revenue", SearchFilters(("AAPL",), (2025,)))
    assert result.abstained and result.answer == "" and result.confidence == "none"
    empty = _answerer(llm).answer("revenue", SearchFilters(("AAPL",), (2023,)))  # no such filing in the fixture
    assert empty.abstained and empty.sources == []


def test_answerer_attaches_citations_when_model_omits_inline_markers():
    llm = ScriptedLLM(GeneratedAnswer(answer="Services revenue increased due to advertising.",
                                      claims=[Claim(text="Services revenue increased.", source_ids=["S1"])],
                                      abstained=False, abstain_reason=""))
    result = _answerer(llm).answer("Why did services revenue increase?", SearchFilters(("AAPL",), (2025,)))
    assert result.answer == "Services revenue increased due to advertising. [AAPL FY2025 p.1]"


def test_ollama_request_sets_context_window_and_schema():
    from app.generation.llm import OllamaProvider

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": ANSWER_JSON}, "prompt_eval_count": 120, "eval_count": 30})

    p = OllamaProvider("http://localhost:11434/", "granite4.1:3b", num_ctx=8192,
                       client=httpx.Client(transport=httpx.MockTransport(handler)))
    res = p.complete(MESSAGES, strict_json_schema(GeneratedAnswer), "GeneratedAnswer")
    assert seen["options"] == {"temperature": 0, "num_ctx": 8192} and seen["stream"] is False
    assert seen["format"]["type"] == "object" and res.usage.prompt_tokens == 120 and res.provider == "ollama"


def test_ollama_down_or_missing_model_fails_over_without_retrying(tmp_path):
    from app.generation.llm import OllamaProvider

    def refuse(request):
        raise httpx.ConnectError("refused")

    down = OllamaProvider("http://x", "m", client=httpx.Client(transport=httpx.MockTransport(refuse)))
    with pytest.raises(LLMError, match="not running") as e:
        down.complete(MESSAGES, {}, "X")
    assert not isinstance(e.value, RetryableError)
    missing = OllamaProvider("http://x", "nope", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    with pytest.raises(LLMError, match="ollama pull nope"):
        missing.complete(MESSAGES, {}, "X")

    groq = FakeProvider("groq", [ANSWER_JSON])
    llm = LLM([down, groq], ResponseCache(tmp_path), sleep=lambda s: pytest.fail("should not back off"))
    _, meta = llm.generate(MESSAGES, GeneratedAnswer)
    assert meta.provider == "groq" and "ollama: ollama is not running" in meta.attempts[0]


def test_answer_without_claims_is_treated_as_abstention():
    llm = ScriptedLLM(GeneratedAnswer(answer="14%", claims=[], abstained=False, abstain_reason="Answerable."))
    result = _answerer(llm).answer("services growth", SearchFilters(("AAPL",), (2025,)))
    assert result.abstained and result.answer == "" and result.abstain_reason  # uncited "14%" can't be verified


@pytest.mark.parametrize("text,expected", [
    ("Services grew 14% [S1]. iPhone grew 4% [S2].", [("Services grew 14% .", ["S1"]), ("iPhone grew 4% .", ["S2"])]),
    ("AWS grew 29% in 2022. [S1] AWS grew 20% in 2025. [S2]", [("AWS grew 29% in 2022.", ["S1"]), ("AWS grew 20% in 2025.", ["S1", "S2"])]),
    ("No markers here.", [("No markers here.", [])]),
    ("Revenue in the U.S. grew 5% [S1]. Inc. results held.", [("Revenue in the U.S. grew 5% .", ["S1"]), ("Inc. results held.", [])]),
])
def test_claims_derived_from_inline_markers(text, expected):
    from app.generation.answer import claims_from_text

    got = [(" ".join(c.text.split()), c.source_ids) for c in claims_from_text(text)]
    assert got == [(" ".join(t.split()), ids) for t, ids in expected]


def test_answer_with_inline_citations_but_no_claims_is_verified_from_text():
    llm = ScriptedLLM(GeneratedAnswer(answer="Services revenue increased due to advertising [S1].", claims=[],
                                      abstained=False, abstain_reason=""))
    result = _answerer(llm).answer("services", SearchFilters(("AAPL",), (2025,)))
    assert not result.abstained and result.claims[0].supported and result.answer.endswith("[AAPL FY2025 p.1].")
