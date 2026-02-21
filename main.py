"""
RAG pipeline: question → embedding → vector search → LLM → cited answer.
Generic over any normative content in chunks; no domain-specific logic.
"""

import sys

from openai import APIError, APIConnectionError

import config
import embeddings
import retrieval
import prompt as prompt_module
import llm
from retrieval import ChunkRow

# ---------------------------------------------------------------------------
# Logging (cursorrules: print question, n chunks, articles, context length, answer)
# ---------------------------------------------------------------------------


def log_run(question: str, chunks: list[ChunkRow], context: str, answer: str) -> None:
    """Print debug info for retrieval and response quality."""
    # Collect article/code from metadata when present (backward compatible)
    refs = []
    for c in chunks:
        meta = c.get("metadata") or {}
        if isinstance(meta, dict):
            if meta.get("article") is not None:
                refs.append(str(meta.get("article")))
            elif meta.get("code") is not None:
                refs.append(str(meta.get("code")))
    print("---")
    print("Domanda:", question[:200] + ("..." if len(question) > 200 else ""))
    print("Chunk recuperati:", len(chunks))
    print("Articoli/code trovati:", refs if refs else "(nessuno)")
    print("Lunghezza contesto (caratteri):", len(context))
    print("---")
    print("Risposta:\n", answer)
    print("---")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run(question: str) -> None:
    """
    Run the full pipeline. On missing config, API errors, or no results, print a clear
    message and exit without producing a fake answer.
    """
    q = (question or "").strip()
    if not q:
        print("Errore: fornire una domanda non vuota.")
        sys.exit(1)

    # 1) Embedding
    try:
        if not config.OPENAI_API_KEY:
            print("Errore: OPENAI_API_KEY non impostata.")
            sys.exit(1)
        query_embedding = embeddings.get_embedding(q)
    except Exception as e:
        print("Errore durante la generazione dell'embedding:", e)
        sys.exit(1)

    # 2) Hybrid retrieval (structured by code if detected, else vector search)
    try:
        chunks: list[ChunkRow] = retrieval.search_chunks(q, query_embedding)
    except ValueError as e:
        print("Errore configurazione Supabase:", e)
        sys.exit(1)
    except Exception as e:
        print("Errore connessione Supabase o RPC:", e)
        sys.exit(1)

    if not chunks:
        print("Nessun risultato dal retrieval. L'informazione non è presente nel database.")
        sys.exit(0)

    # Debug: type, celex, article/code, similarity per chunk
    print("\nTop chunks:")
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        typ = meta.get("type", "N/A")
        celex = meta.get("celex", "N/A")
        art_or_code = meta.get("article") or meta.get("code") or "N/A"
        print(f"\n[{i+1}] type={typ} | celex={celex} | article/code={art_or_code} | similarity={chunk.get('similarity', 'N/A')}")
        chunk_text = chunk.get("chunk_text") or ""
        print(f"Preview: {chunk_text[:200]}...")

    # 3) Context and length check
    context = prompt_module.format_context(chunks)
    if len(context) > config.MAX_CONTEXT_CHARS:
        print(
            f"Errore: contesto troppo lungo ({len(context)} caratteri). "
            f"Limite: {config.MAX_CONTEXT_CHARS}."
        )
        sys.exit(1)

    # 4) LLM
    try:
        answer = llm.generate_answer(q, context)
    except (APIError, APIConnectionError) as e:
        print("Errore API OpenAI:", e)
        sys.exit(1)
    except ValueError as e:
        print(e)
        sys.exit(1)

    log_run(q, chunks, context, answer)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python main.py \"domanda\"")
        sys.exit(1)
    run(" ".join(sys.argv[1:]))
