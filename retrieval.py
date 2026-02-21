"""
Hybrid retrieval: structured by metadata.code when query contains a normative code,
otherwise vector (semantic) search. Keeps return format identical for downstream.
"""

import json
import re
from typing import Optional

from supabase import create_client, Client

import config

# Type for a single chunk row: metadata is optional dict from jsonb.
ChunkRow = dict[str, str | None | float | dict | list]

# Normative code pattern: digit, letter, three digits (e.g. 2B002).
NORMATIVE_CODE_PATTERN = re.compile(r"\b[0-9][A-Z][0-9]{3}\b")


def _get_client() -> Client:
    """Build Supabase client from config. Fails if URL or key missing."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in the environment"
        )
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def detect_normative_code(query: str) -> Optional[str]:
    """
    Detect a normative code in the user query (e.g. 2B002).
    Returns uppercase match if found, else None. Used for hybrid structured retrieval.
    """
    if not query or not query.strip():
        return None
    m = NORMATIVE_CODE_PATTERN.search(query.strip())
    return m.group(0).upper() if m else None


def _parse_metadata(raw: object) -> dict:
    """
    Parse metadata from RPC response into a Python dict.
    Supabase may return jsonb as dict or as JSON string; handle both for robustness.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _structured_retrieval_by_code(code: str, top_k: int) -> list[ChunkRow]:
    """
    Fetch chunks where metadata->>'code' equals code. No RPC, no embedding.
    Return format matches vector search; similarity set to 1.0 for consistency.
    """
    client = _get_client()
    response = (
        client.table(config.TABLE_NAME)
        .select("text, metadata, title, source_url")
        .eq("metadata->>code", code)
        .limit(top_k)
        .execute()
    )
    rows = response.data or []
    out: list[ChunkRow] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        metadata = _parse_metadata(r.get("metadata"))
        row = {
            "chunk_text": r.get("text"),
            "metadata": metadata,
            "title": r.get("title"),
            "source_url": r.get("source_url"),
            "similarity": 1.0,  # structured match, no vector score
        }
        out.append(row)
        _log_chunk_metadata(row)
    return out


def _vector_search(query_embedding: list[float], top_k: int) -> list[ChunkRow]:
    """Run RPC search_chunks and return chunks in standard format."""
    client = _get_client()
    response = client.rpc(
        "search_chunks",
        {"query_embedding": query_embedding, "match_count": top_k},
    ).execute()
    rows = response.data or []
    out: list[ChunkRow] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        metadata = _parse_metadata(r.get("metadata"))
        row = {
            "chunk_text": r.get("text"),
            "metadata": metadata,
            "title": r.get("title"),
            "source_url": r.get("source_url"),
            "similarity": r.get("similarity"),
        }
        out.append(row)
        _log_chunk_metadata(row)
    return out


def search_chunks(
    query: str,
    query_embedding: list[float],
    top_k: int | None = None,
) -> list[ChunkRow]:
    """
    Hybrid retrieval: if query contains a normative code (e.g. 2B002), try structured
    retrieval by metadata.code first; else or on no match, use vector search.
    Return format is always: chunk_text, metadata, title, source_url, similarity.
    """
    k = top_k if top_k is not None else config.TOP_K
    code = detect_normative_code(query)

    if code is not None:
        print(f"[hybrid] detected normative code: {code}")
        structured = _structured_retrieval_by_code(code, k)
        if structured:
            print(f"[structured retrieval] code={code} -> {len(structured)} result(s)")
            return structured
        print("[structured retrieval] no match, fallback to vector search")

    # No code detected or no structured results: normal vector search
    return _vector_search(query_embedding, k)


def _log_chunk_metadata(chunk: ChunkRow) -> None:
    """Log metadata fields for debugging; only logs keys that exist."""
    meta = chunk.get("metadata") or {}
    if not isinstance(meta, dict):
        return
    parts = []
    if "type" in meta:
        parts.append(f"type={meta.get('type')}")
    if "celex" in meta:
        parts.append(f"celex={meta.get('celex')}")
    if "article" in meta:
        parts.append(f"article={meta.get('article')}")
    if "code" in meta:
        parts.append(f"code={meta.get('code')}")
    if parts:
        print(f"  [retrieval] {', '.join(parts)}")
