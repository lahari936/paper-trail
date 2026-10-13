import asyncio
import time
from types import SimpleNamespace
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from server.auth import CognitoTokenVerifier, issuer

ISS = issuer("us-east-1_TEST", "us-east-1")
RESOURCE = "https://papertrail.example.com/mcp"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=KEY.public_key()))
VERIFIER = CognitoTokenVerifier(ISS, ["client-1"], RESOURCE, jwks=JWKS)


def token(key: Any = KEY, **overrides: Any) -> str:
    claims = {"iss": ISS, "sub": "user-123", "token_use": "access", "client_id": "client-1",
              "scope": "openid email", "exp": int(time.time()) + 600} | overrides
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


def verify(t: str):  # type: ignore[no-untyped-def]
    return asyncio.run(VERIFIER.verify_token(t))


def test_valid_access_token() -> None:
    at = verify(token())
    assert at and at.subject == "user-123" and at.client_id == "client-1" and at.scopes == ["openid", "email"]
    assert verify(token(aud=RESOURCE)) is not None
    assert verify(token(aud=[RESOURCE, "other"])) is not None


def test_rejects_bad_tokens() -> None:
    assert verify(token(key=OTHER_KEY)) is None  # bad signature
    assert verify(token(exp=int(time.time()) - 10)) is None  # expired
    assert verify(token(iss="https://evil.example.com")) is None
    assert verify(token(token_use="id")) is None  # ID token, not access token
    assert verify(token(client_id="someone-else")) is None
    assert verify(token(aud="https://other.example.com/mcp")) is None  # issued for another resource
    assert verify(token(sub=None)) is None
    assert verify("not-a-jwt") is None


def test_authorization_server_metadata_for_alexa() -> None:
    from server.auth import authorization_server_metadata, origin

    assert origin("https://papertrail.example.com/mcp") == "https://papertrail.example.com"
    md = authorization_server_metadata("https://papertrail.example.com", "https://pt.auth.us-east-1.amazoncognito.com")
    assert md["issuer"] == "https://papertrail.example.com"
    assert md["authorization_endpoint"] == "https://pt.auth.us-east-1.amazoncognito.com/oauth2/authorize"
    assert "S256" in md["code_challenge_methods_supported"]


def test_401_has_no_www_authenticate() -> None:
    from server.app import without_www_authenticate

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"www-authenticate", b"Bearer"), (b"content-type", b"application/json")]})

    sent: list[dict] = []

    async def send(message):  # type: ignore[no-untyped-def]
        sent.append(message)

    asyncio.run(without_www_authenticate(inner)({"type": "http"}, None, send))
    assert sent[0]["headers"] == [(b"content-type", b"application/json")]
