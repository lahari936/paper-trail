# PaperTrail: Implementation Spec (for Claude Code)

> Put this file in the repo root as `docs/IMPLEMENTATION.md` and point Claude Code at it: *"Read docs/IMPLEMENTATION.md and implement Phase 1. Stop at the acceptance criteria and show me the results."* Work one phase at a time.

## 0. Context for the coding agent

- **What it is:** An MCP server that lets Alexa+ answer questions about a household's documents (warranties, insurance, leases, subscriptions, bills), plus an ingestion pipeline and a small web companion.
- **Hackathon:** Amazon Developer Hackathon, Alexa+ track, plus the AWS Builder and Open Source mini challenges. Deadline: **Oct 24, 2026, 00:30 IST**. A demo video under 3 minutes is required.
- **Hard requirements:**
  - The MCP server follows spec **2025-11-25** over **Streamable HTTP** at a **public HTTPS URL**. Legacy SSE transport is not allowed.
  - The repo must actually call the tech in code. The MCP server, the Alexa add-on config, and the Bedrock calls must all be real.
  - Public repo with an MIT LICENSE.
- **Rules for the agent:**
  - Python 3.12 and type hints everywhere.
  - Keep secrets in env vars only; never commit `.env`.
  - Write tests for the extraction validators and the MCP tool handlers.
  - Prefer boring, working code over clever code.
  - After each phase, update `docs/FRICTION_LOG.md` with any tool or SDK friction encountered.

## 1. Architecture

```
[Web companion] --upload--> [S3 raw/] --event--> [Ingest worker]
                                                   ├─ Textract (OCR)
                                                   ├─ Bedrock: classify + extract (JSON schema)
                                                   ├─ Validator (grounding check)
                                                   └─ Titan embeddings -> Postgres+pgvector
[Alexa+] --Streamable HTTP (OAuth)--> [MCP server on ECS Fargate/ALB] --> Postgres, Bedrock
[EventBridge Scheduler] --daily--> [Reminder job] --> SES email
```

| Component | Choice | Why |
|---|---|---|
| MCP server | `mcp` Python SDK (FastMCP) in stateless Streamable HTTP mode, mounted in FastAPI | Official SDK, spec-compliant |
| Hosting | ECS Fargate + ALB + ACM certificate | Long-lived HTTP; no Lambda streaming quirks |
| Auth | Amazon Cognito user pool (OAuth 2.1 authorization code + PKCE) | Alexa+ account linking; set the resource parameter to the server's canonical URI |
| OCR | Amazon Textract `AnalyzeDocument` (FORMS, TABLES) | Handles photos of receipts and cards |
| LLM | Amazon Bedrock Converse API: Claude Sonnet-class for extraction, Haiku-class for Q&A | Cost and quality balance |
| Embeddings | Amazon Titan Text Embeddings V2 | Native to Bedrock |
| DB | RDS PostgreSQL + pgvector (local: docker `pgvector/pgvector`) | Structured fields and vectors in one place |
| Reminders | EventBridge Scheduler → Lambda → SES | Simple |
| IaC | AWS CDK (Python) | One `cdk deploy` |
| Web | Vite + React, minimal | Upload, library, citations |

> Check the current Bedrock model IDs in your region (`aws bedrock list-foundation-models`) and put them in config. Don't hard-code them.

## 2. Repo layout

```
papertrail/
  LICENSE (MIT)
  README.md                 # setup, run, demo, architecture image
  docs/IMPLEMENTATION.md    # this file
  docs/FRICTION_LOG.md
  docs/PRODUCT_FEEDBACK.md
  server/
    app.py                  # FastAPI + mounted MCP Streamable HTTP endpoint at /mcp
    mcp_tools.py            # tool definitions
    auth.py                 # Cognito JWT validation
    db.py                   # SQLAlchemy models + pgvector
    retrieval.py
    config.py
  ingest/
    pipeline.py             # S3 event -> textract -> extract -> validate -> store
    schemas.py              # Pydantic schemas per document type
    prompts.py
    validate.py             # grounding checks
  reminders/handler.py
  web/                      # Vite React app
  alexa-addon/              # output of `alexa-ai new mcp` (committed)
  infra/                    # CDK app
  seed/                     # 8-12 sample docs (synthetic, no real PII) + labels.json
  tests/
  docker-compose.yml        # postgres+pgvector, server, localstack optional
```

## 3. Data model

```sql
documents(id uuid pk, user_id text, doc_type text, title text, s3_key text,
          vendor text, item_name text, item_category text,
          start_date date, end_date date, renewal_date date, notice_days int,
          amount numeric, currency text, auto_renews bool,
          fields jsonb, status text, created_at timestamptz)
chunks(id uuid pk, document_id uuid fk, page int, text text, embedding vector(1024))
reminders(id uuid pk, user_id text, document_id uuid, due_at timestamptz, kind text, sent bool)
```

`doc_type` is one of: `warranty | insurance | lease | subscription | bill | other`.

Use one Pydantic schema per type. Example for warranty: `product, brand, model, serial, purchase_date, coverage_start, coverage_end, covered_parts[], exclusions[], claim_contact`.

## 4. MCP tools (the core of the demo)

Design rule: every tool returns `{ "answer": <one or two spoken sentences>, "evidence": [{document_id, title, page, quote}], "followups": [...] }`. Alexa+ speaks `answer`, and the screen can show the evidence.

| Tool | Input | Behavior |
|---|---|---|
| `check_coverage` | `item: str`, `issue?: str` | Resolves the item to a document (fuzzy match on item_name, category, brand), compares today to coverage_end, and checks exclusions against the issue |
| `list_upcoming_deadlines` | `days: int = 30` | Renewals, expiries and notice windows (`renewal_date - notice_days`) |
| `ask_documents` | `question: str`, `doc_type?: str` | Hybrid retrieval (structured filter + vector top-k=6) → Haiku answer with citations; returns "I couldn't find that" if nothing grounded |
| `get_document` | `document_id` or `query` | Summary of one document |
| `set_reminder` | `document_id`, `days_before` | Inserts a reminder row |
| `list_documents` | `doc_type?` | Library overview |

Tool descriptions matter. Write them for an LLM router, e.g. "Use when the user asks whether a product or appliance is still under warranty or covered…"

Ambiguity: if more than one document matches, return `answer: "I found two: your Samsung fridge and your LG washing machine. Which one?"` and do not guess.

## 5. Extraction pipeline

1. Upload → `s3://bucket/raw/{user}/{uuid}.{ext}`.
2. Run Textract (async for multi-page PDFs) and save the per-page text.
3. Classify with Bedrock: return `doc_type` and a confidence score.
4. Extract with Bedrock using the type schema. Use the Converse API's JSON or tool-use output for structured results, temperature 0, and require a `source_quote` and `page` for every date and amount.
5. **Validate (`validate.py`):**
   - Each `source_quote` must fuzzy-match (≥90) text on the cited page.
   - Dates must be parseable from the quote.
   - `end_date` must be on or after `start_date`.
   - On failure, set the field to null and `status=needs_review`.
6. Chunk the text (~800 tokens with overlap, keeping page numbers), embed it, and store it.
7. Create default reminders: 30 and 7 days before `end_date` or `renewal_date`, and 7 days before the notice deadline.

## 6. Phases and acceptance criteria

**Phase 1: Local MCP server with seed data (Days 1–2)**
- docker-compose with Postgres + pgvector, plus a seed script that inserts 8–12 synthetic documents with hand-written fields.
- Implement all six tools against the DB, with no Bedrock yet (template answers).
- ✅ The MCP Inspector (`npx @modelcontextprotocol/inspector`) connects to `http://localhost:8000/mcp` over Streamable HTTP, lists the tools, and calling `check_coverage("washing machine")` returns the right answer.

**Phase 2: Real extraction (Days 3–4)**
- Textract + Bedrock extract + validator, plus a CLI: `python -m ingest.pipeline seed/warranty_lg.pdf`.
- `tests/test_extraction.py` compares against `seed/labels.json` and prints per-field accuracy.
- ✅ At least 85% of date and amount fields are correct on the seed set, and 0 ungrounded dates are stored.

**Phase 3: Retrieval Q&A (Day 5)**
- Embeddings, hybrid retrieval, and `ask_documents` with citations.
- ✅ 10 scripted questions in `tests/qa_eval.py`; each answer cites the correct document, and refuses correctly when the answer isn't in the documents.

**Phase 4: Deploy + auth (Days 6–7)**
- CDK stack: VPC, RDS, ECS Fargate service, ALB with HTTPS (ACM certificate on your domain), S3, Cognito, Textract and Bedrock IAM, and the Scheduler + SES reminder Lambda.
- Validate Cognito JWTs on `/mcp`, and expose OAuth protected resource metadata per the MCP 2025-11-25 authorization spec.
- ✅ MCP Inspector connects to `https://<domain>/mcp` with an OAuth token.

**Phase 5: Alexa+ add-on (Day 7)**
- Install the Alexa AI CLI, run `alexa-ai configure`, then `alexa-ai new mcp --name "PaperTrail" --locale en-US --mcp-server-url "https://<domain>/mcp"`, then `alexa-ai deploy`.
- Commit the generated add-on project in `alexa-addon/`.
- ✅ The three demo questions work by voice on an Alexa+ device or the developer console's test tool. **Fallback if Alexa+ isn't reachable from your account or region:** build the "simulated Alexa+ experience" path, a web page with speech input that uses a Bedrock agent as the MCP client against the same server. Decide by the end of Day 7 at the latest.

**Phase 6: Web companion + polish (Day 8)**
- Upload, library, document detail with highlighted source quotes, and a deadlines view.
- README with an architecture PNG, setup steps, and a demo GIF.

**Phase 7: Submission (Days 9–10)**
- Record the video (script in `devpost-submissions.md`).
- Complete `PRODUCT_FEEDBACK.md`, `FRICTION_LOG.md`, and the Open Source contribution (a small PR to the MCP Python SDK, the Alexa samples, or `pgvector` docs; or open-source a reusable `document-grounding-validator` package).

## 7. Environment variables

```
AWS_REGION=us-east-1
BEDROCK_EXTRACT_MODEL_ID=
BEDROCK_QA_MODEL_ID=
BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
DATABASE_URL=postgresql+psycopg://...
S3_BUCKET=
COGNITO_USER_POOL_ID=
COGNITO_CLIENT_ID=
MCP_CANONICAL_URI=https://<domain>/mcp
SES_FROM=
DEMO_USER_ID=demo
```

## 8. Seed documents (create synthetic ones; no real PII)

1. LG washing machine warranty card (photo-like PNG)
2. Samsung refrigerator extended warranty (2-page PDF)
3. Car insurance policy schedule (renewal in ~20 days, so it shows on the radar)
4. Home rental agreement (2-month notice clause)
5. Streaming subscription terms (auto-renews)
6. Electricity bill
7. Laptop accidental-damage plan (excludes liquid damage, for the "issue" demo)
8. Health insurance card (only basic fields)

## 9. Demo script (must work flawlessly)

1. "Alexa, ask PaperTrail if my washing machine is still under warranty." → "Yes, your LG washing machine warranty runs until March 2027. The motor is covered for 10 years."
2. "My laptop got water on it, is that covered?" → "Probably not. Your accidental-damage plan excludes liquid damage on page 2."
3. "What's coming up in the next month?" → car insurance renewal and the subscription auto-renew.
4. "Remind me a week before the insurance renews." → a reminder is created.

## 10. Cost guardrails
- Set a Fargate task at 0.5 vCPU / 1 GB, use RDS `db.t4g.micro`, and create an AWS Budget alert.
- Run Textract and extraction only on upload; Q&A uses the Haiku-class model.
- Tear down after judging.
