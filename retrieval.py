"""
CustomsAI – Retrieval layer (v3)

Fornisce le primitive di accesso ai dati.
Il routing è responsabilità di main.py.

Regole:
- Nessun pattern di codice hardcoded (tutto nel registry)
- lookup_collateral() è generico: funziona per qualsiasi entry del registry
- vector_search() interroga solo la tabella chunks via RPC
"""

import json
from enum import Enum

from supabase import create_client, Client

import config

ChunkRow = dict[str, object]


# ============================================================
# Intent detection (keyword-based, nessuna logica su codici)
# ============================================================

class Intent(str, Enum):
    CODE_SPECIFIC  = "code_specific"
    CLASSIFICATION = "classification"
    PROCEDURAL     = "procedural"
    GENERIC        = "generic"


_PROCEDURAL_KEYWORDS = [
    "esportare", "obblighi", "cosa devo fare", "procedura", "autorizzazione",
]

_CLASSIFICATION_KEYWORDS = [
    "che codice", "voce doganale", "classificazione",
]


def detect_intent(query: str) -> Intent:
    """
    Rileva l'intent dalla query in modo deterministico (solo keyword matching).
    Non rileva codici: quello è compito di detect_code_from_registry() in registry.py.
    """
    q = (query or "").lower()

    if any(k in q for k in _PROCEDURAL_KEYWORDS):
        return Intent.PROCEDURAL

    if any(k in q for k in _CLASSIFICATION_KEYWORDS):
        return Intent.CLASSIFICATION

    return Intent.GENERIC


# ============================================================
# Supabase client
# ============================================================

def _get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _parse_metadata(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


# ============================================================
# Collateral DB lookup – registry-driven
# ============================================================

def lookup_collateral(entry: dict, code: str, top_k: int | None = None) -> list[ChunkRow]:
    """
    Lookup generico sul DB collaterale definito nell'entry del registry.

    Supporta match_mode:
      - "exact"  → .eq(code_field, code)
      - "prefix" → .like(code_field, "{code}%")

    Restituisce lista di ChunkRow con chunk_text, metadata, celex_consolidated, similarity.
    celex_consolidated è None per le entry con source.type == "static_celex".
    """
    k = top_k or config.TOP_K
    client = _get_client()

    table      = entry["table"]
    code_field = entry["code_field"]
    text_field = entry["text_field"]
    match_mode = entry["match_mode"]

    query = client.table(table).select("*")

    if match_mode == "exact":
        query = query.eq(code_field, code)
    elif match_mode == "prefix":
        query = query.like(code_field, f"{code}%")
    else:
        raise ValueError(f"match_mode non supportato: {match_mode!r}")

    response = query.limit(k).execute()
    rows = response.data or []

    print(f"[collateral] {entry['id']} | {match_mode} '{code}' → {len(rows)} risultati")

    display_code_field = entry.get("display_code_field")
    results = []

    for r in rows:
        text = r.get(text_field, "")

        if display_code_field:
            # Formatta chunk_text con codice + indentazione gerarchica.
            # goods_code ha formato "{10 cifre} {2 cifre}" (es. "8544000000 80"):
            # si estrae solo la parte numerica principale.
            raw_code = str(r.get(display_code_field, ""))
            numeric_code = raw_code.split()[0] if raw_code else ""

            # indent: None=voce principale, "-"=livello 1, "- -"=livello 2, ecc.
            indent_str = r.get("indent") or ""
            level = indent_str.count("-") if indent_str else 0
            indent_prefix = "  " * level

            chunk_text = f"{indent_prefix}{numeric_code}  {text}"
        else:
            chunk_text = text

        results.append({
            "chunk_text":         chunk_text,
            "metadata":           {"code": r.get(code_field), "source_id": entry["id"]},
            "celex_consolidated":  r.get("celex_consolidated"),
            "similarity":         1.0,
        })

    return results


# ============================================================
# Vector search su chunks (RPC search_chunks_multi_type)
# ============================================================

def vector_search(
    query_embedding: list[float],
    top_k: int | None = None,
    type_filters: list[str] | None = None,
) -> list[ChunkRow]:
    """
    Ricerca vettoriale su public.chunks tramite RPC search_chunks_multi_type.

    type_filters: lista di unit_type in UPPERCASE (es. ["ARTICLE"], ["ANNEX_CODE"]).
    Se None → ricerca globale su tutti i tipi.
    """
    k = top_k or config.TOP_K
    client = _get_client()

    rpc_params = {
        "query_embedding": query_embedding,
        "match_count":     k,
        "type_filters":    type_filters or None,
    }

    response = client.rpc("search_chunks_multi_type", rpc_params).execute()
    rows = response.data or []

    print(f"[vector] type_filters={type_filters} → {len(rows)} risultati")

    return [
        {
            "chunk_text":        r["text"],
            "metadata":          _parse_metadata(r["metadata"]),
            "celex_consolidated": r.get("celex_consolidated"),
            "similarity":        r.get("similarity"),
        }
        for r in rows
    ]
