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

## Phase 3

- **Titan V2 embeddings** take `dimensions` (256/512/1024) and `normalize` in the request body. With `normalize: true`, pgvector cosine distance ranks the same as dot product.
- **Grounding the Q&A model.** Asking the model for `found` plus verbatim citation quotes, then fuzzy-checking each quote against its source chunk, gives a cheap hallucination guard. Any answer without a verified citation turns into a refusal.

## Phase 4

- **Cognito as an MCP authorization server.** Cognito serves OIDC discovery (`/.well-known/openid-configuration`) but not RFC 8414 `oauth-authorization-server` metadata, and it has no Dynamic Client Registration. MCP 2025-11-25 clients fall back to OIDC discovery, and the client ID has to be pre-registered and entered by hand in the Inspector.
- **No `aud` in Cognito access tokens** unless the client sends an RFC 8707 `resource` indicator. The verifier checks `client_id` and `token_use=access`, and checks `aud` only when it's present.
- **DNS-rebinding protection in MCP SDK 2.x** allows only `localhost` Host headers by default. Behind the ALB the public domain has to go in `TransportSecuritySettings.allowed_hosts`, or every request fails.
- **`ScheduledFargateTask` can't assign a public IP.** Without a NAT gateway, a task in a public subnet then can't pull its image. EventBridge Scheduler's `EcsRunFargateTask` target supports `assign_public_ip`, so the daily reminder job uses that. It runs on Fargate with the server image instead of a separately packaged Lambda.
- **The CDK asset for the Docker build** honours `.dockerignore`. Without that file, the whole `.venv` would be uploaded as the build context.
