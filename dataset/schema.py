from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

SOURCE = "wikidata"
SOURCE_LICENSE = "CC0-1.0"


@dataclass(slots=True)
class CanonicalRecord:
    qid: str
    label_en: str | None
    label_vi: str | None
    description_en: str | None
    description_vi: str | None
    aliases_en: list[str]
    aliases_vi: list[str]
    instance_of_qids: list[str]
    source: str
    source_license: str
    document_en: str | None
    document_vi: str | None
    quality_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RejectedRecord:
    qid: str | None
    reason: str
