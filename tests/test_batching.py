import importlib


def _b():
    return importlib.import_module('app.scheduler.batching')


def test_split_micro_batches_respects_item_limit():
    b = _b()
    items = [b.BatchItem(index=i, text='abc', estimated_tokens=1) for i in range(5)]
    batches = b.split_micro_batches(items, max_items=2, max_estimated_tokens=100)
    assert [len(x) for x in batches] == [2, 2, 1]


def test_split_micro_batches_respects_token_limit_without_reordering():
    b = _b()
    items = [
        b.BatchItem(index=0, text='a', estimated_tokens=3),
        b.BatchItem(index=1, text='b', estimated_tokens=4),
        b.BatchItem(index=2, text='c', estimated_tokens=2),
    ]
    batches = b.split_micro_batches(items, max_items=10, max_estimated_tokens=5)
    assert [[i.index for i in batch] for batch in batches] == [[0], [1], [2]]


def test_padding_aware_cost_splits_one_long_and_many_short_items():
    b = _b()
    items = [b.BatchItem(0, 'long', 420)] + [b.BatchItem(i, 'short', 8) for i in range(1, 16)]
    batches = b.split_micro_batches(items, max_items=16, max_estimated_tokens=512)
    assert [[item.index for item in batch] for batch in batches] == [
        [0],
        list(range(1, 16)),
    ]
    assert all(b.projected_padding_cost(batch) <= 512 for batch in batches)


def test_single_oversize_item_makes_forward_progress():
    b = _b()
    item = b.BatchItem(7, 'oversize', 900)
    batches = b.split_micro_batches([item], max_items=16, max_estimated_tokens=512)
    assert batches == [[item]]


def test_padding_aware_split_preserves_order_on_heterogeneous_lengths():
    b = _b()
    costs = [120, 20, 20, 100, 20, 20]
    items = [b.BatchItem(i, str(i), cost) for i, cost in enumerate(costs)]
    batches = b.split_micro_batches(items, max_items=4, max_estimated_tokens=320)
    assert [item.index for batch in batches for item in batch] == list(range(6))
    assert all(len(batch) == 1 or b.projected_padding_cost(batch) <= 320 for batch in batches)



def test_all_long_items_are_split_before_padding_cost_exceeds_t4_budget():
    b = _b()
    items = [b.BatchItem(i, 'x', 240) for i in range(8)]
    batches = b.split_micro_batches(items, max_items=16, max_estimated_tokens=512)
    assert [len(batch) for batch in batches] == [2, 2, 2, 2]
    assert all(b.projected_padding_cost(batch) <= 512 for batch in batches)
