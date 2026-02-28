"""
Build the LLM prompt: system instructions and context from retrieved chunks.
The model must use only this context and cite articles; no external knowledge.
"""

from retrieval import ChunkRow

# System prompt for interpretative questions (conceptual queries, multiple articles).
# Cursorrules: use only context, cite articles, state when info is absent.
SYSTEM_PROMPT = """Usa esclusivamente le informazioni presenti nel CONTESTO.

Puoi formulare risposte sintetiche combinando informazioni provenienti da più articoli.

Se il contesto consente di dedurre un obbligo, esplicitalo chiaramente citando gli articoli.

Se la risposta non è presente, scrivi:
"Informazione non presente nel contesto fornito."

Fornisci:

1. Risposta sintetica
2. Articoli rilevanti (se presenti)
3. Ambito di applicazione (se disponibile)
4. Note o eccezioni (se presenti)

Cita sempre gli articoli quando disponibili."""

# Modalità "codice diretto": quando l'utente chiede il contenuto di un codice normativo
# (retrieval strutturato per code), il modello deve trascrivere il testo, non interpretare.
# Nessuna sintesi, nessuna sezione aggiuntiva, nessuna conoscenza esterna.
SYSTEM_PROMPT_CODICE_DIRETTO = """Usa ESCLUSIVAMENTE il testo presente nel CONTESTO.

Il tuo compito è RIPORTARE il testo normativo così com'è nel contesto.

NON sintetizzare.
NON riformulare.
NON interpretare.
NON aggiungere elenchi, punti (a, b, c) o struttura che non sia già nel testo.
NON usare conoscenza esterna.
NON completare parti mancanti.

Riporta il testo normativo in modo fedele e integrale. Se nel contesto è indicato un CELEX, puoi citarlo una sola volta all'inizio.

Non aggiungere sezioni come "Note o eccezioni" o "Ambito" se non sono presenti nel contesto.
Se il contesto è vuoto o non pertinente, scrivi solo: "Informazione non presente nel contesto fornito."."""


def _metadata_header(meta: dict) -> str:
    """
    Build a one-line header from metadata for LLM context.
    Uses only keys that exist; format is readable and structure-rich for RAG.
    Examples: [TYPE: article | CELEX: 32021R0821 | Art: 12 | Par: 3 | Let: b]
    """
    if not meta or not isinstance(meta, dict):
        return ""
    segs = []
    if meta.get("type") is not None:
        segs.append(f"TYPE: {meta.get('type')}")
    if meta.get("celex") is not None:
        segs.append(f"CELEX: {meta.get('celex')}")
    typ = meta.get("type")
    if typ == "recital":
        recital_num = meta.get("paragraph") or meta.get("article")
        if recital_num is not None:
            segs.append(f"Recital: {recital_num}")
    else:
        if meta.get("article") is not None:
            segs.append(f"Art: {meta.get('article')}")
        if meta.get("paragraph") is not None:
            segs.append(f"Par: {meta.get('paragraph')}")
    if meta.get("letter") is not None:
        segs.append(f"Let: {meta.get('letter')}")
    if meta.get("annex") is not None:
        segs.append(f"Annex: {meta.get('annex')}")
    if meta.get("code") is not None:
        segs.append(f"Code: {meta.get('code')}")
    if not segs:
        return ""
    return "[" + " | ".join(segs) + "]"


def format_context(chunks: list[ChunkRow]) -> str:
    """
    Turn retrieved chunks into a single CONTESTO string for the LLM.
    Each block starts with a metadata header (when present) then chunk text.
    Metadata improves RAG quality by giving the model structure (type, celex, article, etc.).
    Backward compatible: if metadata is missing, only text/title/source are used.
    """
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, 1):
        text = c.get("chunk_text") or ""
        meta = c.get("metadata")
        if isinstance(meta, dict):
            header = _metadata_header(meta)
        else:
            header = ""
        title = c.get("title") or ""
        url = c.get("source_url") or ""
        block = [f"[Chunk {i}]"]
        if header:
            block.append(header)
        if title:
            block.append(f"Titolo: {title}")
        if text:
            block.append(text)
        if url:
            block.append(f"Fonte: {url}")
        parts.append("\n".join(block))
    return "\n\n---\n\n".join(parts)


def build_messages(
    question: str,
    context: str,
    used_structured_by_code: bool = False,
) -> list[dict[str, str]]:
    """
    Build OpenAI-style messages: system (instructions) + user (question + context).
    When used_structured_by_code is True (retrieval strutturato per codice normativo),
    use the restrictive "codice diretto" prompt so the model transcribes the text without synthesizing.
    """
    system_prompt = (
        SYSTEM_PROMPT_CODICE_DIRETTO if used_structured_by_code else SYSTEM_PROMPT
    )
    user_content = f"CONTESTO:\n\n{context}\n\nDOMANDA: {question}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
