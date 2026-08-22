import pytest


def test_only_health_is_unprotected():
    from app.security import protected_path
    assert protected_path('/health') is False
    for path in ('/ready', '/metrics', '/info', '/v1/embeddings', '/v1/search'):
        assert protected_path(path) is True


def test_bearer_validation_rejects_missing_malformed_and_wrong_key():
    from app.security import AuthError, authorize_bearer
    for header in (None, 'Basic abc', 'Bearer wrong'):
        with pytest.raises(AuthError):
            authorize_bearer(path='/v1/embeddings', authorization=header, api_key='secret')
    authorize_bearer(path='/v1/embeddings', authorization='Bearer secret', api_key='secret')


def test_health_never_requires_key():
    from app.security import authorize_bearer
    authorize_bearer(path='/health', authorization=None, api_key='secret')


def test_external_mode_requires_api_key_in_application_config(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv('EXPOSE_MODE', 'cloudflare-quick')
    monkeypatch.delenv('API_KEY', raising=False)
    with pytest.raises(ValueError, match='API_KEY'):
        Settings.from_env()


def test_invalid_expose_mode_is_rejected(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv('EXPOSE_MODE', 'public-anything')
    monkeypatch.setenv('API_KEY', 'secret')
    with pytest.raises(ValueError, match='EXPOSE_MODE'):
        Settings.from_env()
