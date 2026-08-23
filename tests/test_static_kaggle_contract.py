from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def _runtime_text() -> str:
    paths = list((ROOT / 'app').rglob('*.py')) + list((ROOT / 'dataset').rglob('*.py'))
    for rel in ('kaggle/run-demo.sh', 'kaggle/acceptance.sh', 'scripts/build-index.py'):
        p = ROOT / rel
        if p.exists():
            paths.append(p)
    return '\n'.join(p.read_text(encoding='utf-8') for p in paths)


def test_runtime_has_no_huggingface_download_path():
    text = _runtime_text()
    assert 'snapshot_download' not in text
    assert 'huggingface.co' not in text
    assert 'kagglehub.model_download' not in text
    assert 'from_pretrained("Qwen/' not in text
    assert "from_pretrained('Qwen/" not in text


def test_local_model_loader_requires_local_files_only():
    text = (ROOT / 'app/inference/model.py').read_text(encoding='utf-8')
    assert text.count('local_files_only=True') >= 2
    assert 'str(model_dir)' in text


def test_offline_environment_contract_is_present_in_launcher():
    launcher = (ROOT / 'kaggle/run-demo.sh').read_text(encoding='utf-8')
    for assignment in (
        'HF_HUB_OFFLINE=1',
        'TRANSFORMERS_OFFLINE=1',
        'HF_DATASETS_OFFLINE=1',
        'TOKENIZERS_PARALLELISM=false',
    ):
        assert assignment in launcher
    assert '/kaggle/input' in launcher


def test_notebook_contains_all_acceptance_stages():
    notebook = json.loads((ROOT / 'kaggle/demo.ipynb').read_text(encoding='utf-8'))
    source = '\n'.join(''.join(cell.get('source', [])) for cell in notebook['cells'])
    for phrase in (
        'GPU inventory',
        'Kaggle Model input',
        'Unicode quality gate',
        'two GPU workers',
        'semantic search',
        '1 GPU vs 2 GPU benchmark',
        'final acceptance',
    ):
        assert phrase in source

def test_notebook_bootstraps_project_root_before_importing_app():
    notebook = json.loads((ROOT / 'kaggle/demo.ipynb').read_text(encoding='utf-8'))
    source = '\n'.join(''.join(cell.get('source', [])) for cell in notebook['cells'])
    assert "Path('/kaggle/working/qwen3-embedding-8b-t4x2')" in source
    assert 'os.chdir(PROJECT_ROOT)' in source
    assert 'sys.path.insert(0, str(PROJECT_ROOT))' in source


def test_launcher_encodes_t4_oom_hardening_defaults():
    launcher = (ROOT / 'kaggle/run-demo.sh').read_text(encoding='utf-8')
    assert 'PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"' in launcher
    assert 'MAX_BATCH_ESTIMATED_TOKENS="${MAX_BATCH_ESTIMATED_TOKENS:-512}"' in launcher


def test_readme_is_clone_to_run_and_never_advertises_a_maintainer_endpoint():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    for phrase in (
        'clone/run in your own Kaggle T4×2 session',
        'EXPOSE_MODE=off',
        'Cloudflare Quick Tunnel is optional',
        'not a permanently hosted public inference endpoint',
    ):
        assert phrase in readme
    assert 'https://trycloudflare.com' not in readme
    import re
    assert re.search(r'Bearer [A-Za-z0-9_-]{20,}', readme) is None


def test_notebook_uses_v013_staged_acceptance_and_opt_in_external_qualification():
    notebook = json.loads((ROOT / 'kaggle/demo.ipynb').read_text(encoding='utf-8'))
    source = '\n'.join(''.join(cell.get('source', [])) for cell in notebook['cells'])
    for phrase in (
        'Stage 0 — preflight/static identity',
        'Stage 1 — 5K acceptance',
        'Stage 2 — forced-fresh 100K acceptance',
        'Stage 3 — semantic/model capability qualification',
        'Stage 4 — hardware/long-context envelope',
        'Stage 5 — optional authenticated Cloudflare external demo',
        'Stage 6 — evidence archive verification',
    ):
        assert phrase in source
    assert 'ENABLE_CLOUDFLARE = 0' in source
    assert 'kaggle/qualification.sh' in source
