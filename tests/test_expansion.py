import json
from pathlib import Path

import httpx
import pytest

from paperhub.expansion import (
    DeepSeekQueryExpander,
    QueryExpansion,
    QueryExpansionError,
    source_query,
)
from paperhub.http import HostRateLimiter, HttpClient
from paperhub.sources import SourceName


def _http(handler) -> HttpClient:
    return HttpClient(
        user_agent="paperhub-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        rate_limiter=HostRateLimiter({}),
    )


def test_deepseek_expander_accepts_strict_json_and_preserves_original_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"].startswith("Bearer test-key")
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash-0731"
        assert body["max_tokens"] >= 2048
        assert "AI客服" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "intent": "AI customer service",
                                    "include_terms": [
                                        "artificial intelligence",
                                        "customer service",
                                        "chatbot",
                                    ],
                                    "phrases": ["customer service chatbot"],
                                }
                            )
                        }
                    }
                ]
            },
        )

    expansion = DeepSeekQueryExpander(_http(handler), api_key="test-key").expand("AI客服")
    assert expansion.intent == "AI customer service"
    assert expansion.phrases[0] == "AI客服"
    assert "customer service" in expansion.include_terms


def test_deepseek_expander_rejects_invalid_shape() -> None:
    http = _http(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"intent":"x","include_terms":[],"phrases":[]}'}}
                ]
            },
        )
    )
    with pytest.raises(QueryExpansionError):
        DeepSeekQueryExpander(http, api_key="test-key").expand("x")


def test_deepseek_expander_rejects_markdown_wrapped_json() -> None:
    http = _http(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '```json {"intent":"x","include_terms":["x"],"phrases":["x"]} ```'
                        }
                    }
                ]
            },
        )
    )
    with pytest.raises(QueryExpansionError):
        DeepSeekQueryExpander(http, api_key="test-key").expand("x")


def test_missing_key_is_a_bounded_failure_and_source_queries_are_quoted() -> None:
    with pytest.raises(QueryExpansionError):
        DeepSeekQueryExpander(_http(lambda _: httpx.Response(500))).expand("x")
    expansion = QueryExpansion(
        "AI customer service",
        ("AI客服", "customer service", "chatbot"),
        ("customer service chatbot",),
    )
    query = source_query(SourceName.ARXIV, expansion)
    assert query.startswith("all:(")
    assert '"customer service chatbot"' in query
    assert " OR " in query


def test_key_file_loader_accepts_private_csv_and_rejects_weak_permissions(
    tmp_path: Path, monkeypatch
) -> None:
    key_file = tmp_path / "keys.csv"
    key_file.write_text("apiKey,fixture-key\n", encoding="utf-8")
    key_file.chmod(0o600)
    monkeypatch.delenv("PAPERHUB_QUERY_EXPANSION_API_KEY", raising=False)
    monkeypatch.setenv("PAPERHUB_QUERY_EXPANSION_KEY_FILE", str(key_file))
    expander = DeepSeekQueryExpander(_http(lambda _: httpx.Response(500)))
    assert expander.api_key == "fixture-key"
    key_file.chmod(0o644)
    with pytest.raises(QueryExpansionError, match="must not be group/world readable"):
        DeepSeekQueryExpander(_http(lambda _: httpx.Response(500)))
