# PaperTrail

Ask Alexa+ about your household paperwork: warranties, insurance, leases, subscriptions and bills.
PaperTrail is an MCP server (spec 2025-11-25, Streamable HTTP) that Alexa+ calls as an add-on.

> Status: Phase 1. Local MCP server with seed data and template answers. See [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

## Run locally

Requires Docker, [uv](https://docs.astral.sh/uv/) and Node (for the MCP Inspector).

```bash
docker compose up -d --wait          # Postgres + pgvector on localhost:54329
uv sync
uv run python -m seed.load           # 8 synthetic documents for user "demo"
uv run uvicorn server.app:app --port 8000
```

Then connect the MCP Inspector over Streamable HTTP to `http://localhost:8000/mcp`:

```bash
npx @modelcontextprotocol/inspector
```

Tests (need the DB running):

```bash
uv run pytest
```

Some seed dates are relative to the day you seed (for example, the car insurance renews in 20 days), so re-seed before a demo.

## Tools

| Tool | What it answers |
|---|---|
| `check_coverage(item, issue?)` | "Is my washing machine still under warranty?" "My laptop got water on it, is that covered?" |
| `list_upcoming_deadlines(days=30)` | "What's coming up in the next month?" |
| `ask_documents(question, doc_type?)` | "What's my car insurance deductible?" |
| `get_document(document_id? / query?)` | "Tell me about my lease." |
| `set_reminder(document_id? / query?, days_before=7)` | "Remind me a week before the insurance renews." |
| `list_documents(doc_type?)` | "What warranties do I have?" |

Each tool returns `{answer, evidence: [{document_id, title, page, quote}], followups}`.

## License

MIT
