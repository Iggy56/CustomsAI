"""
Build the LLM prompt: system instructions and context from retrieved chunks.
The model must use only this context and cite articles; no external knowledge.
"""

from retrieval import ChunkRow

# System prompt as per cursorrules: use only context, cite articles, state when info is absent.
SYSTEM_PROMPT = """Usa esclusivamente le informazioni presenti nel CONTESTO.

Se la risposta non è presente, scrivi:
"Informazione non presente nel contesto fornito."

Fornisci:

1. Risposta sintetica
2. Articoli rilevanti (se presenti)
3. Ambito di applicazione (se disponibile)
4. Note o eccezioni (se presenti)

Cita sempre gli articoli quando disponibili."""


def format_context(chunks: list[ChunkRow]) -> str:
    """
    Turn retrieved chunks into a single CONTESTO string for the LLM.
    Each block includes chunk text, article number, title, and source when available.
    """
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, 1):
        text = c.get("chunk_text") or ""
        art = c.get("article_number") or ""
        title = c.get("title") or ""
        url = c.get("source_url") or ""
        block = [f"[Chunk {i}]"]
        if title:
            block.append(f"Titolo: {title}")
        if art:
            block.append(f"Articolo: {art}")
        if text:
            block.append(text)
        if url:
            block.append(f"Fonte: {url}")
        parts.append("\n".join(block))
    return "\n\n---\n\n".join(parts)


def build_messages(question: str, context: str) -> list[dict[str, str]]:
    """
    Build OpenAI-style messages: system (instructions) + user (question + context).
    """
    user_content = f"CONTESTO:\n\n{context}\n\nDOMANDA: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
