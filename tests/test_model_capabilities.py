import numpy as np


def test_mrl_projection_slices_then_renormalizes():
    from app.search.index import IndexMetadata, VectorIndex
    first = np.zeros(64, dtype=np.float32); first[:2] = [3.0, 4.0]
    second = np.zeros(64, dtype=np.float32); second[:3] = [1.0, 2.0, 2.0]
    index = VectorIndex.build(
        np.stack([first, second]),
        [{'qid': 'Q1'}, {'qid': 'Q2'}],
        IndexMetadata('fp', 64, 2, 'data'),
    )
    projected = index.project(32)
    assert projected.vectors.shape == (2, 32)
    assert np.allclose(np.linalg.norm(projected.vectors, axis=1), [1.0, 1.0])
    assert np.allclose(projected.vectors[0][:2], [0.6, 0.8])
    assert projected.metadata.dimensions == 32


def test_rank_vectors_is_deterministic_and_cosine_normalized():
    from app.qualification.model_capabilities import rank_vectors
    corpus = np.array([[1., 0.], [0., 1.], [1., 1.]], dtype=np.float32)
    ranked = rank_vectors(np.array([1., 0.], dtype=np.float32), corpus, ['a', 'b', 'c'], 3)
    assert [item[0] for item in ranked] == ['a', 'c', 'b']
    assert ranked[0][1] == 1.0


def test_exact_mrl_dimension_contract():
    from app.qualification.model_capabilities import MRL_DIMENSIONS
    assert MRL_DIMENSIONS == (32, 128, 256, 512, 1024, 2048, 4096)


def test_rank_metrics_compare_instruction_modes():
    from app.qualification.model_capabilities import summarize_rank_outcomes
    report = summarize_rank_outcomes(
        expected={'q1': {'Q1'}, 'q2': {'Q2'}},
        rankings={'q1': ['Q1'], 'q2': ['Q9', 'Q2']},
    )
    assert report['hit_at_1'] == 0.5
    assert report['hit_at_5'] == 1.0
    assert report['mrr'] == 0.75


def test_cross_lingual_topk_overlap():
    from app.qualification.model_capabilities import topk_overlap
    assert topk_overlap(['Q1', 'Q2', 'Q3'], ['Q3', 'Q2', 'Q9'], 3) == 2 / 3


def test_code_fixture_hit_at_k():
    from app.qualification.model_capabilities import code_hit_at_k
    assert code_hit_at_k({'q': ['python-json-parse', 'other']}, {'q': {'python-json-parse'}}, 1) == 1.0
