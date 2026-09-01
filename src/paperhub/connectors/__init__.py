"""来源连接器包. T01 只有抽象 seam 与占位 stub; 真实六源在 T02 落地."""

from .base import LiteratureConnector, StubConnector
from .sources import (
    ArxivConnector,
    CrossrefConnector,
    DoajConnector,
    EuropePmcConnector,
    OpenAlexConnector,
    PubmedConnector,
    search_connectors,
)

__all__ = [
    "ArxivConnector",
    "CrossrefConnector",
    "DoajConnector",
    "EuropePmcConnector",
    "LiteratureConnector",
    "OpenAlexConnector",
    "PubmedConnector",
    "StubConnector",
    "search_connectors",
]
