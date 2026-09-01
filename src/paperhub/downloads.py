"""Policy-gated full-text acquisition with a content-addressed file cache."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .http import HttpClient
from .models import FullTextCandidate
from .policy import SourcePolicyRegistry
from .sources import FullTextFormat


class InvalidFullText(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CachedObject:
    path: Path
    media_type: str


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)

    def path_for(self, candidate: FullTextCandidate) -> Path:
        key = hashlib.sha256(candidate.url.encode()).hexdigest()
        suffix = ".pdf" if candidate.format == FullTextFormat.PDF else ".xml"
        return self.root / f"{key}{suffix}"

    def put(self, path: Path, content: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        os.chmod(temporary, 0o640)
        temporary.replace(path)


def validate_full_text(content: bytes, format: FullTextFormat) -> None:
    if format == FullTextFormat.PDF:
        if not content.startswith(b"%PDF-"):
            raise InvalidFullText("source did not return a PDF")
        return
    if format in {FullTextFormat.JATS_XML, FullTextFormat.XML}:
        try:
            root = ET.fromstring(content)
        except ET.ParseError as error:
            raise InvalidFullText("source did not return valid XML") from error
        if root.tag.rsplit("}", 1)[-1] != "article":
            raise InvalidFullText("XML root must be <article>")
        return
    raise InvalidFullText(f"unsupported proxy format: {format.value}")


class FullTextDownloader:
    def __init__(
        self, http: HttpClient, store: ObjectStore, policy: SourcePolicyRegistry | None = None
    ) -> None:
        self.http = http
        self.store = store
        self.policy = policy or SourcePolicyRegistry()

    def acquire(self, candidate: FullTextCandidate) -> CachedObject:
        self.policy.require_download_allowed(candidate)
        path = self.store.path_for(candidate)
        if path.is_file():
            return CachedObject(path, candidate.media_type or _media_type(candidate.format))
        response = self.http.get_bytes(candidate.url, max_bytes=100_000_000)
        validate_full_text(response.content, candidate.format)
        self.store.put(path, response.content)
        return CachedObject(path, candidate.media_type or response.media_type)


def _media_type(format: FullTextFormat) -> str:
    return "application/pdf" if format == FullTextFormat.PDF else "application/xml"
