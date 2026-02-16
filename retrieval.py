"""
Vector search on Supabase table chunks.
Fetches the most similar chunks by embedding similarity.
Expects a DB function search_chunks(query_embedding, match_count) – see README.
"""

from supabase import create_client, Client

import config

# Type for a single chunk row returned by the search.
ChunkRow = dict[str, str | None]


def _get_client() -> Client:
    """Build Supabase client from config. Fails if URL or key missing."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in the environment"
        )
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def search_chunks(query_embedding: list[float], top_k: int | None = None) -> list[ChunkRow]:
    """
    Return the top_k most similar chunks for the given query embedding.
    Uses the RPC search_chunks; returns list of dicts with
    chunk_text, article_number, title, source_url (mapped from DB columns text, article_ref).
    """
    k = top_k if top_k is not None else config.TOP_K
    client = _get_client()
    # PostgREST does not expose pgvector operators; similarity search is done via RPC.
    # Expected DB function: search_chunks(query_embedding vector, match_count int)
    # returning (text, article_ref, title, source_url).
    response = client.rpc(
        "search_chunks",
        {"query_embedding": query_embedding, "match_count": k},
    ).execute()
    rows = response.data or []
    # Map DB columns (text, article_ref) to app keys (chunk_text, article_number).
    out: list[ChunkRow] = []
    for r in rows:
        if isinstance(r, dict):
            out.append({
                "chunk_text": r.get("text"),
                "article_number": r.get("article_ref"),
                "title": r.get("title"),
                "source_url": r.get("source_url"),
            })
    return out
