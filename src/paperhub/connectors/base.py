"""来源连接器的抽象 seam: search() -> SearchPage."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import SearchPage, SourceName


class LiteratureConnector(ABC):
    """论文发现服务的统一接口.

    每个来源一个实现, 把各自 API 响应归一化为 canonical ``PaperRecord``.
    这是 paper-hub 的单一测试 seam: 后续 connector 适配、跨源合并、
    搜索 HTTP 层都收敛在这里.
    """

    source: SourceName

    @abstractmethod
    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        """返回由 ``PaperRecord`` 组成的一页搜索结果."""
        ...


class StubConnector(LiteratureConnector):
    """占位 implemention: 让 T01 的测试 seam 端到端可跑.

    返回零结果; 后续 T02 以真实 connector 替换. 当前仅用于证明 seam 契约.
    """

    source = SourceName.ARXIV

    def search(self, query: str, *, limit: int = 25, cursor: str | None = None) -> SearchPage:
        return SearchPage(records=(), next_cursor=None, total=0)


__all__ = ["LiteratureConnector", "StubConnector"]
