"""Central configuration. Everything comes from .env / environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root regardless of cwd
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-6")
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBEDDINGS_PROVIDER = os.environ.get("EMBEDDINGS_PROVIDER", "bedrock")
EMBED_DIMS = 1024

S3_BUCKET = os.environ.get("S3_BUCKET", "")
# Bucket region — only needed if the bucket is NOT in AWS_REGION
S3_REGION = os.environ.get("S3_REGION") or AWS_REGION

PSP_LATENCY_MS = int(os.environ.get("PSP_LATENCY_MS", "300"))

# Crash injection point for the crash-proof tests (see engine.maybe_crash)
CRASH_AT = os.environ.get("CRASH_AT", "")
