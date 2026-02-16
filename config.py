"""
Configuration for the RAG pipeline.
Loads environment variables and exposes settings for embeddings, retrieval, and LLM.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root so the app works when run from any directory.
load_dotenv(Path(__file__).resolve().parent / ".env")

# OpenAI
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
EMBEDDING_MODEL: str = "text-embedding-3-small"
LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()

# Supabase
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
TABLE_NAME: str = "chunks"

# Retrieval: number of chunks to fetch (cursorrules: 5–15).
TOP_K: int = min(20, max(5, int(os.getenv("TOP_K", "15"))))

# Optional: max total context length in characters to avoid token overflow.
# Can be tuned later; for now we rely on TOP_K to keep context small.
MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "30000"))
