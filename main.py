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
    articles = [c.get("article_number") or "" for c in chunks if c.get("article_number")]
    print("---")
    print("Domanda:", question[:200] + ("..." if len(question) > 200 else ""))
    print("Chunk recuperati:", len(chunks))
    print("Articoli trovati:", articles if articles else "(nessuno)")
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

    # 2) Vector search
    try:
        chunks: list[ChunkRow] = retrieval.search_chunks(query_embedding)
    except ValueError as e:
        print("Errore configurazione Supabase:", e)
        sys.exit(1)
    except Exception as e:
        print("Errore connessione Supabase o RPC:", e)
        sys.exit(1)

    if not chunks:
        print("Nessun risultato dal retrieval. L'informazione non è presente nel database.")
        sys.exit(0)

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
