from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Iterable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dataset.normalize import canonicalize_record
from dataset.schema import CanonicalRecord

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
ACTION_API_ENDPOINT = "https://www.wikidata.org/w/api.php"
_QID_RE = re.compile(r"^Q[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class SeedCategory:
    name: str
    instance_of_qid: str
    weight: int


# Direct P31 classes are intentional: subclass-closure queries are much heavier on
# the public WDQS service. The weights are a diversity policy, not a claim that
# every category will contribute exactly that share after deduplication/rejection.
DEFAULT_SEEDS: tuple[SeedCategory, ...] = (
    SeedCategory("human", "Q5", 20),
    SeedCategory("city", "Q515", 10),
    SeedCategory("human_settlement", "Q486972", 8),
    SeedCategory("organization", "Q43229", 9),
    SeedCategory("business_enterprise", "Q4830453", 7),
    SeedCategory("university", "Q3918", 6),
    SeedCategory("software", "Q7397", 8),
    SeedCategory("programming_language", "Q9143", 3),
    SeedCategory("disease", "Q12136", 7),
    SeedCategory("occupation", "Q12737077", 6),
    SeedCategory("scientific_discipline", "Q11862829", 5),
    SeedCategory("chemical_compound", "Q11173", 11),
)


class AcquisitionShortfallError(RuntimeError):
    pass


class WikidataTransportError(RuntimeError):
    pass


class WikidataClientProtocol(Protocol):
    def discover_qids(self, instance_of_qid: str, *, offset: int, limit: int) -> list[str]: ...

    def fetch_entities(self, qids: list[str]) -> list[dict]: ...


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    output_dir: Path
    raw_qids_path: Path
    raw_entities_path: Path
    state_path: Path
    unique_qids: int
    fetched_entities: int
    accepted_rows: int


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _qid_sort_key(qid: str) -> tuple[int, str]:
    if _QID_RE.fullmatch(qid):
        return int(qid[1:]), qid
    return 2**63 - 1, qid


def validate_user_agent(value: str) -> str:
    value = (value or "").strip()
    lowered = value.lower()
    has_contact = "(" in value and ")" in value and (
        "http://" in lowered
        or "https://" in lowered
        or "mailto:" in lowered
        or "@" in value
        or "user:" in lowered
    )
    generic = lowered.startswith(("python-requests/", "python-urllib/", "curl/", "wget/"))
    if len(value) < 12 or generic or not has_contact:
        raise ValueError(
            "A descriptive Wikimedia User-Agent with contact information is required, "
            "for example: QwenDatasetBot/0.1 (https://example.com/contact)"
        )
    return value


def _lang_value(container: Any, lang: str) -> str | None:
    if not isinstance(container, dict):
        return None
    entry = container.get(lang)
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    return value if isinstance(value, str) and value.strip() else None


def _aliases(container: Any, lang: str) -> list[str]:
    if not isinstance(container, dict):
        return []
    values = container.get(lang)
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for entry in values:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if isinstance(value, str) and value.strip() and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _instance_of_qids(claims: Any) -> list[str]:
    if not isinstance(claims, dict):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for claim in claims.get("P31") or []:
        if not isinstance(claim, dict) or claim.get("rank") == "deprecated":
            continue
        mainsnak = claim.get("mainsnak")
        if not isinstance(mainsnak, dict) or mainsnak.get("snaktype") != "value":
            continue
        datavalue = mainsnak.get("datavalue")
        value = datavalue.get("value") if isinstance(datavalue, dict) else None
        qid = value.get("id") if isinstance(value, dict) else None
        if isinstance(qid, str) and _QID_RE.fullmatch(qid) and qid not in seen:
            seen.add(qid)
            result.append(qid)
    return result


def parse_wikibase_entity(entity: dict[str, Any]) -> dict[str, Any]:
    qid = str(entity.get("id") or "").strip()
    if not _QID_RE.fullmatch(qid):
        raise ValueError(f"invalid Wikidata item id: {qid!r}")
    return {
        "qid": qid,
        "label_en": _lang_value(entity.get("labels"), "en"),
        "label_vi": _lang_value(entity.get("labels"), "vi"),
        "description_en": _lang_value(entity.get("descriptions"), "en"),
        "description_vi": _lang_value(entity.get("descriptions"), "vi"),
        "aliases_en": _aliases(entity.get("aliases"), "en"),
        "aliases_vi": _aliases(entity.get("aliases"), "vi"),
        "instance_of_qids": _instance_of_qids(entity.get("claims")),
    }


class WikidataClient:
    """Sequential, polite client for WDQS discovery + Wikibase entity hydration."""

    def __init__(
        self,
        user_agent: str,
        *,
        min_request_interval: float = 0.35,
        timeout_seconds: float = 60.0,
        max_retries: int = 6,
    ) -> None:
        self.user_agent = validate_user_agent(user_agent)
        if min_request_interval < 0:
            raise ValueError("min_request_interval must be >= 0")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self.min_request_interval = float(min_request_interval)
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self._last_request_monotonic = 0.0

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self.min_request_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(params)
        target = f"{url}?{query}"
        last_error: BaseException | None = None
        for attempt in range(self.max_retries):
            self._pace()
            request = Request(
                target,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/sparql-results+json, application/json;q=0.9",
                },
                method="GET",
            )
            retry_after: float | None = None
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310: fixed HTTPS endpoints
                    payload = json.loads(response.read().decode("utf-8", errors="strict"))
                self._last_request_monotonic = time.monotonic()
                if not isinstance(payload, dict):
                    raise WikidataTransportError("Wikimedia endpoint returned non-object JSON")
                error = payload.get("error")
                if isinstance(error, dict) and error.get("code") == "maxlag":
                    raise WikidataTransportError(f"Wikimedia maxlag: {error.get('info', 'busy')}")
                return payload
            except HTTPError as exc:
                self._last_request_monotonic = time.monotonic()
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504):
                    raise WikidataTransportError(f"HTTP {exc.code} from Wikimedia endpoint") from exc
                header = exc.headers.get("Retry-After") if exc.headers else None
                if header:
                    try:
                        retry_after = float(header)
                    except ValueError:
                        retry_after = None
            except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, WikidataTransportError) as exc:
                self._last_request_monotonic = time.monotonic()
                last_error = exc

            if attempt + 1 >= self.max_retries:
                break
            delay = retry_after if retry_after is not None else min(30.0, 1.0 * (2**attempt))
            time.sleep(max(self.min_request_interval, delay))

        raise WikidataTransportError(
            f"Wikimedia request failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    def discover_qids(self, instance_of_qid: str, *, offset: int, limit: int) -> list[str]:
        if not _QID_RE.fullmatch(instance_of_qid):
            raise ValueError(f"invalid seed QID: {instance_of_qid}")
        if offset < 0 or limit < 1 or limit > 1000:
            raise ValueError("WDQS offset must be >= 0 and limit must be in 1..1000")
        sparql = f"""
SELECT ?item WHERE {{
  ?item wdt:P31 wd:{instance_of_qid} .
}}
ORDER BY ?item
LIMIT {limit}
OFFSET {offset}
""".strip()
        payload = self._request_json(WDQS_ENDPOINT, {"query": sparql, "format": "json"})
        bindings = ((payload.get("results") or {}).get("bindings") or [])
        result: list[str] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            value = ((binding.get("item") or {}).get("value"))
            if not isinstance(value, str):
                continue
            qid = value.rsplit("/", 1)[-1]
            if _QID_RE.fullmatch(qid):
                result.append(qid)
        return result

    def fetch_entities(self, qids: list[str]) -> list[dict]:
        if not qids:
            return []
        if len(qids) > 50:
            raise ValueError("Wikibase Action API supports at most 50 entity IDs per request")
        for qid in qids:
            if not _QID_RE.fullmatch(qid):
                raise ValueError(f"invalid Wikidata item id: {qid}")
        payload = self._request_json(
            ACTION_API_ENDPOINT,
            {
                "action": "wbgetentities",
                "format": "json",
                "formatversion": "2",
                "ids": "|".join(qids),
                "props": "labels|descriptions|aliases|claims",
                "languages": "en|vi",
                "languagefallback": "0",
                "maxlag": "5",
            },
        )
        entities = payload.get("entities") or {}
        if isinstance(entities, list):
            by_id = {str(entity.get("id")): entity for entity in entities if isinstance(entity, dict)}
        elif isinstance(entities, dict):
            by_id = {str(key): value for key, value in entities.items() if isinstance(value, dict)}
        else:
            raise WikidataTransportError("Wikibase response is missing entities")
        result: list[dict] = []
        for qid in qids:
            entity = by_id.get(qid)
            if not entity or entity.get("missing") is True:
                continue
            result.append(parse_wikibase_entity(entity))
        return result


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="strict") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(value)
    return rows


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_qid_rows(path: Path, qid_sources: dict[str, dict[str, set[str]]]) -> None:
    lines: list[str] = []
    for qid in sorted(qid_sources, key=_qid_sort_key):
        info = qid_sources[qid]
        row = {
            "qid": qid,
            "seed_names": sorted(info["seed_names"]),
            "seed_instance_of_qids": sorted(info["seed_qids"], key=_qid_sort_key),
        }
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _accepted_count(rows_by_qid: dict[str, dict]) -> int:
    count = 0
    for row in rows_by_qid.values():
        normalized = canonicalize_record(row)
        if isinstance(normalized, CanonicalRecord):
            count += 1
    return count


def _chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]



def acquire_wikidata_raw(*args, **kwargs):
    """Development placeholder completed by the next history step."""
    raise NotImplementedError("resumable acquisition orchestration not added yet")
