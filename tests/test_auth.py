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
