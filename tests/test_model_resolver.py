from pathlib import Path
import importlib
import json

import pytest


def _resolver():
    return importlib.import_module('app.model_resolver')


def _make_model_dir(path: Path, *, sharded: bool = False) -> Path:
    path.mkdir(parents=True)
    (path / 'config.json').write_text(json.dumps({'model_type': 'qwen3'}))
    (path / 'tokenizer_config.json').write_text(json.dumps({'padding_side': 'left'}))
    (path / 'tokenizer.json').write_text('{}')
    if sharded:
        (path / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'x': 'model-00001-of-00002.safetensors'}}))
        (path / 'model-00001-of-00002.safetensors').write_bytes(b'a')
        (path / 'model-00002-of-00002.safetensors').write_bytes(b'b')
    else:
        (path / 'model.safetensors').write_bytes(b'weights')
    return path


def test_explicit_path_must_be_under_kaggle_input(tmp_path: Path):
    m = _resolver()
    model = _make_model_dir(tmp_path / 'model')
    with pytest.raises(m.ModelResolutionError, match='under'):
        m.resolve_kaggle_model_dir(tmp_path / 'kaggle-input', str(model))


def test_valid_explicit_model_path_is_accepted(tmp_path: Path):
    m = _resolver()
    root = tmp_path / 'kaggle' / 'input'
    model = _make_model_dir(root / 'qwen-qwen3-embedding-8b' / 'transformers' / 'default' / '1')
    assert m.resolve_kaggle_model_dir(root, str(model)) == model.resolve()


def test_missing_weights_are_rejected(tmp_path: Path):
    m = _resolver()
    root = tmp_path / 'kaggle' / 'input'
    model = root / 'qwen-qwen3-embedding-8b'
    model.mkdir(parents=True)
    (model / 'config.json').write_text('{}')
    (model / 'tokenizer_config.json').write_text('{}')
    with pytest.raises(m.ModelResolutionError, match='weights'):
        m.resolve_kaggle_model_dir(root, str(model))


def test_scan_prefers_qwen_named_candidate(tmp_path: Path):
    m = _resolver()
    root = tmp_path / 'kaggle' / 'input'
    _make_model_dir(root / 'other-model' / 'transformers' / 'default' / '1')
    preferred = _make_model_dir(root / 'qwen-qwen3-embedding-8b' / 'transformers' / 'default' / '1')
    assert m.resolve_kaggle_model_dir(root, None) == preferred.resolve()


def test_scan_rejects_ambiguous_preferred_candidates(tmp_path: Path):
    m = _resolver()
    root = tmp_path / 'kaggle' / 'input'
    _make_model_dir(root / 'qwen-qwen3-embedding-8b' / 'transformers' / 'a' / '1')
    _make_model_dir(root / 'qwen-qwen3-embedding-8b' / 'transformers' / 'b' / '1')
    with pytest.raises(m.ModelResolutionError, match='Multiple'):
        m.resolve_kaggle_model_dir(root, None)


def test_model_fingerprint_is_stable_and_changes_with_file_size(tmp_path: Path):
    m = _resolver()
    root = tmp_path / 'kaggle' / 'input'
    model = _make_model_dir(root / 'qwen-qwen3-embedding-8b')
    first = m.model_fingerprint(model)
    second = m.model_fingerprint(model)
    assert first == second
    (model / 'model.safetensors').write_bytes(b'weights-more')
    assert m.model_fingerprint(model) != first


def test_offline_environment_policy_sets_required_flags(monkeypatch):
    c = importlib.import_module('app.config')
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE', 'TOKENIZERS_PARALLELISM'):
        monkeypatch.delenv(key, raising=False)
    c.enforce_offline_environment()
    assert c.os.environ['HF_HUB_OFFLINE'] == '1'
    assert c.os.environ['TRANSFORMERS_OFFLINE'] == '1'
    assert c.os.environ['HF_DATASETS_OFFLINE'] == '1'
    assert c.os.environ['TOKENIZERS_PARALLELISM'] == 'false'
