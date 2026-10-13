"""Cognito access-token validation for /mcp (MCP 2025-11-25 authorization: this server is a resource server).

Alexa+ needs RFC 8414 metadata at `/.well-known/oauth-authorization-server` and doesn't speak OIDC discovery,
which is all Cognito serves. So this server publishes the authorization-server metadata itself (issuer = its own
origin) with Cognito's hosted-UI endpoints, and the protected resource metadata points at that origin.
"""

import asyncio
from typing import Any
from urllib.parse import urlparse

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from server.config import AWS_REGION, COGNITO_CLIENT_IDS, COGNITO_DOMAIN, COGNITO_USER_POOL_ID, MCP_CANONICAL_URI


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


def origin(url: str = MCP_CANONICAL_URI) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def authorization_server_metadata(issuer_url: str, cognito_domain: str) -> dict[str, Any]:
    """RFC 8414 metadata for the Cognito user pool, served from this server's origin."""
    return {
        "issuer": issuer_url,
        "authorization_endpoint": f"{cognito_domain}/oauth2/authorize",
        "token_endpoint": f"{cognito_domain}/oauth2/token",
        "revocation_endpoint": f"{cognito_domain}/oauth2/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
    }


def auth_config() -> tuple[AuthSettings | None, CognitoTokenVerifier | None]:
    if not COGNITO_USER_POOL_ID:
        return None, None
    if not (MCP_CANONICAL_URI and COGNITO_CLIENT_IDS and COGNITO_DOMAIN):
        raise RuntimeError("COGNITO_USER_POOL_ID needs MCP_CANONICAL_URI, COGNITO_CLIENT_ID and COGNITO_DOMAIN too")
    settings = AuthSettings(
        issuer_url=origin(),  # protected resource metadata -> this origin's authorization-server metadata
        resource_server_url=MCP_CANONICAL_URI,
        validate_token_resource=False,  # the verifier checks `aud` itself
    )
    return settings, CognitoTokenVerifier(issuer(), COGNITO_CLIENT_IDS, MCP_CANONICAL_URI)
