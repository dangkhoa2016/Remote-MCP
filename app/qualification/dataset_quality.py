from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import re

ENGLISH_MARKERS = frozenset({
    'the', 'of', 'and', 'in', 'to', 'for', 'with', 'from', 'city', 'state',
    'university', 'software', 'language', 'organization', 'capital', 'located',
})
VIETNAMESE_DIACRITICS = frozenset(
    'ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ'
    'ÁÀẢÃẠẤẦẨẪẬẮẰẲẴẶÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ'
)
_ALPHA_RE = re.compile(r"[A-Za-z]+")


def suspected_english_in_vi(text: str | None) -> bool:
    if not text:
        return False
    if any(ch in VIETNAMESE_DIACRITICS for ch in text):
        return False
    tokens = [token.lower() for token in _ALPHA_RE.findall(text)]
    if len(tokens) < 4:
        return False
    marker_count = sum(1 for token in tokens if token in ENGLISH_MARKERS)
    return marker_count >= 2


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def summarize_dataset_quality(rows: Iterable[dict]) -> dict:
    materialized = list(rows)
    total = len(materialized)
    fields = ('label_en', 'label_vi', 'description_en', 'description_vi', 'document_en', 'document_vi')
    null_rates = {
        field: _rate(sum(1 for row in materialized if not row.get(field)), total)
        for field in fields
    }

    identical: dict[str, dict[str, float | int]] = {}
    for stem in ('label', 'description', 'document'):
        en_key = f'{stem}_en'
        vi_key = f'{stem}_vi'
        count = sum(
            1 for row in materialized
            if row.get(en_key) and row.get(vi_key) and row.get(en_key) == row.get(vi_key)
        )
        identical[stem] = {'count': count, 'rate': _rate(count, total)}

    suspected: dict[str, dict[str, float | int]] = {}
    for field in ('label_vi', 'description_vi', 'document_vi'):
        non_null = sum(1 for row in materialized if row.get(field))
        count = sum(1 for row in materialized if suspected_english_in_vi(row.get(field)))
        suspected[field] = {
            'count': count,
            'rate_over_non_null': _rate(count, non_null),
            'non_null': non_null,
        }

    category_counts: Counter[str] = Counter()
    for row in materialized:
        for qid in row.get('instance_of_qids') or []:
            category_counts[str(qid)] += 1

    return {
        'row_count': total,
        'heuristic': {
            'name': 'suspected_english_in_vi',
            'purpose': 'signal only; not a language-identification ground truth claim',
            'minimum_ascii_alpha_tokens': 4,
            'minimum_english_markers': 2,
            'requires_no_vietnamese_specific_diacritics': True,
            'english_markers': sorted(ENGLISH_MARKERS),
        },
        'null_rates': null_rates,
        'identical_en_vi': identical,
        'suspected_english_vi': suspected,
        'category_coverage': {
            qid: {'rows': count, 'rate': _rate(count, total)}
            for qid, count in sorted(category_counts.items())
        },
    }
