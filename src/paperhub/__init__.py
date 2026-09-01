"""paper-hub: 合规开放论文下载站核心包."""

from .merge import MergedPaper, merge_records
from .models import (
    FullTextFormat,
    PaperRecord,
    SearchPage,
    SourceAccess,
    SourceName,
    canonical_key,
    normalize_doi,
)

__all__ = [
    "FullTextFormat",
    "MergedPaper",
    "PaperRecord",
    "SearchPage",
    "SourceAccess",
    "SourceName",
    "canonical_key",
    "merge_records",
    "normalize_doi",
]
