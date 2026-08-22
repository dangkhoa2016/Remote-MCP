import importlib

import pytest
import torch


def _m():
    return importlib.import_module('app.inference.model')


def test_last_token_pool_handles_left_padding():
    m = _m()
    hidden = torch.tensor([[[1., 0.], [2., 0.], [3., 0.]]])
    mask = torch.tensor([[0, 1, 1]])
    pooled = m.last_token_pool(hidden, mask)
    assert torch.equal(pooled, torch.tensor([[3., 0.]]))


def test_last_token_pool_handles_right_padding():
    m = _m()
    hidden = torch.tensor([[[1., 0.], [2., 0.], [99., 0.]]])
    mask = torch.tensor([[1, 1, 0]])
    pooled = m.last_token_pool(hidden, mask)
    assert torch.equal(pooled, torch.tensor([[2., 0.]]))


def test_truncate_then_renormalize_has_unit_norm():
    m = _m()
    x = torch.arange(1, 65, dtype=torch.float32).unsqueeze(0)
    y = m.normalize_and_truncate(x, 32, max_dimensions=64)
    assert y.shape == (1, 32)
    assert torch.allclose(torch.linalg.vector_norm(y, dim=1), torch.ones(1), atol=1e-6)


@pytest.mark.parametrize('dimensions', [0, 31, 4097])
def test_dimension_bounds_are_enforced(dimensions):
    m = _m()
    with pytest.raises(ValueError, match='dimensions'):
        m.normalize_and_truncate(torch.ones((1, 4096)), dimensions, max_dimensions=4096)


def test_query_instruction_is_applied_only_in_query_mode():
    m = _m()
    prefix = 'Instruct: retrieve\nQuery: '
    assert m.prepare_texts(['hello'], is_query=True, query_instruction=prefix) == [prefix + 'hello']
    assert m.prepare_texts(['hello'], is_query=False, query_instruction=prefix) == ['hello']

def test_encode_caps_tokenizer_length_from_runtime_settings():
    from types import SimpleNamespace
    from app.config import Settings

    m = _m()

    class FakeTokenizer:
        def __init__(self):
            self.last_kwargs = None

        def __call__(self, texts, **kwargs):
            self.last_kwargs = kwargs
            return {
                'input_ids': torch.tensor([[1, 2]], dtype=torch.long),
                'attention_mask': torch.tensor([[1, 1]], dtype=torch.long),
            }

    class FakeModel:
        config = SimpleNamespace(max_position_embeddings=32768, hidden_size=32)

        def __call__(self, **batch):
            return SimpleNamespace(last_hidden_state=torch.ones((1, 2, 32), dtype=torch.float32))

    embedder = m.LocalQwenEmbedder.__new__(m.LocalQwenEmbedder)
    embedder.settings = Settings(max_sequence_tokens=1024)
    embedder.device = 'cpu'
    embedder.tokenizer = FakeTokenizer()
    embedder.model = FakeModel()
    embedder.max_dimensions = 32

    output = embedder.encode(['hello'], dimensions=32, is_query=False)

    assert len(output.embeddings[0]) == 32
    assert embedder.tokenizer.last_kwargs['max_length'] == 1024


def test_encode_output_defaults_to_no_cuda_memory_on_cpu():
    m = _m()
    output = m.EncodeOutput(embeddings=[[1.0, 0.0]], token_count=2)
    assert output.cuda_memory is None
