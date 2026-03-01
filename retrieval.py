"""
CustomsAI – Layer-aware hybrid retrieval
Deterministic SQL-level filtering (production locked)
"""

import json
import re
from enum import Enum

from supabase import create_client, Client
import config

ChunkRow = dict[str, object]

NORMATIVE_CODE_PATTERN = re.compile(r"\b[0-9][A-Za-z][0-9]{3}\b", re.IGNORECASE)


# ============================================================
# Intent detection
# ============================================================

class Intent(str, Enum):
    CODE_SPECIFIC = "code_specific"
    CLASSIFICATION = "classification"
    PROCEDURAL = "procedural"
    GENERIC = "generic"


def detect_intent(query: str) -> Intent:
    q = (query or "").lower()

    if NORMATIVE_CODE_PATTERN.search(q):
        return Intent.CODE_SPECIFIC

    if any(k in q for k in ["che codice", "voce doganale", "classificazione"]):
        return Intent.CLASSIFICATION

    if any(k in q for k in ["cosa devo fare", "obblighi", "procedura", "autorizzazione", "esportare"]):
        return Intent.PROCEDURAL

    return Intent.GENERIC


# ============================================================
# Supabase client
# ============================================================

def _get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _parse_metadata(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


# ============================================================
# Structured retrieval by normative code
# ============================================================

def _structured_retrieval_by_code(code: str, top_k: int):

    client = _get_client()

    response = (
        client.table(config.TABLE_NAME)
        .select("text, metadata, celex_consolidated")
        .eq("metadata->>code", code)
        .limit(top_k)
        .execute()
    )

    rows = response.data or []

    return [
        {
            "chunk_text": r["text"],
            "metadata": _parse_metadata(r["metadata"]),
            "celex_consolidated": r.get("celex_consolidated"),
            "similarity": 1.0,
        }
        for r in rows
    ]


# ============================================================
# SQL-level vector search
# ============================================================

def _vector_search_sql(query_embedding, top_k, type_filters=None):

    client = _get_client()

    rpc_params = {
        "query_embedding": query_embedding,
        "match_count": top_k,
        "type_filters": type_filters if type_filters else None
    }

    response = client.rpc(
        "search_chunks_multi_type",
        rpc_params
    ).execute()

    rows = response.data or []

    parsed = []

    for r in rows:
        parsed.append({
            "chunk_text": r["text"],
            "metadata": _parse_metadata(r["metadata"]),
            "celex_consolidated": r.get("celex_consolidated"),
            "similarity": r.get("similarity"),
        })

    return parsed


# ============================================================
# Public search entrypoint
# ============================================================

def search_chunks(query, query_embedding, top_k=None):

    k = top_k if top_k else config.TOP_K
    intent = detect_intent(query)

    print(f"\n[routing] intent={intent.value}\n")

    # CODE SPECIFIC
    if intent == Intent.CODE_SPECIFIC:
        match = NORMATIVE_CODE_PATTERN.search(query)
        if match:
            code = match.group(0).upper()

            print(f"[routing] structured retrieval by code={code}")

            results = _structured_retrieval_by_code(code, k)

            if results:
                return results, True

            print("[routing] no structured match → fallback to vector")

    # PROCEDURAL
    if intent == Intent.PROCEDURAL:

        print("[routing] first pass: article only")

        articles = _vector_search_sql(
            query_embedding,
            k,
            type_filters=["article"]
        )

        if articles:
            return articles, False

        print("[routing] no article results → fallback global")

    # CLASSIFICATION
    if intent == Intent.CLASSIFICATION:

        print("[routing] first pass: annex_code only")

        annex_codes = _vector_search_sql(
            query_embedding,
            k,
            type_filters=["annex_code"]
        )

        if annex_codes:
            return annex_codes, False

        print("[routing] no annex_code results → fallback global")

    # GLOBAL
    print("[routing] global search")

    results = _vector_search_sql(
        query_embedding,
        k,
        type_filters=None
    )

    return results, False