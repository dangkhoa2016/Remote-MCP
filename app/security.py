from __future__ import annotations

import hmac


PROTECTED_PATHS = frozenset({
    '/ready',
    '/metrics',
    '/info',
    '/v1/embeddings',
    '/v1/search',
})


class AuthError(RuntimeError):
    pass


def protected_path(path: str) -> bool:
    return path in PROTECTED_PATHS


def authorize_bearer(*, path: str, authorization: str | None, api_key: str | None) -> None:
    if api_key is None or not protected_path(path):
        return
    prefix = 'Bearer '
    if authorization is None or not authorization.startswith(prefix):
        raise AuthError('unauthorized')
    supplied = authorization[len(prefix):]
    if not supplied or not hmac.compare_digest(supplied, api_key):
        raise AuthError('unauthorized')
