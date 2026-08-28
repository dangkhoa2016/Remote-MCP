import hashlib, json
from pathlib import Path
import numpy as np, pytest
from app.quick_demo_artifact import QuickDemoArtifactError, resolve_kaggle_quick_demo_dir, validate_quick_demo_dir

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def make(path,fp='fp'):
    path.mkdir(parents=True); np.save(path/'vectors.npy',np.zeros((1,1),dtype=np.float32)); (path/'rows.json').write_text('[]')
    meta={'model_fingerprint':fp,'dataset_sha256':'data','row_count':100000,'dimensions':4096}; (path/'index-metadata.json').write_text(json.dumps(meta))
    man={'schema_version':1,'artifact_type':'qwen3-embedding-8b-prebuilt-search-index',**meta}; (path/'quick-demo-manifest.json').write_text(json.dumps(man))
    names=('vectors.npy','rows.json','index-metadata.json'); (path/'SHA256SUMS').write_text(''.join(f'{sha(path/n)}  {n}\n' for n in names)); return path

def test_valid(tmp_path): assert validate_quick_demo_dir(make(tmp_path/'a'),expected_model_fingerprint='fp')['row_count']==100000
def test_wrong_model(tmp_path):
    with pytest.raises(QuickDemoArtifactError,match='model fingerprint mismatch'): validate_quick_demo_dir(make(tmp_path/'a'),expected_model_fingerprint='x')
def test_tamper(tmp_path):
    p=make(tmp_path/'a'); (p/'rows.json').write_text('[1]')
    with pytest.raises(QuickDemoArtifactError,match='checksum mismatch'): validate_quick_demo_dir(p)
def test_resolve(tmp_path):
    expected=make(tmp_path/'a')
    assert resolve_kaggle_quick_demo_dir(tmp_path,expected_model_fingerprint='fp')==expected.resolve()
