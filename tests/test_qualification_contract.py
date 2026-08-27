from pathlib import Path


def test_qualification_script_has_ordered_stage_markers_and_opt_in_external_security():
    text = Path('kaggle/qualification.sh').read_text(encoding='utf-8')
    required = (
        'STAGE_0_STATIC_PREFLIGHT',
        'STAGE_1_5K_ACCEPTANCE',
        'STAGE_2_100K_ACCEPTANCE',
        'STAGE_3_MODEL_CAPABILITIES',
        'STAGE_4_HARDWARE_ENVELOPE',
        'STAGE_5_EXTERNAL_SECURITY',
    )
    positions = [text.index(marker) for marker in required]
    assert positions == sorted(positions)
    assert 'SKIPPED_OPT_IN' in text
    assert '--enable-cloudflare' in text


def test_evidence_manifest_v2_requires_non_null_run_kind(tmp_path):
    import pytest
    from app.qualification.evidence import write_manifest_v2
    with pytest.raises(ValueError, match='run_kind'):
        write_manifest_v2(tmp_path, run_id='x', run_kind='', identity={})


def test_acceptance_uses_sanitized_runtime_config_and_secret_scan():
    text = Path('kaggle/acceptance.sh').read_text(encoding='utf-8')
    assert 'sanitize_runtime_config' in text
    assert 'scan_secret_bytes' in text
    assert 'index-metadata.json' in text
    assert 'pip-list.json' in text
    assert 'run_kind' in text


def test_manifest_v2_checksums_nested_artifacts(tmp_path):
    import json
    from app.qualification.evidence import write_manifest_v2
    nested = tmp_path / 'hardware-cases'
    nested.mkdir()
    (nested / 'case.json').write_text('{"ok": true}\n', encoding='utf-8')
    manifest = write_manifest_v2(tmp_path, run_id='r', run_kind='qualification', identity={})
    assert 'hardware-cases/case.json' in manifest['files']
    persisted = json.loads((tmp_path / 'run-manifest.json').read_text(encoding='utf-8'))
    assert persisted['files']['hardware-cases/case.json']['bytes'] > 0


def test_qualification_retains_hardware_telemetry_and_full_external_auth_lifecycle():
    text = Path('kaggle/qualification.sh').read_text(encoding='utf-8')
    for marker in (
        'gpu-telemetry.csv',
        'process-telemetry.log',
        'metrics_after_case',
        'wrong_auth_http_status',
        'secret_scan_status',
        'stale_url_reachable',
        'cloudflared-version.txt',
    ):
        assert marker in text
