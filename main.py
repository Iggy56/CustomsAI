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

from openai import APIError, APIConnectionError

import config
import embeddings
import retrieval
import prompt as prompt_module
import llm
from query_normalizer import normalize_query
from registry import detect_code_from_registry


# ---------------------------------------------------------------------------
# Source printing (deterministico)
# ---------------------------------------------------------------------------

def _eurlex_link(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{celex}"


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
    lines: list[str] = []

    # 1. Fonti statiche dal registry (es. nomenclature, dual_use_correlations)
    for entry in registry_entries:
        src = entry.get("source", {})
        if src.get("type") == "static_celex":
            if src.get("label"):
                lines.append(src["label"])
            lines.append(f"CELEX: {src['celex']}")
            lines.append(src["url"])
            lines.append("")

    # 2. CELEX dinamici dai chunk (celex_field)
    seen: set[str] = set()
    for c in chunks:
        celex = c.get("celex_consolidated")
        if celex and celex not in seen:
            seen.add(celex)
            lines.append(f"CELEX: {celex}")
            lines.append(_eurlex_link(celex))
            lines.append("")

    if not lines:
        return

    print("\n---")
    print("FONTI NORMATIVE (deterministiche)\n")
    print("\n".join(lines))
    print("---")


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_direct_text(chunks: list[dict]) -> None:
    print("\n=== TESTO NORMATIVO ===\n")
    for r in chunks:
        print(r.get("chunk_text", ""))
        print("\n---")


def _run_llm_and_print(
    question: str,
    chunks: list[dict],
    registry_entries: list[dict],
) -> None:
    context = prompt_module.format_context(chunks)
    answer = llm.generate_answer(question, context, used_structured_by_code=False)
    print("\n=== RISPOSTA ===\n")
    print(answer)
    _print_normative_sources(chunks, registry_entries)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(question: str) -> None:
    q = (question or "").strip()
    if not q:
        print("Errore: domanda vuota.")
        sys.exit(1)

    # ── 1. Intent (keyword) + codice (registry pattern scan) ──────────────
    base_intent     = retrieval.detect_intent(q)
    registry_matches = detect_code_from_registry(q)   # list[tuple[dict, str]]
    registry_entries = [e for e, _ in registry_matches]

    # ── 2. Intent finale ───────────────────────────────────────────────────
    # Se c'è almeno un codice e l'intent non è procedurale → CODE_SPECIFIC
    if registry_matches:
        intent = (
            base_intent
            if base_intent == retrieval.Intent.PROCEDURAL
            else retrieval.Intent.CODE_SPECIFIC
        )
    else:
        intent = base_intent

    print(
        f"[routing] intent={intent.value} | "
        f"code={','.join(c for _,c in registry_matches) if registry_matches else '-'} | "
        f"db={','.join(e['id'] for e,_ in registry_matches) if registry_matches else '-'}"
    )

    # ── 3. CODE_SPECIFIC: lookup collaterale, nessun embedding, nessun LLM ─
    if intent == retrieval.Intent.CODE_SPECIFIC:
        chunks = []
        active_entries: list[dict] = []   # solo entry che hanno prodotto risultati
        for entry, code in registry_matches:
            results = retrieval.lookup_collateral(entry, code)
            if results:
                chunks += results
                active_entries.append(entry)

        if not chunks:
            print("[routing] nessun risultato collaterale → fallback vector search")
            intent = retrieval.Intent.GENERIC  # ricade nel ramo vector
        else:
            _display_direct_text(chunks)
            _print_normative_sources(chunks, active_entries)
            return

    # ── 4. Embedding (necessario per tutti i rami rimanenti) ───────────────
    normalized_query = normalize_query(q, intent)
    print(f"[normalization] embedding query: {normalized_query}")

    try:
        query_embedding = embeddings.get_embedding(normalized_query)
    except Exception as e:
        print("Errore embedding:", e)
        sys.exit(1)

    # ── 5. PROCEDURAL + codice: collaterale + vector search → LLM ─────────
    if intent == retrieval.Intent.PROCEDURAL and registry_matches:
        collateral = []
        active_entries = []   # solo entry che hanno prodotto risultati
        for entry, code in registry_matches:
            results = retrieval.lookup_collateral(entry, code)
            if results:
                collateral += results
                active_entries.append(entry)
        vec_chunks = retrieval.vector_search(query_embedding)
        combined   = collateral + vec_chunks

        if not combined:
            print("Nessun risultato trovato.")
            sys.exit(0)

        try:
            _run_llm_and_print(q, combined, active_entries)
        except (APIError, APIConnectionError, ValueError) as e:
            print("Errore LLM:", e)
            sys.exit(1)

        return

    # ── 6. CLASSIFICATION / GENERIC: solo vector search → LLM ─────────────
    type_filters = (
        ["ANNEX_CODE"] if intent == retrieval.Intent.CLASSIFICATION else None
    )

    chunks = retrieval.vector_search(query_embedding, type_filters=type_filters)

    if not chunks and type_filters:
        print(f"[routing] nessun risultato con filtri={type_filters} → fallback global")
        chunks = retrieval.vector_search(query_embedding)

    if not chunks:
        print("Nessun risultato trovato.")
        sys.exit(0)

    try:
        _run_llm_and_print(q, chunks, registry_entries=[])
    except (APIError, APIConnectionError, ValueError) as e:
        print("Errore LLM:", e)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python main.py "domanda"')
        sys.exit(1)

    run(" ".join(sys.argv[1:]))
