"""六源支持的来源身份与访问/权利门控枚举."""

from __future__ import annotations

from enum import StrEnum


class SourceName(StrEnum):
    """paper-hub 支持的论文来源平台标识."""

    EUROPE_PMC = "europe_pmc"
    DOAJ = "doaj"
    ARXIV = "arxiv"
    OPENALEX = "openalex"
    CROSSREF = "crossref"
    PUBMED = "pubmed"
    UNPAYWALL = "unpaywall"


class SourceAccess(StrEnum):
    """对来源资源的访问层级, 决定下载是否被允许."""

    APPROVED_OPEN = "approved_open"
    APPROVED_LICENSED = "approved_licensed"
    METADATA_ONLY = "metadata_only"
    MANUAL_REVIEW = "manual_review"
    BLOCKED = "blocked"


class RightsStatus(StrEnum):
    """对下载到的全文可再分发/再利用的权利状态."""

    REDISTRIBUTABLE = "redistributable"
    INTERNAL_TDM_ONLY = "internal_tdm_only"
    METADATA_ONLY = "metadata_only"
    UNKNOWN = "unknown"


class FullTextFormat(StrEnum):
    """全文物件的格式标识, 用于下载后的校验."""

    JATS_XML = "jats_xml"
    XML = "xml"
    HTML = "html"
    PDF = "pdf"
    UNKNOWN = "unknown"
