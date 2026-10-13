# Friction log

## Phase 1

- **MCP Python SDK 2.x renamed FastMCP.** `pip install mcp` now gives 2.x, where `mcp.server.fastmcp` is gone and the class is `mcp.server.mcpserver.MCPServer`. Most tutorials, including the spec this project started from, still show `FastMCP`. The SDK does raise a helpful `ModuleNotFoundError` pointing at the migration guide.
- **Transport options moved.** In 2.x, `stateless_http` / `json_response` are arguments to `streamable_http_app()` rather than the constructor.
- **Mounting in FastAPI needs the lifespan wired by hand.** Starlette doesn't run a mounted sub-app's lifespan, so `mcp.session_manager.run()` has to be the parent FastAPI app's lifespan. Otherwise every request fails because the session manager's task group never started.
- **Protocol versions.** SDK 2.3 negotiates 2025-11-25 through the `initialize` handshake and also serves the newer 2026-07-28 per-request envelope. 2025-11-25 clients work without extra configuration.
- **Docker Desktop on Windows** sometimes doesn't start on the first launch. Relaunching it worked.
- **Host port clashes.** Other local compose projects already held 5433 and 55432, so PaperTrail's DB uses 54329. `docker ps` shows who owns a port.
- **`localhost` was slow on Windows.** psycopg tried `::1` first and waited before falling back to IPv4. Every DB call took seconds until `DATABASE_URL` pointed at `127.0.0.1`.
