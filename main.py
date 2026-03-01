"""
CustomsAI – Intent-aware main
with deterministic query normalization layer
"""

import sys
import re

from openai import APIError, APIConnectionError

import embeddings
import retrieval
import prompt as prompt_module
import llm
from query_normalizer import normalize_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def contains_specific_reference(query: str) -> bool:
    if not query:
        return False

    if re.search(r"\b[0-9][A-Za-z][0-9]{3}\b", query):
        return True

    if re.search(r"\b\d{4,10}\b", query):
        return True

    return False


def extract_celex_from_chunks(chunks: list[dict]) -> list[str]:
    celex_set = set()

    for c in chunks:
        celex = c.get("celex_consolidated")
        if celex:
            celex_set.add(str(celex))

    return sorted(celex_set)


def eurlex_link(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{celex}"


def print_normative_sources(chunks: list[dict]) -> None:
    celex_list = extract_celex_from_chunks(chunks)

    if not celex_list:
        return

    print("\n---")
    print("FONTI NORMATIVE (deterministiche)\n")

    for celex in celex_list:
        print(f"CELEX: {celex}")
        print(eurlex_link(celex))
        print()

    print("---")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(question: str) -> None:

    q = (question or "").strip()
    if not q:
        print("Errore: domanda vuota.")
        sys.exit(1)

    # Detect intent early (deterministic)
    intent = retrieval.detect_intent(q)

    # Normalize only for embedding generation
    normalized_query = normalize_query(q, intent)

    print(f"[normalization] embedding query: {normalized_query}")

    # ------------------------------------------------------------------
    # FULL TEXT MODE (direct reference)
    # ------------------------------------------------------------------

    if contains_specific_reference(q):

        try:
            query_embedding = embeddings.get_embedding(normalized_query)
            chunks, _ = retrieval.search_chunks(q, query_embedding)

            if not chunks:
                print("Nessun risultato trovato.")
                sys.exit(0)

            print("\n=== OFFICIAL NORMATIVE TEXT ===\n")

            for chunk in chunks:
                print(chunk.get("chunk_text"))
                print("\n---")

            print_normative_sources(chunks)

        except Exception as e:
            print("Errore retrieval:", e)
            sys.exit(1)

        return

    # ------------------------------------------------------------------
    # INTERPRETATIVE MODE
    # ------------------------------------------------------------------

    try:
        query_embedding = embeddings.get_embedding(normalized_query)
        chunks, used_structured_by_code = retrieval.search_chunks(q, query_embedding)

        if not chunks:
            print("Nessun risultato trovato.")
            sys.exit(0)

        context = prompt_module.format_context(chunks)

        answer = llm.generate_answer(
            q,  # original user question
            context,
            used_structured_by_code=used_structured_by_code,
        )

        print("\n=== RISPOSTA ===\n")
        print(answer)

        print_normative_sources(chunks)

        print("\n---")

    except (APIError, APIConnectionError) as e:
        print("Errore LLM:", e)
        sys.exit(1)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python main.py \"domanda\"")
        sys.exit(1)

    run(" ".join(sys.argv[1:]))