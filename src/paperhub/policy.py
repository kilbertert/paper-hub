"""来源门控政策: 每个来源允许/禁止搜索与下载."""

from __future__ import annotations

from dataclasses import dataclass

from .sources import FullTextCandidate, RightsStatus, SourceAccess, SourceName


class SourcePolicyError(RuntimeError):
    """来源策略违规时抛出."""


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    source: SourceName
    access: SourceAccess
    search_allowed: bool
    download_allowed: bool
    note: str


class SourcePolicyRegistry:
    """中心化策略门; 每个 connector 与下载都经过这里."""

    def __init__(self, *, core_license_confirmed: bool = False) -> None:
        self._policies = {
            SourceName.EUROPE_PMC: SourcePolicy(
                source=SourceName.EUROPE_PMC,
                access=SourceAccess.APPROVED_OPEN,
                search_allowed=True,
                download_allowed=True,
                note="Only explicit open-access full-text endpoints are downloadable.",
            ),
            SourceName.DOAJ: SourcePolicy(
                source=SourceName.DOAJ,
                access=SourceAccess.APPROVED_OPEN,
                search_allowed=True,
                download_allowed=False,
                note="DOAJ metadata is open; publisher full-text links require rights review.",
            ),
            SourceName.ARXIV: SourcePolicy(
                source=SourceName.ARXIV,
                access=SourceAccess.APPROVED_OPEN,
                search_allowed=True,
                download_allowed=True,
                note="arXiv full-text PDFs are open assets.",
            ),
            SourceName.OPENALEX: SourcePolicy(
                source=SourceName.OPENALEX,
                access=SourceAccess.APPROVED_OPEN,
                search_allowed=True,
                download_allowed=False,
                note="OpenAlex is a metadata index; links resolve elsewhere.",
            ),
            SourceName.CROSSREF: SourcePolicy(
                source=SourceName.CROSSREF,
                access=SourceAccess.APPROVED_OPEN,
                search_allowed=True,
                download_allowed=False,
                note="Crossref is a metadata register; no full-text assets.",
            ),
            SourceName.PUBMED: SourcePolicy(
                source=SourceName.PUBMED,
                access=SourceAccess.APPROVED_OPEN,
                search_allowed=True,
                download_allowed=False,
                note="PubMed is a metadata index; abstracts only.",
            ),
        }

    @staticmethod
    def is_blocked_url(url: str) -> bool:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").casefold()
        return "sci-hub" in host or "scihub" in host

    def policy_for(self, source: SourceName) -> SourcePolicy:
        return self._policies[source]

    def require_search_allowed(self, source: SourceName) -> None:
        policy = self.policy_for(source)
        if not policy.search_allowed:
            raise SourcePolicyError(policy.note)

    def require_download_allowed(self, candidate: FullTextCandidate) -> None:
        if self.is_blocked_url(candidate.url):
            raise SourcePolicyError("Blocked source URL: paywall-bypass sources are forbidden.")
        policy = self.policy_for(candidate.source)
        if not policy.download_allowed:
            raise SourcePolicyError(policy.note)
        if candidate.access not in {
            SourceAccess.APPROVED_OPEN,
            SourceAccess.APPROVED_LICENSED,
        }:
            raise SourcePolicyError(
                f"Candidate access status does not permit download: {candidate.access.value}"
            )
        if candidate.rights_status in {
            RightsStatus.METADATA_ONLY,
        }:
            raise SourcePolicyError("Candidate rights permit metadata storage only.")
