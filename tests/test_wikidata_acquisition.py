from pathlib import Path
import json

import pytest


def _entity(qid: str, *, en: str | None = None, vi: str | None = None, p31: tuple[str, ...] = ()) -> dict:
    labels = {}
    if en:
        labels['en'] = {'language': 'en', 'value': en}
    if vi:
        labels['vi'] = {'language': 'vi', 'value': vi}
    return {
        'id': qid,
        'labels': labels,
        'descriptions': {
            'en': {'language': 'en', 'value': f'{en} description'} if en else {},
            'vi': {'language': 'vi', 'value': f'mô tả {vi}'} if vi else {},
        },
        'aliases': {
            'en': [{'language': 'en', 'value': f'{en} alias'}] if en else [],
            'vi': [{'language': 'vi', 'value': f'{vi} bí danh'}] if vi else [],
        },
        'claims': {
            'P31': [
                {
                    'rank': 'normal',
                    'mainsnak': {
                        'snaktype': 'value',
                        'datavalue': {'value': {'entity-type': 'item', 'id': parent}},
                    },
                }
                for parent in p31
            ]
        },
    }


def test_parse_wikibase_entity_extracts_only_structured_en_vi_fields():
    from dataset.acquire_wikidata import parse_wikibase_entity

    raw = _entity('Q64', en='Berlin', vi='Berlin', p31=('Q515', 'Q200250'))
    raw['aliases']['fr'] = [{'language': 'fr', 'value': 'Berlin FR'}]
    raw['claims']['P31'].append(
        {
            'rank': 'deprecated',
            'mainsnak': {
                'snaktype': 'value',
                'datavalue': {'value': {'entity-type': 'item', 'id': 'Q999'}},
            },
        }
    )

    record = parse_wikibase_entity(raw)

    assert record == {
        'qid': 'Q64',
        'label_en': 'Berlin',
        'label_vi': 'Berlin',
        'description_en': 'Berlin description',
        'description_vi': 'mô tả Berlin',
        'aliases_en': ['Berlin alias'],
        'aliases_vi': ['Berlin bí danh'],
        'instance_of_qids': ['Q515', 'Q200250'],
    }
    assert 'fr' not in json.dumps(record, ensure_ascii=False)
    assert 'Q999' not in record['instance_of_qids']


def test_descriptive_user_agent_is_required():
    from dataset.acquire_wikidata import validate_user_agent

    with pytest.raises(ValueError, match='contact'):
        validate_user_agent('python-requests/2.0')
    with pytest.raises(ValueError, match='contact'):
        validate_user_agent('MyBot/1.0')
    assert validate_user_agent('QwenDatasetBot/0.1 (https://example.test/contact)')


class FakeWikidataClient:
    def __init__(self, pages: dict[tuple[str, int], list[str]], entities: dict[str, dict]):
        self.pages = pages
        self.entities = entities
        self.discovery_calls: list[tuple[str, int, int]] = []
        self.fetch_calls: list[list[str]] = []

    def discover_qids(self, instance_of_qid: str, *, offset: int, limit: int) -> list[str]:
        self.discovery_calls.append((instance_of_qid, offset, limit))
        return list(self.pages.get((instance_of_qid, offset), []))[:limit]

    def fetch_entities(self, qids: list[str]) -> list[dict]:
        from dataset.acquire_wikidata import parse_wikibase_entity

        self.fetch_calls.append(list(qids))
        return [parse_wikibase_entity(self.entities[qid]) for qid in qids if qid in self.entities]


def test_acquisition_is_resumable_deduplicated_and_stops_on_accepted_target(tmp_path: Path):
    from dataset.acquire_wikidata import SeedCategory, acquire_wikidata_raw

    client = FakeWikidataClient(
        pages={
            ('Q5', 0): ['Q1', 'Q2'],
            ('Q5', 2): ['Q3'],
            ('Q515', 0): ['Q2', 'Q4'],
        },
        entities={
            'Q1': _entity('Q1', en='one', p31=('Q5',)),
            'Q2': _entity('Q2', en='two', vi='hai', p31=('Q5',)),
            'Q3': _entity('Q3', p31=('Q5',)),  # rejected: no usable label
            'Q4': _entity('Q4', vi='bốn', p31=('Q515',)),
        },
    )
    seeds = [SeedCategory('human', 'Q5', 3), SeedCategory('city', 'Q515', 2)]

    result = acquire_wikidata_raw(
        tmp_path,
        target_rows=3,
        client=client,
        seeds=seeds,
        discovery_page_size=2,
        entity_batch_size=2,
    )

    assert result.accepted_rows == 3
    assert result.unique_qids == 4
    raw_rows = [json.loads(line) for line in result.raw_entities_path.read_text(encoding='utf-8').splitlines()]
    assert [row['qid'] for row in raw_rows] == ['Q1', 'Q2', 'Q3', 'Q4']
    assert len({row['qid'] for row in raw_rows}) == 4
    qid_rows = [json.loads(line) for line in result.raw_qids_path.read_text(encoding='utf-8').splitlines()]
    q2 = [row for row in qid_rows if row['qid'] == 'Q2']
    assert len(q2) == 1
    assert sorted(q2[0]['seed_names']) == ['city', 'human']

    before_discovery = list(client.discovery_calls)
    before_fetch = list(client.fetch_calls)
    resumed = acquire_wikidata_raw(
        tmp_path,
        target_rows=3,
        client=client,
        seeds=seeds,
        discovery_page_size=2,
        entity_batch_size=2,
    )
    assert resumed.accepted_rows == 3
    assert client.discovery_calls == before_discovery
    assert client.fetch_calls == before_fetch


def test_acquisition_fails_closed_when_sources_cannot_reach_target(tmp_path: Path):
    from dataset.acquire_wikidata import SeedCategory, AcquisitionShortfallError, acquire_wikidata_raw

    client = FakeWikidataClient(
        pages={('Q5', 0): ['Q1']},
        entities={'Q1': _entity('Q1', en='only row', p31=('Q5',))},
    )
    with pytest.raises(AcquisitionShortfallError, match='target_rows=2'):
        acquire_wikidata_raw(
            tmp_path,
            target_rows=2,
            client=client,
            seeds=[SeedCategory('human', 'Q5', 1)],
            discovery_page_size=10,
            entity_batch_size=10,
        )


def test_acquisition_redistributes_shortfall_with_bounded_spillover(tmp_path: Path):
    from dataset.acquire_wikidata import SeedCategory, acquire_wikidata_raw

    client = FakeWikidataClient(
        pages={
            ('Q5', 0): ['Q1', 'Q2'],
            ('Q515', 0): ['Q3'],
            ('Q5', 2): ['Q4'],
        },
        entities={
            'Q1': _entity('Q1', en='one', p31=('Q5',)),
            'Q2': _entity('Q2', p31=('Q5',)),
            'Q3': _entity('Q3', en='three', p31=('Q515',)),
            'Q4': _entity('Q4', vi='bốn', p31=('Q5',)),
        },
    )
    result = acquire_wikidata_raw(
        tmp_path,
        target_rows=3,
        client=client,
        seeds=[SeedCategory('human', 'Q5', 2), SeedCategory('city', 'Q515', 1)],
        discovery_page_size=2,
        entity_batch_size=2,
        overfetch_factor=1.0,
        max_discovery_factor=3.0,
    )
    assert result.accepted_rows == 3
    assert ('Q5', 2, 2) in client.discovery_calls
