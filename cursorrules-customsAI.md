# .cursorrules – CustomsAI v7

## 1. Missione attuale del sistema

CustomsAI è un **motore normativo AI-first** per interrogare normativa strutturata
e sistemi di classificazione doganale, con comportamento deterministico, tracciabile e verificabile.

Obiettivo:
- ricevere una domanda
- determinare il tipo di interrogazione e il codice eventualmente presente
- eseguire retrieval sul DB corretto tramite registry config-driven
- generare risposta SOLO dal contesto recuperato
- garantire tracciabilità delle fonti
- impedire hallucination normativa

Il sistema deve essere: ✔ generico ✔ domain-agnostic ✔ deterministico ✔ scalabile ✔ auditabile

---

## 2. Principi architetturali obbligatori

**Separazione dei layer** — Parsing ≠ Chunking ≠ Embedding ≠ Retrieval ≠ LLM. Nessuna logica cross-layer.

**Determinismo** — Nessun routing LLM. Nessuna fonte generata dall'LLM. Nessuna conoscenza esterna.

**Database-first** — Se un dato non è nel DB non può essere citato né dedotto.

**Registry-first** — Il routing verso i DB collaterali è guidato esclusivamente da `registry.py`.
Nessun pattern di codice o nome di tabella è hardcoded nel codice di retrieval.

---

## 3. Architettura del database

### `chunks` (Layer 1)

Campi: `text`, `embedding vector(1536)`, `metadata jsonb`, `celex_consolidated`, `source_url`.
`metadata.code` è popolato SOLO per `unit_type=ANNEX_CODE` (codici dual-use, pattern `[0-9][A-Z][0-9]{3}`).

### `dual_use_items` (Layer 2 – DB collaterale)

Campi: `code`, `celex_consolidated`, `consolidation_date`, `description`.
Match: esatto su `code` (es. `2B002`).

### `nomenclature` (DB collaterale)

Campi: `goods_code`, `indent`, `description`, ecc.
`goods_code` ha formato `{10 cifre} {2 cifre}` (es. `8544000000 80`) — il suffisso viene rimosso nella visualizzazione.
Match: per prefisso (`LIKE '8544%'`) per restituire l'intera gerarchia.
`indent=null` = voce principale; `"-"` = primo livello; `"- -"` = secondo, ecc.

### `dual_use_correlations` (DB collaterale)

Campi: `cn_codes_2026` (10 cifre), `dual_use_codification`.
Una riga = un mapping NC → DU. Match: prefisso.

---

## 4. Registry dei DB collaterali

Il file `registry.py` è l'**unico punto di configurazione** per i DB collaterali.
Aggiungere un nuovo DB = aggiungere una entry in `REGISTRY`. **Nessun altro file va modificato.**

### Struttura di ogni entry

```python
{
    "id": str,                   # identificatore univoco
    "table": str,                # nome tabella Supabase
    "code_field": str,           # campo su cui fare il lookup
    "text_field": str,           # campo testo da restituire
    "pattern": str,              # regex per riconoscere il codice nell'input utente
    "label": str,                # etichetta human-readable
    "match_mode": str,           # "exact" | "prefix"
    "display_code_field": str,   # (opzionale) chunk_text include codice + gerarchia (indent)
    "links_to": str,             # (opzionale) i text_value di questa entry sono codici
                                 # dell'entry con questo id — usato per correlation graph
    "source": dict,              # configurazione fonte (celex_field | static_celex)
}
```

### Entry attive

```python
REGISTRY = [
    {
        "id": "dual_use",
        "table": "dual_use_items",
        "code_field": "code",
        "text_field": "description",
        "pattern": r"\b[0-9][A-Z][0-9]{3}\b",   # es. 2B002
        "label": "Bene a duplice uso",
        "match_mode": "exact",
        "source": {"type": "celex_field"},
    },
    {
        "id": "nomenclature",
        "table": "nomenclature",
        "code_field": "goods_code",
        "text_field": "description",
        "pattern": r"\b\d{4,10}\b",              # es. 8544
        "label": "Nomenclatura Combinata",
        "match_mode": "prefix",
        "display_code_field": "goods_code",
        "source": {
            "type": "static_celex",
            "celex": "31987R2658",
            "url": "https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=celex:31987R2658",
            "label": "Nomenclatura Combinata (Reg. CEE 2658/87)",
        },
    },
    {
        "id": "dual_use_correlations",
        "table": "dual_use_correlations",
        "code_field": "cn_codes_2026",
        "text_field": "dual_use_codification",
        "pattern": r"\b\d{4,10}\b",              # stesso di nomenclature → multi-match per NC
        "label": "Dual Use Correlations",
        "match_mode": "prefix",
        "display_code_field": "cn_codes_2026",
        "links_to": "dual_use",                  # i text_value sono codici DU → correlation graph
        "source": {
            "type": "static_celex",
            "celex": "32021R0821",
            "url": "https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:32021R0821",
            "label": "Regolamento UE 2021/821 (Beni a duplice uso)",
        },
    },
]
```

**Multi-match**: `dual_use_correlations` e `nomenclature` condividono `\b\d{4,10}\b` → una query con codice NC produce due match e viene eseguito `lookup_collateral` su entrambe.

---

## 5. Mappa dei file

```
main.py              # Pipeline: query() → QueryResult, run() (CLI wrapper)
                     #   + _format_eurlex_text() formatter EUR-Lex
                     #   + _extract_linked_codes(), _build_correlation_preamble()
app.py               # Interfaccia web Streamlit
config.py            # Env vars, costanti (modelli, TOP_K, MAX_CONTEXT_CHARS)
registry.py          # REGISTRY + detect_code_from_registry() ← unico punto di config
retrieval.py         # detect_intent(), lookup_collateral(), vector_search(),
                     #   get_annex_chunks_by_codes()
prompt.py            # Context builder + system prompts (DISCLAIMER, ANALYTICAL, standard)
llm.py               # Chiamata LLM
embeddings.py        # Generazione embedding (OpenAI)
query_normalizer.py  # Normalizzazione query per embedding
supabase_rpc.sql     # Funzione search_chunks_multi_type (deploy su Supabase)

tools/
  scan_db.py         # Scanner automatizzato: valida registry + profila nuove tabelle
  catalog.sql        # Funzioni RPC Supabase per introspezione

tests/               # 120 test su 6 file (L1 unit, L2 mock, L3 e2e)
```

---

## 6. Pipeline obbligatoria

### `query(question) -> QueryResult`

Tutta la logica computazionale è in `query()`. Nessun print: i messaggi di routing vanno in `result["log"]`.

```
query(question)
  ↓
  detect_intent (keyword)          → retrieval.py
  detect_code_from_registry        → registry.py  →  list[tuple[dict, str]]
  │
  ├─ CODE_SPECIFIC (codice trovato, no keyword procedurale)
  │       for entry, code in registry_matches:
  │           lookup_collateral(entry, code)
  │       → mode="direct" (nessun LLM)
  │       → se vuoto: fallback GENERIC
  │
  ├─ PROCEDURAL (codice trovato + keyword procedurale)
  │       for entry, code in registry_matches:
  │           lookup_collateral(entry, code)
  │       _extract_linked_codes() → linked DU codes (entries con links_to)
  │       se linked_codes:
  │           get_annex_chunks_by_codes(linked_codes)   [Opzione A]
  │           vector_search(embedding DU-focused)        [Opzione B]
  │           analytical=True → SYSTEM_PROMPT_ANALYTICAL
  │       altrimenti:
  │           vector_search(query_embedding)
  │       _build_correlation_preamble() → preamble contesto NC→DU
  │       LLM con combined context + preamble
  │       answer += DISCLAIMER
  │       → mode="llm"
  │
  ├─ CLASSIFICATION (keyword classificazione, no codice)
  │       vector_search(embedding, ["ANNEX_CODE"])
  │       → se vuoto: fallback global
  │       LLM → mode="llm"
  │
  └─ GENERIC
          vector_search(query_embedding)
          LLM → mode="llm"
  ↓
  _build_sources(chunks, active_entries) → list[dict]
```

### `QueryResult` (TypedDict)

```python
class QueryResult(TypedDict):
    mode:    str          # "direct" | "llm" | "empty"
    intent:  str
    codes:   list[str]
    dbs:     list[str]    # ID entry con ≥1 risultato
    chunks:  list[dict]
    answer:  str | None
    sources: list[dict]   # [{"label": str|None, "celex": str, "url": str}]
    log:     list[str]
```

---

## 7. Regole di routing

### Rilevamento codice

`detect_code_from_registry(query)` scansiona **tutti** i pattern (re.IGNORECASE), normalizza in UPPERCASE,
restituisce `list[tuple[dict, str]]`. La pipeline itera su tutti i match.

### Intent detection

| Intent | Trigger | Retrieval |
|---|---|---|
| `code_specific` | codice presente + no keyword procedurale | solo DB collaterale |
| `procedural` | codice + "esportare", "obblighi", "cosa devo fare", "procedura", "autorizzazione" | collaterale + annex + vector |
| `classification` | "che codice", "voce doganale", "classificazione" | chunks ANNEX_CODE |
| `generic` | default | chunks global |

Override in `main.py`: codice trovato + intent ≠ PROCEDURAL → intent diventa CODE_SPECIFIC.

### Fallback

- CODE_SPECIFIC senza risultati → fallback GENERIC
- CLASSIFICATION senza risultati filtrati → fallback global vector search

---

## 8. Correlation graph (Fase 3)

### `_extract_linked_codes(registry_matches, collateral_results) -> list[str]`

Estrae i codici "linked" dai risultati collaterali delle entry con `links_to`.
Non contiene logica hardcoded: legge `links_to` dal registry.

Esempio: `dual_use_correlations` ha `links_to="dual_use"` → i `text_value` dei suoi risultati
sono codici DU (es. `"3E001"`) da usare per annex lookup e analytical embedding.

### `_build_correlation_preamble(registry_matches, collateral_results) -> str`

Costruisce un riepilogo testuale delle correlazioni NC→DU da includere nel contesto LLM:

```
CORRELAZIONI RILEVATE NEL DATABASE:
- NC 8544300000 → Dual Use Correlations: 3E001
```

### Modalità Analytical

Attivata automaticamente se `linked_codes` è non vuoto (intent PROCEDURAL + correlazioni trovate).

- **Opzione A** (`get_annex_chunks_by_codes`): recupera i chunk `ANNEX_CODE` dai `chunks` filtrando
  per `metadata->>code` = codice DU. Dà la definizione normativa esatta dell'allegato dual-use.
- **Opzione B** (vector search): embedding costruito sui codici DU (`"obblighi autorizzazione esportazione {du_codes}"`),
  non sul codice NC, per evitare che il vettore punti verso la nomenclatura.
- Usa `SYSTEM_PROMPT_ANALYTICAL` → risposta strutturata articolo per articolo.

---

## 9. EUR-Lex text formatter

`_format_eurlex_text(text: str) -> str` in `main.py`.

Converte il plain text EUR-Lex (allegati dual-use) in markdown multilivello. Best-effort (~85% accuratezza
su strutture profonde). Il testo originale è sempre disponibile nell'expander Streamlit.

### Livelli

| Marcatore | Output |
|-----------|--------|
| `a.` `b.` (livello 1) | `- **a.** testo` |
| `1.` `2.` (livello 2) | `  - **1.** testo` |
| `a.` `b.` (livello 3) | `    - **a.** testo` |
| `1.` `2.` (livello 4) | `      - **1.** testo` |
| `—` (em dash) | `  - testo` |
| `e` / `o` su riga propria | connettore inline: `testo; **e**` |
| `Note tecniche:` / `N.B.` | intestazione in corsivo `*Note tecniche:*` |
| testo sotto Note/N.B. | corsivo `*testo*` |
| numerati dentro Note | `  *1. testo*` |

### Helper

- `_is_list_marker(line)` — True se la riga è `a.`, `1.` o `—`
- `_is_section_break(line)` — True se `_is_list_marker` OPPURE intestazione nota (`Note tecniche`, `N.B.`, ecc.)
  Usato in tutti i loop di raccolta testo per fermarsi correttamente.

### Stato interno

`depth`, `next_d1`, `next_d3`, `last_text`, `in_note`, `connector`

La profondità di una lettera è determinata dal contesto (profondità precedente + indice lettera).
Euristiche: `last_text.endswith(':')` segnala che il livello successivo scende di profondità.

### Dual rendering in Streamlit (app.py)

Per `mode="direct"`:
```python
st.markdown(_format_eurlex_text(raw))           # formattato markdown
with st.expander("Testo originale EUR-Lex"):
    st.code(raw, language=None)                 # originale monospace
```

---

## 10. Fonti normative

### Helper

- `_build_sources(chunks, active_entries) -> list[dict]` — funzione pura.
- `_render_sources(sources)` — stampa testuale standard, usata da `run()`.
- `_print_normative_sources(chunks, registry_entries)` — firma invariata (compat. `test_sources.py`).

### Tipi

- `celex_field` — fonte letta da `celex_consolidated` della riga (chunks, dual_use_items).
- `static_celex` — fonte fissa dal registry (nomenclature, dual_use_correlations).

`active_entries` = solo le entry con ≥1 risultato. Le fonti delle entry vuote non compaiono.

---

## 11. Prompt LLM

### Tre modalità

| Modalità | Attiva quando | Sistema |
|----------|---------------|---------|
| Codice Diretto | intent=code_specific | `SYSTEM_PROMPT_CODICE_DIRETTO` — fedele, no sintesi |
| Interpretativa | intent=procedural/classification/generic | `SYSTEM_PROMPT` — strutturata |
| Analytical | PROCEDURAL + linked_codes trovati | `SYSTEM_PROMPT_ANALYTICAL` — articolo per articolo |

### DISCLAIMER

Costante in `prompt.py`, appesa a tutte le risposte `mode="llm"`:
> Le informazioni riportate sono generate automaticamente … non costituiscono consulenza legale …

### Regole assolute

- L'LLM non genera CELEX né fonti normative
- Il context builder accetta qualsiasi schema di metadata, senza assumere campi fissi
- `format_context(chunks, preamble="")` accetta preamble opzionale (es. correlazioni NC→DU)

---

## 12. Supabase RPC

### `search_chunks_multi_type` (attiva)

```sql
search_chunks_multi_type(
  query_embedding vector(1536),
  match_count     int,
  type_filters    text[] default null   -- es. ARRAY['ANNEX_CODE']
)
```

`type_filters=null` → ricerca globale. Filtro su `unit_type` (colonna, non metadata). Definita in `supabase_rpc.sql`.

### Catalog functions (`tools/catalog.sql`)

Deploy una volta sola: `list_public_tables()`, `get_table_columns(p_table)`, `sample_column_values(p_table, p_col, p_limit)`.

---

## 13. Scanner automatizzato (`tools/scan_db.py`)

```bash
python3 tools/scan_db.py              # report completo
python3 tools/scan_db.py --check-only # solo validazione registry
python3 tools/scan_db.py --json       # output JSON
```

**Validazione registry** (6 check per entry): tabella esiste, campi presenti, dati non vuoti,
pattern coverage ≥80%, lookup campione, consistenza fonte.

**Profiling nuove tabelle**: rileva code_field/text_field/match_mode, genera draft entry pronto per `registry.py`.

---

## 14. Procedura onboarding nuovo DB

```
1. Carica la tabella su Supabase (schema public)
2. python3 tools/scan_db.py  →  draft entry stampato automaticamente
3. Rivedi: pattern, match_mode, source, display_code_field, links_to (se applicabile)
4. Aggiungi entry in REGISTRY (registry.py)
5. python3 tools/scan_db.py --check-only  →  tutti ✅?
6. python3 -m pytest tests/ -v            →  tutti passed?
7. python3 main.py "tuo codice di test"   →  output corretto?
```

**Nessun altro file da modificare oltre a `registry.py`.**

---

## 15. Suite di test (120 test)

```
test_registry.py   L1 – struttura REGISTRY, pattern, multi-match, case-insensitive
test_intent.py     L1 – keyword detection, priorità PROCEDURAL
test_sources.py    L1 – fonti celex_field/static_celex, deduplicazione, output vuoto
test_retrieval.py  L2 – lookup_collateral (exact/prefix/display_code), vector_search (mock)
test_pipeline.py   L3 – run() end-to-end: 9 scenari
test_scan_db.py    L1 – funzioni pure scan_db.py
```

```bash
python3 -m pytest tests/ -v
```

---

## 16. Cosa è vietato

❌ Pattern di codice hardcoded fuori dal registry
❌ Branch `if/else` per tipo di codice fuori dal registry
❌ CELEX hardcoded nel codice (solo nel registry per fonti statiche)
❌ LLM che genera CELEX o fonti normative
❌ Classificazione automatica o reasoning predittivo
❌ Logica che assume un numero fisso di DB collaterali
❌ Modificare file diversi da `registry.py` per aggiungere un nuovo DB

---

## 17. Criteri di validazione

✔ `python3 -m pytest tests/ -v` → tutti passed (120)
✔ `python3 tools/scan_db.py --check-only` → tutti ✅
✔ Lookup dual-use: exact match, fonti celex_field
✔ Lookup NC: prefix match, gerarchia con codici, fonti static_celex
✔ PROCEDURAL con codice NC correlato DU: analytical mode, preamble correlazioni, DISCLAIMER
✔ EUR-Lex formatter: Note tecniche in corsivo, livelli gerarchici
✔ Streamlit: dual rendering (markdown + expander originale)
✔ Aggiungere un nuovo DB = solo `registry.py`

---

## 18. Filosofia

Prima stabilità. Poi sofisticazione.

```
Fase 1  – Retrieval stabile su chunks                          ✅
Fase 2  – Registry multi-DB + retrieval unificato              ✅
Fase 2b – Interfaccia web Streamlit                            ✅
Fase 3  – Correlation graph + formatter EUR-Lex + analytical   ✅ (parziale)
Fase 4  – Reasoning normativo avanzato
```

---

## 19. Changelog

### v7 (corrente)
- **Correlation graph** (Fase 3): `links_to` nel registry, `_extract_linked_codes()`,
  `_build_correlation_preamble()` in `main.py`.
- **Annex lookup** (`retrieval.py`): `get_annex_chunks_by_codes(codes)` — query diretta
  su `metadata->>code` per definizioni normative esatte dei codici DU collegati.
- **Analytical mode**: PROCEDURAL + linked_codes → embedding DU-focused (no deriva NC),
  `SYSTEM_PROMPT_ANALYTICAL` (struttura articolo per articolo), `analytical=True` in `llm.py`.
- **DISCLAIMER**: costante in `prompt.py`, appeso automaticamente a tutte le risposte `mode="llm"`.
- **EUR-Lex formatter** `_format_eurlex_text()` in `main.py`: state machine best-effort,
  livelli a./b./1./2./—, Note tecniche/N.B. in corsivo, `_is_section_break()` per terminazione corretta.
- **Dual rendering Streamlit**: `mode="direct"` → markdown formattato + expander originale monospace.
- `metadata["text_value"]` aggiunto in `lookup_collateral()` per tracciabilità del valore raw.
- Suite di test: 120 test, nessuna regressione.

### v6
- `query(question) -> QueryResult` estratta da `run()`. Logica senza print, routing in `result["log"]`.
- `QueryResult` TypedDict: `mode, intent, codes, dbs, chunks, answer, sources, log`.
- `_build_sources()` funzione pura. `_render_sources()` per CLI. `app.py` Streamlit.
- Suite di test: 120 test.

### v5
- Multi-match registry: `detect_code_from_registry()` → `list[tuple[dict, str]]`.
- Nuova entry `dual_use_correlations`. `display_code_field` su correlations.
- `active_entries`: fonti solo per entry con ≥1 risultato.
