from pathlib import Path


def test_extracts_only_https_trycloudflare_hostname():
    from app.qualification.cloudflare import extract_quick_tunnel_url
    text = 'INF Your quick Tunnel has been created! Visit it at https://abc-def.trycloudflare.com'
    assert extract_quick_tunnel_url(text) == 'https://abc-def.trycloudflare.com'
    assert extract_quick_tunnel_url('http://abc.trycloudflare.com') is None
    assert extract_quick_tunnel_url('https://example.com') is None


def test_parser_returns_first_strict_tunnel_url_only():
    from app.qualification.cloudflare import extract_quick_tunnel_url
    text = 'noise https://bad.example.com then https://first-one.trycloudflare.com and https://second.trycloudflare.com'
    assert extract_quick_tunnel_url(text) == 'https://first-one.trycloudflare.com'


def test_shell_lifecycle_contract_is_fail_closed_and_secret_safe():
    script = Path('scripts/expose-cloudflare.sh').read_text(encoding='utf-8')
    for marker in ('start)', 'status)', 'stop)', 'cloudflared tunnel --url', 'cloudflared.pid', 'tunnel-url.txt', 'status.json'):
        assert marker in script
    assert 'set -x' not in script
    assert 'echo "$API_KEY"' not in script
    assert 'EXPOSE_MODE' in script
    assert '/health' in script
    assert '/ready' in script
    assert "Authorization: Bearer" in script
    assert '-H "Authorization: Bearer $key"' not in script
    assert '--config "$AUTH_CURL_CONFIG"' in script


def test_fake_cloudflared_log_is_parseable_without_network(tmp_path):
    from app.qualification.cloudflare import extract_quick_tunnel_url
    fake = tmp_path / 'cloudflared'
    fake.write_text('#!/usr/bin/env bash\necho "INF https://fake-test.trycloudflare.com"\n', encoding='utf-8')
    fake.chmod(0o755)
    output = __import__('subprocess').check_output([str(fake)], text=True)
    assert extract_quick_tunnel_url(output) == 'https://fake-test.trycloudflare.com'
