"""Central configuration. Everything comes from .env / environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root regardless of cwd
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _env(name: str, default: str = "") -> str:
    """Read an env var, stripping stray whitespace/newlines that sneak in
    when values are pasted into cloud dashboards (Render, Lambda...)."""
    return os.environ.get(name, default).strip()


DATABASE_URL = _env("DATABASE_URL")

# AWS credentials may also carry pasted whitespace — sanitize in place so
# boto3 (which reads os.environ directly) sees clean values too.
for _k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    if os.environ.get(_k):
        os.environ[_k] = os.environ[_k].strip()

AWS_REGION = _env("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = _env("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-6")
EMBED_MODEL_ID = _env("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBEDDINGS_PROVIDER = _env("EMBEDDINGS_PROVIDER", "bedrock")
EMBED_DIMS = 1024

S3_BUCKET = _env("S3_BUCKET")
# Bucket region — only needed if the bucket is NOT in AWS_REGION
S3_REGION = _env("S3_REGION") or AWS_REGION

PSP_LATENCY_MS = int(_env("PSP_LATENCY_MS", "300") or "300")

# Crash injection point for the crash-proof tests (see engine.maybe_crash)
CRASH_AT = _env("CRASH_AT")
