from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.unicode_quality import UnicodeQualityError, normalize_aliases, normalize_text
from dataset.schema import CanonicalRecord, RejectedRecord, SOURCE, SOURCE_LICENSE


def _clean_optional(value: Any) -> tuple[str | None, list[str]]:
    if value is None:
        return None, []
    result = normalize_text(str(value))
    return (result.text or None), list(result.flags)


def _document(label: str | None, description: str | None, aliases: list[str]) -> str | None:
    if not label:
        return None
    parts = [f"{label}."]
    if description:
        parts.append(f"{description}.")
    if aliases:
        parts.append("Aliases: " + "; ".join(aliases) + ".")
    return " ".join(parts)


def canonicalize_record(raw: Mapping[str, Any]) -> CanonicalRecord | RejectedRecord:
    qid_raw = raw.get("qid")
    qid = str(qid_raw).strip() if qid_raw is not None else None
    try:
        label_en, f1 = _clean_optional(raw.get("label_en"))
        label_vi, f2 = _clean_optional(raw.get("label_vi"))
        description_en, f3 = _clean_optional(raw.get("description_en"))
        description_vi, f4 = _clean_optional(raw.get("description_vi"))
        aliases_en, f5 = normalize_aliases(raw.get("aliases_en") or [])
        aliases_vi, f6 = normalize_aliases(raw.get("aliases_vi") or [])
    except UnicodeQualityError as exc:
        return RejectedRecord(qid=qid, reason=f"unicode_quality:{exc}")

    if not label_en and not label_vi:
        return RejectedRecord(qid=qid, reason="missing_usable_label")

    instance_of_qids: list[str] = []
    seen: set[str] = set()
    for value in raw.get("instance_of_qids") or []:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            instance_of_qids.append(cleaned)

    document_en = _document(label_en, description_en, aliases_en)
    document_vi = _document(label_vi, description_vi, aliases_vi)
    if not document_en and not document_vi:
        return RejectedRecord(qid=qid, reason="missing_usable_document")

    flags = sorted(set([*f1, *f2, *f3, *f4, *f5, *f6]))
    return CanonicalRecord(
        qid=qid or "",
        label_en=label_en,
        label_vi=label_vi,
        description_en=description_en,
        description_vi=description_vi,
        aliases_en=aliases_en,
        aliases_vi=aliases_vi,
        instance_of_qids=instance_of_qids,
        source=SOURCE,
        source_license=SOURCE_LICENSE,
        document_en=document_en,
        document_vi=document_vi,
        quality_flags=flags,
    )


__all__ = ["CanonicalRecord", "RejectedRecord", "canonicalize_record"]
