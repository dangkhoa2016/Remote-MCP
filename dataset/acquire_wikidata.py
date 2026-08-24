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


def _scaled_candidate_quotas(
    seeds: Iterable[SeedCategory], target_rows: int, overfetch_factor: float
) -> dict[str, int]:
    seeds = tuple(seeds)
    total_weight = sum(seed.weight for seed in seeds)
    if total_weight <= 0:
        raise ValueError("seed weights must sum to a positive number")
    candidate_target = max(target_rows, math.ceil(target_rows * overfetch_factor))
    return {
        seed.name: max(1, math.ceil(candidate_target * seed.weight / total_weight))
        for seed in seeds
    }


def acquire_wikidata_raw(
    output_dir: Path,
    *,
    target_rows: int,
    client: WikidataClientProtocol,
    seeds: Iterable[SeedCategory] = DEFAULT_SEEDS,
    discovery_page_size: int = 250,
    entity_batch_size: int = 50,
    overfetch_factor: float = 1.35,
    max_discovery_factor: float = 2.5,
) -> AcquisitionResult:
    """Acquire a resumable raw EN/VI structured corpus from official Wikidata endpoints."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if target_rows < 1:
        raise ValueError("target_rows must be >= 1")
    if discovery_page_size < 1 or discovery_page_size > 1000:
        raise ValueError("discovery_page_size must be in 1..1000")
    if entity_batch_size < 1 or entity_batch_size > 50:
        raise ValueError("entity_batch_size must be in 1..50")
    if overfetch_factor < 1.0:
        raise ValueError("overfetch_factor must be >= 1.0")
    if max_discovery_factor < overfetch_factor:
        raise ValueError("max_discovery_factor must be >= overfetch_factor")

    seeds = tuple(seeds)
    if not seeds:
        raise ValueError("at least one seed category is required")
    names = [seed.name for seed in seeds]
    if len(set(names)) != len(names):
        raise ValueError("seed category names must be unique")
    for seed in seeds:
        if not seed.name.strip() or not _QID_RE.fullmatch(seed.instance_of_qid) or seed.weight < 1:
            raise ValueError(f"invalid seed category: {seed}")

    raw_qids_path = output_dir / "raw-qids.jsonl"
    raw_entities_path = output_dir / "raw-wikidata-en-vi.jsonl"
    state_path = output_dir / "acquisition-state.json"

    qid_sources: dict[str, dict[str, set[str]]] = {}
    for row in _load_jsonl(raw_qids_path):
        qid = str(row.get("qid") or "")
        if not _QID_RE.fullmatch(qid):
            raise ValueError(f"invalid qid in resume file: {qid!r}")
        qid_sources[qid] = {
            "seed_names": set(str(x) for x in (row.get("seed_names") or [])),
            "seed_qids": set(str(x) for x in (row.get("seed_instance_of_qids") or [])),
        }

    entity_rows: dict[str, dict] = {}
    accepted = 0
    for row in _load_jsonl(raw_entities_path):
        qid = str(row.get("qid") or "")
        if not _QID_RE.fullmatch(qid):
            raise ValueError(f"invalid qid in raw entity resume file: {qid!r}")
        if qid in entity_rows:
            continue
        entity_rows[qid] = row
        if isinstance(canonicalize_record(row), CanonicalRecord):
            accepted += 1

    state: dict[str, Any] = {}
    if state_path.is_file():
        loaded = json.loads(state_path.read_text(encoding="utf-8", errors="strict"))
        if isinstance(loaded, dict):
            state = loaded
    seed_offsets = {str(k): int(v) for k, v in (state.get("seed_offsets") or {}).items()}
    exhausted = {str(x) for x in (state.get("exhausted_seeds") or [])}

    if accepted >= target_rows:
        return AcquisitionResult(
            output_dir=output_dir,
            raw_qids_path=raw_qids_path,
            raw_entities_path=raw_entities_path,
            state_path=state_path,
            unique_qids=len(qid_sources),
            fetched_entities=len(entity_rows),
            accepted_rows=accepted,
        )

    quotas = _scaled_candidate_quotas(seeds, target_rows, overfetch_factor)
    max_discovered_positions = max(
        sum(seed_offsets.values()),
        math.ceil(target_rows * max_discovery_factor),
    )

    def persist_state() -> None:
        _write_qid_rows(raw_qids_path, qid_sources)
        _atomic_write_json(
            state_path,
            {
                "format_version": 1,
                "updated_at_utc": _now_utc(),
                "target_rows": target_rows,
                "unique_qids": len(qid_sources),
                "fetched_entities": len(entity_rows),
                "accepted_rows": accepted,
                "seed_offsets": dict(sorted(seed_offsets.items())),
                "exhausted_seeds": sorted(exhausted),
                "seed_candidate_quotas": quotas,
                "max_discovery_factor": max_discovery_factor,
                "source": "wikidata",
                "source_license": "CC0-1.0",
                "wdqs_endpoint": WDQS_ENDPOINT,
                "action_api_endpoint": ACTION_API_ENDPOINT,
            },
        )

    def fetch_new(qids: list[str]) -> None:
        nonlocal accepted
        for batch in _chunked(qids, entity_batch_size):
            records = client.fetch_entities(batch)
            if records:
                with raw_entities_path.open("a", encoding="utf-8") as fh:
                    for row in records:
                        qid = str(row.get("qid") or "")
                        if not _QID_RE.fullmatch(qid) or qid in entity_rows:
                            continue
                        entity_rows[qid] = row
                        if isinstance(canonicalize_record(row), CanonicalRecord):
                            accepted += 1
                        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            persist_state()
            if accepted >= target_rows:
                return

    def discover_page(seed: SeedCategory, request_limit: int) -> int:
        offset = seed_offsets.get(seed.name, 0)
        discovered = client.discover_qids(
            seed.instance_of_qid,
            offset=offset,
            limit=request_limit,
        )
        if not discovered:
            exhausted.add(seed.name)
            persist_state()
            return 0
        seed_offsets[seed.name] = offset + len(discovered)
        new_to_fetch: list[str] = []
        for qid in discovered:
            if not _QID_RE.fullmatch(qid):
                continue
            info = qid_sources.setdefault(qid, {"seed_names": set(), "seed_qids": set()})
            info["seed_names"].add(seed.name)
            info["seed_qids"].add(seed.instance_of_qid)
            if qid not in entity_rows and qid not in new_to_fetch:
                new_to_fetch.append(qid)
        _write_qid_rows(raw_qids_path, qid_sources)
        fetch_new(new_to_fetch)
        if len(discovered) < request_limit:
            exhausted.add(seed.name)
            persist_state()
        return len(discovered)

    # Phase 1: diversity-oriented weighted quotas.
    for seed in seeds:
        if accepted >= target_rows:
            break
        if seed.name in exhausted:
            continue
        attributed = sum(1 for info in qid_sources.values() if seed.name in info["seed_names"])
        quota = quotas[seed.name]
        while attributed < quota and accepted < target_rows:
            request_limit = min(discovery_page_size, quota - attributed)
            before = attributed
            got = discover_page(seed, request_limit)
            attributed = sum(1 for info in qid_sources.values() if seed.name in info["seed_names"])
            if got == 0 or seed.name in exhausted or attributed <= before:
                break

    # Phase 2: bounded spillover redistributes shortfalls from sparse/duplicate categories.
    # This preserves diversity first, then favors completion without unbounded crawling.
    while accepted < target_rows and sum(seed_offsets.values()) < max_discovered_positions:
        progressed = False
        for seed in seeds:
            if accepted >= target_rows:
                break
            if seed.name in exhausted:
                continue
            remaining_budget = max_discovered_positions - sum(seed_offsets.values())
            if remaining_budget <= 0:
                break
            request_limit = min(discovery_page_size, remaining_budget)
            before_offset = seed_offsets.get(seed.name, 0)
            got = discover_page(seed, request_limit)
            if seed_offsets.get(seed.name, 0) > before_offset or got > 0:
                progressed = True
        if not progressed:
            break

    persist_state()
    if accepted < target_rows:
        raise AcquisitionShortfallError(
            f"Wikidata acquisition shortfall: target_rows={target_rows}, accepted_rows={accepted}, "
            f"unique_qids={len(qid_sources)}, discovered_positions={sum(seed_offsets.values())}, "
            f"max_discovery_factor={max_discovery_factor}. Re-run with a larger max discovery factor "
            "or additional seed classes."
        )
    return AcquisitionResult(
        output_dir=output_dir,
        raw_qids_path=raw_qids_path,
        raw_entities_path=raw_entities_path,
        state_path=state_path,
        unique_qids=len(qid_sources),
        fetched_entities=len(entity_rows),
        accepted_rows=accepted,
    )

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire resumable structured EN/VI Wikidata records using WDQS + Wikibase Action API"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--target-rows", type=int, default=100_000)
    parser.add_argument("--user-agent", required=True, help="Descriptive Wikimedia User-Agent with contact info")
    parser.add_argument("--discovery-page-size", type=int, default=250)
    parser.add_argument("--entity-batch-size", type=int, default=50)
    parser.add_argument("--overfetch-factor", type=float, default=1.35)
    parser.add_argument("--min-request-interval", type=float, default=0.35)
    parser.add_argument("--max-discovery-factor", type=float, default=2.5)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()

    client = WikidataClient(
        args.user_agent,
        min_request_interval=args.min_request_interval,
        timeout_seconds=args.timeout_seconds,
    )
    result = acquire_wikidata_raw(
        args.output_dir,
        target_rows=args.target_rows,
        client=client,
        discovery_page_size=args.discovery_page_size,
        entity_batch_size=args.entity_batch_size,
        overfetch_factor=args.overfetch_factor,
        max_discovery_factor=args.max_discovery_factor,
    )
    print(f"RAW_QIDS={result.raw_qids_path}")
    print(f"RAW_ENTITIES={result.raw_entities_path}")
    print(f"UNIQUE_QIDS={result.unique_qids}")
    print(f"FETCHED_ENTITIES={result.fetched_entities}")
    print(f"ACCEPTED_ROWS={result.accepted_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
