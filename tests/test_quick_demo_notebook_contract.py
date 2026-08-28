import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; P=ROOT/'notebooks/kaggle-t4x2-quick-demo.ipynb'
def nb(): return json.loads(P.read_text())
def test_every_code_cell_has_bilingual_markdown_before_it():
    n=nb()
    for i,c in enumerate(n['cells']):
        if c['cell_type']!='code': continue
        assert i>0 and n['cells'][i-1]['cell_type']=='markdown'; t=''.join(n['cells'][i-1]['source']); assert '**English:**' in t and '**Tiếng Việt:**' in t
def test_three_examples_per_feature_and_dataset_slug():
    t='\n'.join(''.join(c.get('source',[])) for c in nb()['cells'])
    for marker in ('EN_EXAMPLES=[','VI_EXAMPLES=[','PAIRS=[','AB=[','SIM=[','MRL_TEXTS=['): assert marker in t
    assert 'for n in (1,8,16):' in t
    assert 'dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index' in t
def test_prebuilt_only_and_runtime_contract():
    t='\n'.join(''.join(c.get('source',[])) for c in nb()['cells'])
    assert 'resolve_kaggle_quick_demo_dir' in t and 'build_search_index' not in t and 'scripts/build-index.py' not in t
    assert 'elapsed<=600' in t and 'elapsed<=900' in t and 'QUICK_DEMO=PASS' in t
def test_code_compiles():
    for i,c in enumerate(nb()['cells']):
        if c['cell_type']=='code': compile(''.join(c['source']),f'cell-{i}','exec')
