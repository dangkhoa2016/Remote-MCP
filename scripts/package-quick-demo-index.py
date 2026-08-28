#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.quick_demo_artifact import REQUIRED_INDEX_FILES, sha256_file, validate_quick_demo_dir

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--index-dir',type=Path,required=True); ap.add_argument('--output-dir',type=Path,required=True); ap.add_argument('--source-commit',default=None)
    a=ap.parse_args(); src=a.index_dir.resolve(); out=a.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
    meta=json.loads((src/'index-metadata.json').read_text())
    if int(meta.get('row_count',0))!=100000 or int(meta.get('dimensions',0))!=4096: raise SystemExit('Quick Demo publication requires the canonical 100000x4096 index')
    for n in REQUIRED_INDEX_FILES: shutil.copy2(src/n,out/n)
    commit=a.source_commit or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest={'schema_version':1,'artifact_type':'qwen3-embedding-8b-prebuilt-search-index','model':'Qwen/Qwen3-Embedding-8B','model_fingerprint':meta['model_fingerprint'],'dataset':'wikidata-en-vi-semantic-search-100k','dataset_sha256':meta['dataset_sha256'],'row_count':int(meta['row_count']),'dimensions':int(meta['dimensions']),'source_commit':commit,'created_utc':datetime.now(timezone.utc).isoformat()}
    (out/'quick-demo-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    (out/'SHA256SUMS').write_text(''.join(f'{sha256_file(out/n)}  {n}\n' for n in REQUIRED_INDEX_FILES))
    validate_quick_demo_dir(out,expected_model_fingerprint=meta['model_fingerprint'])
    print('QUICK_DEMO_DATASET_VALIDATION=PASS')
if __name__=='__main__': main()
