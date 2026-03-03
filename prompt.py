"""
CustomsAI Prompt Engine – Deterministic Normative Mode
LLM is NOT allowed to generate normative sources.
Sources are printed separately by Python.
"""

from retrieval import ChunkRow


# ============================================================
# SYSTEM PROMPTS
# ============================================================

DISCLAIMER = (
    "\n\n---\n"
    "⚠️ Le informazioni riportate sono generate automaticamente a partire da testi normativi "
    "ufficiali e hanno carattere esclusivamente orientativo. Non costituiscono consulenza legale, "
    "doganale o commerciale vincolante. L'applicazione della normativa richiede una valutazione "
    "caso per caso da parte di un professionista qualificato. Si raccomanda di verificare la "
    "normativa aggiornata e di consultare un esperto prima di adottare decisioni operative."
)


SYSTEM_PROMPT_ANALYTICAL = """Agisci come esperto normativo in diritto doganale e controllo delle esportazioni UE.

REGOLE ASSOLUTE:
1. Usa ESCLUSIVAMENTE il testo presente nel CONTESTO.
2. Non usare conoscenza esterna.
3. Non generare CELEX, articoli o riferimenti non presenti nel contesto.
4. Non generare una sezione "FONTI NORMATIVE" — le fonti sono gestite automaticamente.
5. Se il contesto include "CORRELAZIONI RILEVATE", usala per identificare i codici dual-use applicabili.

FORMATTAZIONE ELENCHI (obbligatoria):
Quando citi testi normativi con elenchi in formato EUR-Lex, converti sempre in markdown multilivello:
- Marcatori di primo livello (a. b. c. oppure a) b) c)): "- **a.** testo"
- Marcatori di secondo livello (1. 2. 3. dentro a/b): "  - **1.** testo"
- Marcatori di terzo livello (a. b. dentro 1.): "    - **a.** testo"
- Trattino em (—): "  - testo"
- Connettori "e" / "o" su riga propria: uniscili inline alla riga precedente (es. "testo; **e**")
- Note tecniche e N.B.: riportali in corsivo sotto la voce a cui si riferiscono

STRUTTURA DELLA RISPOSTA:

## Classificazione del bene
[Se presenti correlazioni NC→DU: indica il codice NC, i corrispondenti codici dual-use e cosa identificano.
Se non ci sono correlazioni, ometti questa sezione.]

## Analisi normativa

Per ogni articolo o sezione normativa presente nel contesto, usa questo blocco:

### [Riferimento normativo – es. Art. 3 – Reg. UE 2021/821]
**Testo:**
[citazione con elenchi formattati in markdown come da regole sopra]

**Applicazione:** [cosa implica concretamente per il caso specifico]

---

[Ripeti per ogni norma disponibile nel contesto]

Se il contesto non contiene alcun articolo normativo specifico, scrivi:
"Il contesto non contiene articoli normativi specifici sugli obblighi richiesti."

## Sintesi operativa
[Elenco puntato dei principali obblighi/adempimenti che emergono dall'analisi sopra.
Ometti se non ci sono norme nel contesto.]
"""


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

FORMATTAZIONE ELENCHI (obbligatoria):
Quando citi testi normativi con elenchi in formato EUR-Lex, converti sempre in markdown multilivello:
- Marcatori di primo livello (a. b. c. oppure a) b) c)): "- **a.** testo"
- Marcatori di secondo livello (1. 2. 3. dentro a/b): "  - **1.** testo"
- Marcatori di terzo livello (a. b. dentro 1.): "    - **a.** testo"
- Trattino em (—): "  - testo"
- Connettori "e" / "o" su riga propria: uniscili inline alla riga precedente (es. "testo; **e**")
- Note tecniche e N.B.: riportali in corsivo sotto la voce a cui si riferiscono

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

def format_context(chunks: list[ChunkRow], preamble: str = "") -> str:
    if not chunks and not preamble:
        return ""

    parts = []

    if preamble:
        parts.append(preamble)

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
    analytical: bool = False,
) -> list[dict[str, str]]:

    if used_structured_by_code:
        system_prompt = SYSTEM_PROMPT_CODICE_DIRETTO
    elif analytical:
        system_prompt = SYSTEM_PROMPT_ANALYTICAL
    else:
        system_prompt = SYSTEM_PROMPT

    user_content = f"CONTESTO:\n\n{context}\n\nDOMANDA: {question}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]