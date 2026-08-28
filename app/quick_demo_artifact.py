from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import json

class QuickDemoArtifactError(RuntimeError):
    pass

REQUIRED_INDEX_FILES = ('vectors.npy','rows.json','index-metadata.json')

def sha256_file(path: Path) -> str:
    h=sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def _parse_sha256s(path: Path) -> dict[str,str]:
    out={}
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        if not raw.strip(): continue
        parts=raw.split(None,1)
        if len(parts)!=2: raise QuickDemoArtifactError(f'invalid SHA256SUMS row: {raw!r}')
        checksum,name=parts; name=name.lstrip('*')
        if Path(name).name != name: raise QuickDemoArtifactError('SHA256SUMS must contain portable basenames only')
        out[name]=checksum
    return out

def validate_quick_demo_dir(path: Path, *, expected_model_fingerprint: str|None=None) -> dict:
    path=Path(path).resolve(); mp=path/'quick-demo-manifest.json'; sp=path/'SHA256SUMS'
    if not mp.is_file() or not sp.is_file(): raise QuickDemoArtifactError(f'missing quick-demo manifest/checksum file: {path}')
    try: manifest=json.loads(mp.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as e: raise QuickDemoArtifactError(f'invalid quick-demo manifest: {path}') from e
    if manifest.get('schema_version')!=1 or manifest.get('artifact_type')!='qwen3-embedding-8b-prebuilt-search-index': raise QuickDemoArtifactError('unsupported quick-demo artifact manifest')
    if int(manifest.get('row_count',0))!=100000 or int(manifest.get('dimensions',0))!=4096: raise QuickDemoArtifactError('quick-demo artifact must be the canonical 100000x4096 index')
    fp=str(manifest.get('model_fingerprint',''))
    if expected_model_fingerprint and fp!=expected_model_fingerprint: raise QuickDemoArtifactError('quick-demo model fingerprint mismatch')
    sums=_parse_sha256s(sp)
    for name in REQUIRED_INDEX_FILES:
        p=path/name
        if not p.is_file(): raise QuickDemoArtifactError(f'missing quick-demo artifact file: {name}')
        if not sums.get(name) or sha256_file(p)!=sums[name]: raise QuickDemoArtifactError(f'quick-demo artifact checksum mismatch: {name}')
    meta=json.loads((path/'index-metadata.json').read_text(encoding='utf-8'))
    for key in ('model_fingerprint','dataset_sha256','row_count','dimensions'):
        if str(meta.get(key))!=str(manifest.get(key)): raise QuickDemoArtifactError(f'quick-demo manifest/index metadata mismatch: {key}')
    return manifest

def resolve_kaggle_quick_demo_dir(root: Path, explicit: str|None=None, *, expected_model_fingerprint: str|None=None) -> Path:
    root=Path(root).resolve()
    if explicit:
        p=Path(explicit).expanduser().resolve()
        try: p.relative_to(root)
        except ValueError as e: raise QuickDemoArtifactError(f'QUICK_DEMO_INDEX_DIR must resolve under {root}; got {p}') from e
        validate_quick_demo_dir(p, expected_model_fingerprint=expected_model_fingerprint); return p
    candidates=[]
    if root.is_dir():
        for m in root.rglob('quick-demo-manifest.json'):
            if len(m.relative_to(root).parts)>8: continue
            try: validate_quick_demo_dir(m.parent, expected_model_fingerprint=expected_model_fingerprint)
            except QuickDemoArtifactError: continue
            candidates.append(m.parent.resolve())
    candidates=sorted(set(candidates))
    if not candidates: raise QuickDemoArtifactError('No verified Qwen3-Embedding-8B quick-demo prebuilt index found under Kaggle input')
    if len(candidates)>1: raise QuickDemoArtifactError('Multiple quick-demo index inputs found; set QUICK_DEMO_INDEX_DIR explicitly')
    return candidates[0]
