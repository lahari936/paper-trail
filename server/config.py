import os
from urllib.parse import quote


def _database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    if host := os.environ.get("DB_HOST"):  # ECS: host from env, credentials injected from Secrets Manager
        user, password = os.environ["DB_USER"], quote(os.environ["DB_PASSWORD"], safe="")
        return f"postgresql+psycopg://{user}:{password}@{host}:{os.environ.get('DB_PORT', '5432')}/papertrail"
    return "postgresql+psycopg://papertrail:papertrail@127.0.0.1:54329/papertrail"


DATABASE_URL: str = _database_url()
DEMO_USER_ID: str = os.environ.get("DEMO_USER_ID", "demo")
AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_EXTRACT_MODEL_ID: str = os.environ.get("BEDROCK_EXTRACT_MODEL_ID", "")
BEDROCK_QA_MODEL_ID: str = os.environ.get("BEDROCK_QA_MODEL_ID", "")
BEDROCK_EMBED_MODEL_ID: str = os.environ.get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")

# Auth is on when COGNITO_USER_POOL_ID is set; local dev runs without it as DEMO_USER_ID.
COGNITO_USER_POOL_ID: str = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_IDS: list[str] = [c for c in os.environ.get("COGNITO_CLIENT_ID", "").split(",") if c]
MCP_CANONICAL_URI: str = os.environ.get("MCP_CANONICAL_URI", "")
SES_FROM: str = os.environ.get("SES_FROM", "")
COGNITO_DOMAIN: str = os.environ.get("COGNITO_DOMAIN", "")  # hosted UI base, e.g. https://papertrail-123.auth.us-east-1.amazoncognito.com
