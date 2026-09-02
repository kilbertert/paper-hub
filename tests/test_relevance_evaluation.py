from paperhub.expansion import QueryExpansion
from paperhub.merge import merge_records
from paperhub.models import PaperRecord
from paperhub.relevance import rank_papers
from paperhub.sources import SourceName

FIXTURES = {
    "AI客服": QueryExpansion(
        "AI customer service",
        ("AI", "artificial intelligence", "customer service", "chatbot", "conversational AI"),
        ("AI客服", "customer service chatbot"),
    ),
    "人工智能客服": QueryExpansion(
        "AI customer service",
        ("人工智能", "artificial intelligence", "customer service", "chatbot", "conversational AI"),
        ("人工智能客服", "customer service chatbot"),
    ),
    "customer service chatbot": QueryExpansion(
        "customer service chatbot",
        ("customer service", "chatbot", "conversational AI", "virtual agent"),
        ("customer service chatbot",),
    ),
}


def test_frozen_compound_query_fixtures_have_precision_gate() -> None:
    for query, expansion in FIXTURES.items():
        records = tuple(
            PaperRecord(
                source=SourceName.CROSSREF,
                source_id=f"relevant-{i}",
                title=f"{query} chatbot study {i}",
            )
            for i in range(8)
        ) + (
            PaperRecord(
                source=SourceName.CROSSREF,
                source_id="generic",
                title="Artificial intelligence in medicine",
            ),
            PaperRecord(source=SourceName.CROSSREF, source_id="generic-2", title="AI education"),
        )
        ranked = rank_papers(merge_records(records), expansion, original_query=query, limit=10)
        assert len(ranked) == 8
        assert all(item.match_fields for item in ranked)
        assert all("generic" not in item.item.record.source_id for item in ranked)
