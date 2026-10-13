import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://papertrail:papertrail@127.0.0.1:54329/papertrail"
)
DEMO_USER_ID: str = os.environ.get("DEMO_USER_ID", "demo")
