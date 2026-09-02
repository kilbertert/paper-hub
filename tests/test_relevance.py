from paperhub.expansion import QueryExpansion
from paperhub.merge import merge_records
from paperhub.models import PaperRecord
from paperhub.relevance import rank_papers
from paperhub.sources import SourceName

EXPANSION = QueryExpansion(
    intent="AI customer service",
    include_terms=("AI", "customer service", "chatbot", "conversational AI"),
    phrases=("AI客服", "customer service chatbot"),
)


def _paper(
    title: str, *, abstract: str | None = None, keywords: tuple[str, ...] = ()
) -> PaperRecord:
    return PaperRecord(
        source=SourceName.CROSSREF,
        source_id=title,
        title=title,
        abstract=abstract,
        keywords=keywords,
    )


def test_relevance_gate_removes_ai_only_results_and_exposes_match_explanation() -> None:
    relevant = _paper("Customer service chatbot evaluation")
    ai_only = _paper("Artificial intelligence in pediatric education")
    abstract_match = _paper(
        "Support systems", abstract="We evaluate conversational AI for customer service."
    )
    papers = merge_records((ai_only, relevant, abstract_match))

    ranked = rank_papers(papers, EXPANSION, original_query="AI客服", limit=10)

    assert [item.item.record.title for item in ranked] == [
        "Customer service chatbot evaluation",
        "Support systems",
    ]
    assert ranked[0].match_fields == ("title",)
    assert "customer service chatbot" in ranked[0].matched_terms
    assert "Artificial intelligence in pediatric education" not in {
        item.item.record.title for item in ranked
    }


def test_relevance_ranking_is_global_and_respects_limit() -> None:
    papers = merge_records(
        tuple(_paper(f"Customer service chatbot paper {index}") for index in range(5))
    )
    ranked = rank_papers(papers, EXPANSION, original_query="AI客服", limit=3)
    assert len(ranked) == 3
    assert [item.item.record.title for item in ranked] == [
        "Customer service chatbot paper 0",
        "Customer service chatbot paper 1",
        "Customer service chatbot paper 2",
    ]


def test_match_priority_is_title_phrase_then_title_terms_then_abstract() -> None:
    title_phrase = _paper("Customer service chatbot evaluation")
    title_terms = _paper("Customer service support evaluation")
    abstract_phrase = _paper("Support systems", abstract="Customer service chatbot evaluation")
    ranked = rank_papers(
        merge_records((abstract_phrase, title_terms, title_phrase)),
        EXPANSION,
        original_query="AI客服",
        limit=10,
    )
    assert [item.item.record.title for item in ranked] == [
        "Customer service chatbot evaluation",
        "Customer service support evaluation",
        "Support systems",
    ]


def test_single_generic_query_remains_searchable() -> None:
    papers = merge_records((_paper("Artificial intelligence methods"),))
    expansion = QueryExpansion("AI", ("AI", "artificial intelligence"), ("AI",))
    assert rank_papers(papers, expansion, original_query="AI", limit=10)
