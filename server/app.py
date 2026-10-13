"""FastAPI app with the PaperTrail MCP server mounted at /mcp (stateless Streamable HTTP).

Run: uv run uvicorn server.app:app --port 8000
"""

from fastapi import FastAPI

from server.mcp_tools import mcp

mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True)

# A mounted sub-app's lifespan doesn't run, so start the MCP session manager here.
app = FastAPI(title="PaperTrail", lifespan=lambda _: mcp.session_manager.run())


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", mcp_app)
