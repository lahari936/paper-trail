import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://papertrail:papertrail@127.0.0.1:54329/papertrail"
)
DEMO_USER_ID: str = os.environ.get("DEMO_USER_ID", "demo")
AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_EXTRACT_MODEL_ID: str = os.environ.get("BEDROCK_EXTRACT_MODEL_ID", "")
