# PaperTrail

Ask Alexa+ about your household paperwork: warranties, insurance, leases, subscriptions and bills.
PaperTrail is an MCP server (spec 2025-11-25, Streamable HTTP) that Alexa+ calls as an add-on.

> Status: Phase 4. Deployable to AWS with CDK: ECS Fargate behind HTTPS, RDS with pgvector, and Cognito OAuth on `/mcp`. See [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

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

## Ingest a document (Phase 2)

Needs AWS credentials with Textract and Bedrock access, and a Bedrock model you've enabled in your region:

```bash
aws bedrock list-inference-profiles --region us-east-1 --query "inferenceProfileSummaries[].inferenceProfileId"
```

Copy `.env.example` to `.env` and set `BEDROCK_EXTRACT_MODEL_ID` (a Sonnet-class Claude inference profile). Then:

```bash
uv run --env-file .env python -m ingest.pipeline seed/warranty_lg.pdf --dry-run
```

Without `--dry-run`, the document is stored. It replaces an earlier ingest of the same file, and that includes the hand-written seed row.

Pipeline: Textract `AnalyzeDocument` per page, then Bedrock Converse classifies the type and extracts fields with forced tool use at temperature 0. `ingest/validate.py` then checks that every date, amount and notice period has a `source_quote` that fuzzy-matches (90 or above) the cited page and actually states the value. Anything that fails is set to null and the document is marked `needs_review`.

Extraction eval (calls AWS, about $1 per run):

```bash
uv run --env-file .env pytest tests/test_extraction.py -s
```

`seed/labels.json` and the seed PDFs come from `seed/load.py`. Regenerate them together with `uv run python -m seed.make_docs`.

## Q&A with citations (Phase 3)

`ask_documents` runs hybrid retrieval. If the question clearly names one document ("my car insurance"), the search is limited to that document. It then takes the top 6 chunks by Titan V2 vector search and merges in the chunks behind the best keyword-matching sentences. A Haiku-class model (`BEDROCK_QA_MODEL_ID`) answers from those sources only. Every citation's quote has to match its source text, and with no verified citation the tool answers "I couldn't find that in your documents."

When `BEDROCK_QA_MODEL_ID` is unset, `ask_documents` quotes the best keyword sentence instead, so local development works offline.

```bash
uv run --env-file .env python -m server.retrieval    # embed chunks that have no embedding yet (e.g. after seed.load)
uv run --env-file .env python -m tests.qa_eval       # 10 scripted questions, including 2 that must be refused
```

## Deploy to AWS (Phase 4)

[infra/app.py](infra/app.py) is one CDK stack. It contains:

- a VPC with no NAT gateway
- RDS Postgres 17 (`db.t4g.micro`, pgvector)
- the ECS Fargate MCP server (0.5 vCPU / 1 GB) behind an HTTPS ALB, with an ACM certificate on your domain
- an S3 bucket
- a Cognito user pool with an app client (authorization code + PKCE)
- IAM permissions for Textract, Bedrock and SES
- a daily EventBridge Scheduler job that runs `reminders.handler` on Fargate and emails due reminders through SES
- a $30/month AWS Budget alert

Prerequisites: AWS CLI credentials, Docker, Node, and a Route 53 hosted zone for your domain.

```bash
cd infra
npx aws-cdk@2 bootstrap
npx aws-cdk@2 deploy -c domain_name=papertrail.example.com -c hosted_zone_id=Z123 -c hosted_zone_name=example.com -c alert_email=you@example.com -c ses_from=you@example.com -c extract_model_id=us.anthropic.claude-sonnet-... -c qa_model_id=us.anthropic.claude-haiku-...
```

SES sends a verification email to `ses_from`. In the SES sandbox, recipients must be verified as well.

Create the demo user and seed their documents. The stack outputs give the pool, cluster, task definition, subnets and security group.

```bash
aws cognito-idp admin-create-user --user-pool-id <UserPoolId> --username you@example.com --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
aws cognito-idp admin-get-user --user-pool-id <UserPoolId> --username you@example.com --query "UserAttributes[?Name=='sub'].Value" --output text
aws ecs run-task --cluster <ClusterName> --task-definition <TaskDefinition> --launch-type FARGATE --network-configuration "awsvpcConfiguration={subnets=[<PublicSubnets>],securityGroups=[<TaskSecurityGroup>],assignPublicIp=ENABLED}" --overrides '{"containerOverrides":[{"name":"web","command":["python","-m","seed.load","<sub>"]}]}'
```

To check auth, open the MCP Inspector on `https://<domain>/mcp`. Choose OAuth, enter the `ClientId` output as the client ID, and use scopes `openid email profile`. The server serves RFC 9728 metadata at `/.well-known/oauth-protected-resource/mcp`, which points the Inspector at Cognito.

Tear down after judging: `npx aws-cdk@2 destroy`.

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
