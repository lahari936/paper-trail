"""FastAPI app with the PaperTrail MCP server mounted at /mcp (stateless Streamable HTTP).

Run: uv run uvicorn server.app:app --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings

from server.config import MCP_CANONICAL_URI
from server.db import init_db
from server.mcp_tools import mcp

# Behind the ALB the Host header is the public domain, so allow it explicitly (DNS-rebinding protection).
# Locally (no canonical URI) the SDK defaults to allowing only localhost.
security = None
if MCP_CANONICAL_URI:
    host = urlparse(MCP_CANONICAL_URI).netloc
    security = TransportSecuritySettings(allowed_hosts=[host], allowed_origins=[f"https://{host}"])

# Also serves /.well-known/oauth-protected-resource/mcp (RFC 9728) when auth is configured.
mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    # A mounted sub-app's lifespan doesn't run, so start the MCP session manager here.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="PaperTrail", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", mcp_app)
