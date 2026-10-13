"""Cognito access-token validation for /mcp (MCP 2025-11-25 authorization: this server is a resource server)."""

import asyncio
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from server.config import AWS_REGION, COGNITO_CLIENT_IDS, COGNITO_USER_POOL_ID, MCP_CANONICAL_URI


def issuer(pool_id: str = COGNITO_USER_POOL_ID, region: str = AWS_REGION) -> str:
    return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}"


class CognitoTokenVerifier:
    """Checks signature (pool JWKS), issuer, expiry, token_use=access, app client, and audience if present."""

    def __init__(self, issuer_url: str, client_ids: list[str], resource: str, jwks: Any = None) -> None:
        self.issuer_url, self.client_ids, self.resource = issuer_url, client_ids, resource
        self.jwks = jwks or jwt.PyJWKClient(f"{issuer_url}/.well-known/jwks.json", cache_keys=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256"], issuer=self.issuer_url,
                options={"verify_aud": False, "require": ["exp", "iss", "sub", "token_use", "client_id"]},
            )
        except (jwt.PyJWTError, jwt.PyJWKClientError):
            return None
        if claims["token_use"] != "access" or claims["client_id"] not in self.client_ids:
            return None
        # Cognito access tokens carry `aud` only when the client sent an RFC 8707 resource indicator.
        aud = claims.get("aud")
        if aud is not None and self.resource not in (aud if isinstance(aud, list) else [aud]):
            return None
        return AccessToken(
            token=token, client_id=claims["client_id"], scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"], resource=self.resource, subject=claims["sub"], claims=claims,
        )


def auth_config() -> tuple[AuthSettings | None, CognitoTokenVerifier | None]:
    if not COGNITO_USER_POOL_ID:
        return None, None
    if not MCP_CANONICAL_URI or not COGNITO_CLIENT_IDS:
        raise RuntimeError("COGNITO_USER_POOL_ID needs MCP_CANONICAL_URI and COGNITO_CLIENT_ID too")
    settings = AuthSettings(
        issuer_url=issuer(), resource_server_url=MCP_CANONICAL_URI,
        validate_token_resource=False,  # the verifier checks `aud` itself
    )
    return settings, CognitoTokenVerifier(issuer(), COGNITO_CLIENT_IDS, MCP_CANONICAL_URI)
