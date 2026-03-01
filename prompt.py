"""
CustomsAI Prompt Engine – Deterministic Normative Mode
LLM is NOT allowed to generate normative sources.
Sources are printed separately by Python.
"""

from retrieval import ChunkRow


# ============================================================
# SYSTEM PROMPTS
# ============================================================

SYSTEM_PROMPT = """Agisci come consulente doganale senior specializzato in normativa UE.

REGOLE ASSOLUTE:

1. Usa ESCLUSIVAMENTE il testo presente nel CONTESTO.
2. Non usare conoscenza esterna.
3. Non formulare deduzioni non supportate.
4. Ogni affermazione deve essere collegata a un articolo presente nel contesto.
5. È VIETATO citare CELEX non presenti nel contesto.
6. È VIETATO generare riferimenti normativi non presenti nei chunk.
7. Non generare una sezione "FONTI NORMATIVE".
   Le fonti verranno gestite automaticamente dal sistema.
8. Se il contesto non contiene base normativa sufficiente, scrivi:
   "Il contesto fornito non contiene una base normativa sufficiente per rispondere in modo completo."

FORMATO OBBLIGATORIO:

1. INQUADRAMENTO NORMATIVO
   - Elenca SOLO gli articoli presenti nel contesto.
   - Indica SOLO il regolamento presente nel contesto.

2. CHECKLIST OPERATIVA PER L’ESPORTATORE

3. OBBLIGHI DOCUMENTALI

4. PROFILI DI RESPONSABILITÀ

Non aggiungere altre sezioni.
"""


SYSTEM_PROMPT_CODICE_DIRETTO = """Usa ESCLUSIVAMENTE il testo presente nel CONTESTO.

Riporta il testo normativo in modo fedele e integrale.
Non sintetizzare.
Non riformulare.
Non interpretare.
Non usare conoscenza esterna.

Non generare sezioni aggiuntive.
Non generare riferimenti normativi.
"""


# ============================================================
# Metadata header builder
# ============================================================

def _metadata_header(meta: dict, celex: str | None) -> str:
    if not meta or not isinstance(meta, dict):
        return ""

    segs = []

    if meta.get("type"):
        segs.append(f"TYPE: {meta.get('type')}")

    if celex:
        segs.append(f"CELEX: {celex}")

    if meta.get("article"):
        segs.append(f"Art: {meta.get('article')}")

    if meta.get("paragraph"):
        segs.append(f"Par: {meta.get('paragraph')}")

    if meta.get("annex"):
        segs.append(f"Annex: {meta.get('annex')}")

    if meta.get("code"):
        segs.append(f"Code: {meta.get('code')}")

    if not segs:
        return ""

    return "[" + " | ".join(segs) + "]"


# ============================================================
# Context formatter
# ============================================================

def format_context(chunks: list[ChunkRow]) -> str:
    if not chunks:
        return ""

    parts = []

    for i, c in enumerate(chunks, 1):
        text = c.get("chunk_text") or ""
        meta = c.get("metadata")
        celex = c.get("celex_consolidated")

        header = _metadata_header(meta, celex)

        block = [f"[Chunk {i}]"]

        if header:
            block.append(header)

        if text:
            block.append(text)

        parts.append("\n".join(block))

    return "\n\n---\n\n".join(parts)


# ============================================================
# Message builder
# ============================================================

def build_messages(
    question: str,
    context: str,
    used_structured_by_code: bool = False,
) -> list[dict[str, str]]:

    system_prompt = (
        SYSTEM_PROMPT_CODICE_DIRETTO if used_structured_by_code else SYSTEM_PROMPT
    )

    user_content = f"CONTESTO:\n\n{context}\n\nDOMANDA: {question}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]