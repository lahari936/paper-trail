# Friction log

## Phase 1

- **MCP Python SDK 2.x renamed FastMCP.** `pip install mcp` now gives 2.x, where `mcp.server.fastmcp` is gone and the class is `mcp.server.mcpserver.MCPServer`. Most tutorials, including the spec this project started from, still show `FastMCP`. The SDK does raise a helpful `ModuleNotFoundError` pointing at the migration guide.
- **Transport options moved.** In 2.x, `stateless_http` / `json_response` are arguments to `streamable_http_app()` rather than the constructor.
- **Mounting in FastAPI needs the lifespan wired by hand.** Starlette doesn't run a mounted sub-app's lifespan, so `mcp.session_manager.run()` has to be the parent FastAPI app's lifespan. Otherwise every request fails because the session manager's task group never started.
- **Protocol versions.** SDK 2.3 negotiates 2025-11-25 through the `initialize` handshake and also serves the newer 2026-07-28 per-request envelope. 2025-11-25 clients work without extra configuration.
- **Docker Desktop on Windows** sometimes doesn't start on the first launch. Relaunching it worked.
- **Host port clashes.** Other local compose projects already held 5433 and 55432, so PaperTrail's DB uses 54329. `docker ps` shows who owns a port.
- **`localhost` was slow on Windows.** psycopg tried `::1` first and waited before falling back to IPv4. Every DB call took seconds until `DATABASE_URL` pointed at `127.0.0.1`.

## Phase 2

- **Textract sync vs async.** Sync `AnalyzeDocument` accepts one page and won't take a multi-page PDF. Async `StartDocumentAnalysis` needs the file in S3 plus job polling. The CLI renders each PDF page to PNG with PyMuPDF and makes one sync call per page, so local runs need no S3.
- **Structured output on Bedrock.** The Converse API has no JSON mode, so extraction forces a single tool call (`toolChoice: {tool: ...}`) whose `inputSchema` is the Pydantic model's JSON schema. The `$defs` refs that Pydantic emits are accepted.
- **Model IDs.** Newer Claude models on Bedrock have to be called through a cross-region inference profile (`us.anthropic...`), not the bare model ID. They also have to be enabled per account under Model access first.
