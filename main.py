"""
CustomsAI v3 – Pipeline registry-first

Flusso:
  detect_intent (keyword) + detect_code_from_registry (pattern)
    → CODE_SPECIFIC  : lookup collaterale → testo diretto, nessun LLM
    → PROCEDURAL+code: lookup collaterale + vector_search → LLM interpretativo
    → CLASSIFICATION : vector_search (ANNEX_CODE) → LLM interpretativo
    → GENERIC        : vector_search globale → LLM interpretativo

Le fonti normative sono sempre stampate da Python, mai dall'LLM.
"""

import sys
from typing import TypedDict

from openai import APIError, APIConnectionError

import config
import embeddings
import retrieval
import prompt as prompt_module
import llm
from query_normalizer import normalize_query
from registry import detect_code_from_registry


# ---------------------------------------------------------------------------
# QueryResult – struttura dati restituita da query()
# ---------------------------------------------------------------------------

class QueryResult(TypedDict):
    mode:    str          # "direct" | "llm" | "empty"
    intent:  str          # valore dell'Intent enum (es. "code_specific")
    codes:   list[str]    # codici rilevati dalla query (es. ["8544"])
    dbs:     list[str]    # ID delle entry con ≥1 risultato (es. ["nomenclature"])
    chunks:  list[dict]   # raw chunks (per display diretto o context LLM)
    answer:  str | None   # risposta LLM (solo mode="llm")
    sources: list[dict]   # [{"label": str|None, "celex": str, "url": str}]
    log:     list[str]    # messaggi di routing/debug in ordine


# ---------------------------------------------------------------------------
# Source helpers (deterministico)
# ---------------------------------------------------------------------------

def _eurlex_link(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{celex}"


def _build_sources(chunks: list[dict], active_entries: list[dict]) -> list[dict]:
    """
    Costruisce la lista di fonti normative in modo puro (nessun print).

    Due tipi di fonte (non esclusivi):
      - static_celex : CELEX fisso letto dall'entry del registry (es. nomenclature)
      - celex_field  : CELEX dinamico letto dal campo celex_consolidated dei chunk
    """
    sources: list[dict] = []

    # 1. Fonti statiche dal registry (es. nomenclature, dual_use_correlations)
    for entry in active_entries:
        src = entry.get("source", {})
        if src.get("type") == "static_celex":
            sources.append({
                "label": src.get("label"),
                "celex": src["celex"],
                "url":   src["url"],
            })

    # 2. CELEX dinamici dai chunk (celex_field)
    seen: set[str] = set()
    for c in chunks:
        celex = c.get("celex_consolidated")
        if celex and celex not in seen:
            seen.add(celex)
            sources.append({
                "label": None,
                "celex": celex,
                "url":   _eurlex_link(celex),
            })

    return sources


def _render_sources(sources: list[dict]) -> None:
    """Stampa la lista di fonti già costruita nel formato testuale standard."""
    if not sources:
        return

    lines: list[str] = []
    for src in sources:
        if src.get("label"):
            lines.append(src["label"])
        lines.append(f"CELEX: {src['celex']}")
        lines.append(src["url"])
        lines.append("")

    print("\n---")
    print("FONTI NORMATIVE (deterministiche)\n")
    print("\n".join(lines))
    print("---")


def _print_normative_sources(
    chunks: list[dict],
    registry_entries: list[dict],
) -> None:
    """
    Stampa le fonti normative in modo deterministico.

    Due tipi di fonte (non esclusivi):
      - static_celex : CELEX fisso letto dall'entry del registry (es. nomenclature)
      - celex_field  : CELEX dinamico letto dal campo celex_consolidated dei chunk
    """
    _render_sources(_build_sources(chunks, registry_entries))


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_direct_text(chunks: list[dict]) -> None:
    print("\n=== TESTO NORMATIVO ===\n")
    for r in chunks:
        print(r.get("chunk_text", ""))
        print("\n---")


# ---------------------------------------------------------------------------
# Query – pura computazione, nessun print
# ---------------------------------------------------------------------------

def query(question: str) -> QueryResult:
    """
    Esegue la pipeline di retrieval e restituisce un QueryResult strutturato.
    Nessun print: i messaggi di routing vanno in result["log"].

    Raises:
        ValueError: se la domanda è vuota.
        APIError, APIConnectionError: errori OpenAI (embedding o LLM).
    """
    q = (question or "").strip()
    if not q:
        raise ValueError("Domanda vuota.")

    log: list[str] = []

    # ── 1. Intent (keyword) + codice (registry pattern scan) ──────────────
    base_intent      = retrieval.detect_intent(q)
    registry_matches = detect_code_from_registry(q)   # list[tuple[dict, str]]

    # ── 2. Intent finale ───────────────────────────────────────────────────
    if registry_matches:
        intent = (
            base_intent
            if base_intent == retrieval.Intent.PROCEDURAL
            else retrieval.Intent.CODE_SPECIFIC
        )
    else:
        intent = base_intent

    log.append(
        f"[routing] intent={intent.value} | "
        f"code={','.join(c for _,c in registry_matches) if registry_matches else '-'} | "
        f"db={','.join(e['id'] for e,_ in registry_matches) if registry_matches else '-'}"
    )

    # ── 3. CODE_SPECIFIC: lookup collaterale, nessun embedding, nessun LLM ─
    if intent == retrieval.Intent.CODE_SPECIFIC:
        chunks: list[dict] = []
        active_entries: list[dict] = []
        for entry, code in registry_matches:
            results = retrieval.lookup_collateral(entry, code)
            if results:
                chunks += results
                active_entries.append(entry)

        if not chunks:
            log.append("[routing] nessun risultato collaterale → fallback vector search")
            intent = retrieval.Intent.GENERIC  # ricade nel ramo vector
        else:
            return QueryResult(
                mode="direct",
                intent=intent.value,
                codes=[c for _, c in registry_matches],
                dbs=[e["id"] for e in active_entries],
                chunks=chunks,
                answer=None,
                sources=_build_sources(chunks, active_entries),
                log=log,
            )

    # ── 4. Embedding (necessario per tutti i rami rimanenti) ───────────────
    normalized_query = normalize_query(q, intent)
    log.append(f"[normalization] embedding query: {normalized_query}")
    query_embedding = embeddings.get_embedding(normalized_query)  # può raise

    # ── 5. PROCEDURAL + codice: collaterale + vector search → LLM ─────────
    if intent == retrieval.Intent.PROCEDURAL and registry_matches:
        collateral: list[dict] = []
        active_entries = []
        for entry, code in registry_matches:
            results = retrieval.lookup_collateral(entry, code)
            if results:
                collateral += results
                active_entries.append(entry)
        vec_chunks = retrieval.vector_search(query_embedding)
        combined   = collateral + vec_chunks

        if not combined:
            return QueryResult(
                mode="empty",
                intent=intent.value,
                codes=[c for _, c in registry_matches],
                dbs=[],
                chunks=[],
                answer=None,
                sources=[],
                log=log,
            )

        context = prompt_module.format_context(combined)
        answer  = llm.generate_answer(q, context, used_structured_by_code=False)
        return QueryResult(
            mode="llm",
            intent=intent.value,
            codes=[c for _, c in registry_matches],
            dbs=[e["id"] for e in active_entries],
            chunks=combined,
            answer=answer,
            sources=_build_sources(combined, active_entries),
            log=log,
        )

    # ── 6. CLASSIFICATION / GENERIC: solo vector search → LLM ─────────────
    type_filters = (
        ["ANNEX_CODE"] if intent == retrieval.Intent.CLASSIFICATION else None
    )

    chunks = retrieval.vector_search(query_embedding, type_filters=type_filters)

    if not chunks and type_filters:
        log.append(f"[routing] nessun risultato con filtri={type_filters} → fallback global")
        chunks = retrieval.vector_search(query_embedding)

    if not chunks:
        return QueryResult(
            mode="empty",
            intent=intent.value,
            codes=[c for _, c in registry_matches],
            dbs=[],
            chunks=[],
            answer=None,
            sources=[],
            log=log,
        )

    context = prompt_module.format_context(chunks)
    answer  = llm.generate_answer(q, context, used_structured_by_code=False)
    return QueryResult(
        mode="llm",
        intent=intent.value,
        codes=[c for _, c in registry_matches],
        dbs=[],
        chunks=chunks,
        answer=answer,
        sources=_build_sources(chunks, []),
        log=log,
    )


# ---------------------------------------------------------------------------
# Run – wrapper CLI (output identico all'attuale)
# ---------------------------------------------------------------------------

def run(question: str) -> None:
    q = (question or "").strip()
    if not q:
        print("Errore: domanda vuota.")
        sys.exit(1)

    try:
        result = query(q)
    except (APIError, APIConnectionError, ValueError) as e:
        print("Errore:", e)
        sys.exit(1)

    for msg in result["log"]:
        print(msg)

    if result["mode"] == "empty":
        print("Nessun risultato trovato.")
        sys.exit(0)
    elif result["mode"] == "direct":
        _display_direct_text(result["chunks"])
    else:
        print("\n=== RISPOSTA ===\n")
        print(result["answer"])

    _render_sources(result["sources"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python main.py "domanda"')
        sys.exit(1)

    run(" ".join(sys.argv[1:]))
