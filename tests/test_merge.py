from paperhub.merge import merge_records
from paperhub.models import FullTextCandidate, PaperRecord
from paperhub.sources import FullTextFormat, SourceAccess, SourceName


def _record(source: SourceName, **values) -> PaperRecord:
    return PaperRecord(source=source, source_id=source.value, title="Same title", **values)


def test_duplicate_doi_prefers_downloadable_record_and_preserves_badges() -> None:
    metadata = _record(SourceName.CROSSREF, doi="10.1/same", abstract="More metadata")
    downloadable = _record(
        SourceName.EUROPE_PMC,
        doi="10.1/SAME",
        full_text_candidates=(
            FullTextCandidate(
                source=SourceName.EUROPE_PMC,
                source_id="PMC1",
                url="https://example.test/PMC1.xml",
                format=FullTextFormat.JATS_XML,
                access=SourceAccess.APPROVED_OPEN,
            ),
        ),
    )

    result = merge_records([metadata, downloadable])

    assert len(result) == 1
    assert result[0].record is downloadable
    assert result[0].primary_badge == "europe_pmc · 10.1/same"
    assert result[0].secondary_badges == ("crossref",)


def test_duplicate_without_download_prefers_more_complete_metadata() -> None:
    sparse = _record(SourceName.DOAJ, doi="10.2/same")
    complete = _record(
        SourceName.OPENALEX,
        doi="10.2/same",
        abstract="Abstract",
        publication_year=2024,
        authors=("Ada",),
    )

    assert merge_records([sparse, complete])[0].record is complete


def test_unique_records_remain_in_first_seen_order() -> None:
    first = _record(SourceName.ARXIV, doi="10.3/first")
    second = _record(SourceName.PUBMED, doi="10.3/second")

    assert [item.record for item in merge_records([first, second])] == [first, second]


def test_title_fingerprint_fallback_merges_same_title_and_year() -> None:
    first = _record(SourceName.DOAJ, publication_year=2022)
    duplicate = _record(SourceName.CROSSREF, publication_year=2022, abstract="Abstract")
    other_year = _record(SourceName.OPENALEX, publication_year=2023)

    result = merge_records([first, duplicate, other_year])

    assert len(result) == 2
    assert result[0].record is duplicate
