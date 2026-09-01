"""礼貌的 HTTP 客户端: 每个来源宿主的节流与超时."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx


@dataclass
class HostRateLimiter:
    """按宿主限制请求间隔, 避免对公共 API 过度请求."""

    intervals: dict[str, float] = field(default_factory=dict)
    _last_call: dict[str, float] = field(default_factory=dict)

    def wait(self, url: str) -> None:
        host = (urlparse(url).hostname or "unknown").casefold()
        interval = self.intervals.get(host, 0.0)
        last = self._last_call.get(host, 0.0)
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_call[host] = time.monotonic()


@dataclass
class DownloadedResponse:
    """一次电子的下载结果, 供校验与对象库使用."""

    content: bytes
    media_type: str
    final_url: str


class HttpClient:
    """对 ``httpx.Client`` 的一层薄封装: 限速 + 重试 + JSON/bytes 获取.

    依赖注入 ``httpx.Client``(可传 ``httpx.MockTransport``)以便测试 seam 用
    假传输验证各 connector 的归一化.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        client: httpx.Client | None = None,
        rate_limiter: HostRateLimiter | None = None,
    ) -> None:
        self.user_agent = user_agent
        self._client = client or httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": user_agent},
        )
        self.rate_limiter = rate_limiter or HostRateLimiter()

    def get_json(self, url: str, *, params: dict[str, object] | None = None, headers=None):
        """GET 并解析 JSON 响应; 404/5xx 抛出 httpx.HTTPStatusError."""
        headers = {"User-Agent": self.user_agent, **(headers or {})}
        self.rate_limiter.wait(url)
        return self._client.get(url, params=params, headers=headers).raise_for_status().json()

    def get_bytes(
        self,
        url: str,
        *,
        max_bytes: int,
        headers: dict[str, str] | None = None,
    ) -> DownloadedResponse:
        """GET 并返回原始字节, 限制最大大小."""
        headers = {"User-Agent": self.user_agent, **(headers or {})}
        self.rate_limiter.wait(url)
        response = self._client.get(url, headers=headers)
        response.raise_for_status()
        content = response.content
        if len(content) > max_bytes:
            raise httpx.HTTPStatusError(
                f"response exceeds {max_bytes} bytes", request=response.request, response=response
            )
        return DownloadedResponse(
            content=content,
            media_type=response.headers.get("content-type", "application/octet-stream"),
            final_url=str(response.url),
        )
