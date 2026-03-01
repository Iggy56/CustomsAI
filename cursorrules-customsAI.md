# .cursorrules – CustomsAI v4

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

Il sistema deve essere:

✔ generico
✔ domain-agnostic
✔ deterministico
✔ scalabile
✔ auditabile

---

## 2. Principi architetturali obbligatori

### Separazione dei layer

Parsing ≠ Chunking ≠ Embedding ≠ Retrieval ≠ LLM

Nessuna logica cross-layer.

### Determinismo

- Nessuna dipendenza da LLM per routing
- Nessun filtro post-ranking lato Python
- Nessuna generazione di fonti da parte dell'LLM
- Nessuna conoscenza esterna

### Database-first

Il database è la fonte di verità normativa.

Se un dato non è nel DB → non può essere citato né dedotto.

### Registry-first

Il routing verso i DB collaterali è guidato esclusivamente da `registry.py`.

Nessun pattern di codice o nome di tabella è hardcoded nel codice di retrieval.

---

## 3. Architettura del database

Il sistema opera su tre tabelle Supabase:

### `chunks` (DB principale – Layer 1 Vectorize)

Contiene le unità normative estratte da Eur-Lex (articoli, allegati, codici dual-use).

Campi rilevanti:
- `text` – testo del chunk
- `embedding vector(1536)` – embedding OpenAI text-embedding-3-small
- `metadata jsonb` – `unit_type`, `celex_original`, `celex_consolidated`, `consolidation_date`, `article`, `paragraph`, `letter`, `annex`, `code`
- `celex_consolidated` – versione consolidata del documento
- `source_url` – link Eur-Lex

`metadata.code` è popolato SOLO per `unit_type=ANNEX_CODE` (codici dual-use, pattern `[0-9][A-Z][0-9]{3}`).

### `dual_use_items` (DB collaterale – Layer 2 Vectorize)

Contiene i codici beni dual-use con descrizione aggregata.

Campi: `code`, `celex_consolidated`, `consolidation_date`, `description`, `created_at`

Match: esatto su `code` (es. `2B002`).

### `nomenclature` (DB collaterale – importata da XLSX)

Contiene l'albero completo della Nomenclatura Combinata UE.

Campi: `goods_code`, `start_date`, `end_date`, `language_col`, `hier_pos`, `indent`, `description`, `descr_start_date`, `imported_at`

Note critiche:
- `goods_code` ha formato `{10 cifre} {2 cifre}` (es. `8544000000 80`) – il suffisso viene rimosso nella visualizzazione
- Match: per prefisso (`LIKE '8544%'`) per restituire l'intera gerarchia
- `indent` indica la profondità: `null` = voce principale, `-` = primo livello, `- -` = secondo, ecc.
- Visualizzazione: `display_code_field` attivo → codice + indentazione gerarchica nel testo
- Lingua attuale: EN. Versione IT sarà importata quando disponibile
- Fonte normativa: CELEX `31987R2658` (Reg. CEE 2658/87 – Nomenclatura Combinata)
- Link: `https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=celex:31987R2658`

---

## 4. Registry dei DB collaterali

Il file `registry.py` è l'**unico punto di configurazione** per i DB collaterali.

Aggiungere un nuovo DB collaterale = aggiungere una entry in `REGISTRY`.
**Nessun altro file deve essere modificato.**

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
    "display_code_field": str,   # (opzionale) se presente, il chunk_text include
                                 # il codice e l'indentazione gerarchica dal campo "indent"
    "source": dict,              # configurazione fonte (vedi sezione 7)
}
```

### Campo `display_code_field` (opzionale)

Se presente, `lookup_collateral()` formatta il `chunk_text` come:

```
{indent_spazi}{codice_numerico}  {testo}
```

- Il valore del campo (es. `goods_code = "8544000000 80"`) viene estratto con `.split()[0]`
- L'indentazione è calcolata dal campo `indent` della riga: `null`→0, `"-"`→2 spazi, `"- -"`→4 spazi, ecc.
- Usato per tabelle con struttura gerarchica (es. `nomenclature`)

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
        "source": {
            "type": "celex_field",
        },
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
]
```

### Priorità dei pattern

I pattern sono scansionati nell'ordine in cui appaiono in `REGISTRY`.
Il **primo match vince**. L'ordine è significativo: `dual_use` prima di `nomenclature`
per evitare che codici come `2B002` (che contiene cifre) vengano catturati dal pattern numerico.

---

## 5. Mappa dei file

```
CustomsAI/
├── main.py              # Pipeline orchestratore (routing a due variabili)
├── config.py            # Env vars, costanti (modelli, TOP_K, MAX_CONTEXT_CHARS)
├── registry.py          # REGISTRY + detect_code_from_registry() ← unico punto di config
├── retrieval.py         # Primitivi DB: detect_intent(), lookup_collateral(), vector_search()
├── prompt.py            # Context builder + system prompt (codice diretto / interpretativo)
├── llm.py               # Chiamata LLM
├── embeddings.py        # Generazione embedding (OpenAI)
├── query_normalizer.py  # Normalizzazione query per embedding (deterministico)
├── supabase_rpc.sql     # Funzione search_chunks_multi_type (deploy su Supabase)
│
├── tools/
│   ├── scan_db.py       # Scanner automatizzato: valida registry + profila nuove tabelle
│   └── catalog.sql      # Funzioni RPC Supabase per introspezione (deploy una volta sola)
│
└── tests/
    ├── test_registry.py      # L1 – pattern matching, struttura REGISTRY
    ├── test_intent.py        # L1 – keyword detection
    ├── test_sources.py       # L1 – fonti celex_field e static_celex
    ├── test_retrieval.py     # L2 – lookup_collateral e vector_search (mock Supabase)
    ├── test_pipeline.py      # L3 – run() end-to-end (tutto mockato)
    └── test_scan_db.py       # L1 – funzioni pure di scan_db.py
```

File **non modificare** senza motivo: `structured_lookup.py` (deprecato, non usato dalla pipeline).

---

## 6. Pipeline obbligatoria

```
User Question
↓
detect_intent (keyword-based, deterministico)         → retrieval.py
↓
detect_code_from_registry (scan pattern REGISTRY)     → registry.py
│
├─ Codice rilevato
│   ├─ intent = CODE_SPECIFIC
│   │       → lookup_collateral(entry, code)           → retrieval.py
│   │       → se risultati: TESTO DIRETTO, no LLM
│   │       → se vuoto: fallback vector search
│   │
│   └─ intent = PROCEDURAL
│           → lookup_collateral(entry, code)           → retrieval.py
│           → vector_search(embedding)                 → retrieval.py
│           → combined context → LLM INTERPRETATIVO
│
└─ Nessun codice
    ├─ intent = CLASSIFICATION
    │       → vector_search(embedding, ["ANNEX_CODE"]) → retrieval.py
    │       → se vuoto: fallback global vector search
    │       → LLM INTERPRETATIVO
    │
    └─ intent = GENERIC
            → vector_search(embedding)                 → retrieval.py
            → LLM INTERPRETATIVO
↓
format_context(chunks)                                 → prompt.py
↓
generate_answer(question, context)                     → llm.py
↓
Risposta
↓
_print_normative_sources(chunks, registry_entry)       → main.py
```

---

## 7. Regole di routing

### 7.1 Rilevamento codice

`detect_code_from_registry(query)` in `registry.py`:
- Scansiona `REGISTRY` in ordine
- Pattern compilati con `re.IGNORECASE`
- Il codice è normalizzato in **UPPERCASE** prima del lookup
- Restituisce `(entry, codice)` o `(None, None)`

È vietato:
- Hardcodare pattern di codice in `retrieval.py`, `main.py` o qualsiasi altro file
- Aggiungere branch `if/else` per tipo di codice fuori dal registry

### 7.2 Intent detection

`detect_intent(query)` in `retrieval.py` — solo keyword matching, nessuna logica su codici:

| Intent | Trigger | Retrieval |
|---|---|---|
| `code_specific` | codice presente + nessuna keyword procedurale | solo DB collaterale |
| `procedural` | codice + "esportare", "obblighi", "cosa devo fare", "procedura", "autorizzazione" | DB collaterale + chunks |
| `classification` | "che codice", "voce doganale", "classificazione" | chunks (ANNEX_CODE filter) |
| `generic` | nessuna delle precedenti | chunks (global vector) |

Regola di override in `main.py`:
- Se codice rilevato + intent ≠ PROCEDURAL → intent diventa CODE_SPECIFIC
- Se codice rilevato + intent = PROCEDURAL → rimane PROCEDURAL

### 7.3 Fallback

- CODE_SPECIFIC senza risultati collaterali → fallback GENERIC (vector search globale)
- CLASSIFICATION senza risultati filtrati → fallback global vector search

---

## 8. Fonti normative

Le fonti sono sempre stampate deterministicamente da `_print_normative_sources()` in `main.py`.
**Mai generate dall'LLM.**

### `celex_field`
La fonte è letta dal campo `celex_consolidated` della riga restituita.
Usato per: `dual_use_items`, `chunks`.
Link generato: `https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{celex}`

### `static_celex`
La fonte è fissa, definita nel registry.
Usato per: `nomenclature` e futuri DB senza CELEX dinamico per riga.
Richiede: `celex`, `url`, `label` nell'entry del registry.

### Output

```
---
FONTI NORMATIVE (deterministiche)

Nomenclatura Combinata (Reg. CEE 2658/87)    ← solo se static_celex
CELEX: 31987R2658
https://eur-lex.europa.eu/...

CELEX: 02021R0821                            ← da chunks (celex_field)
https://eur-lex.europa.eu/...

---
```

I due tipi non sono esclusivi: in un routing PROCEDURAL con codice, entrambi possono comparire.

---

## 9. Regole per il prompt LLM

### Modalità Codice Diretto
- Attiva quando intent=`code_specific`
- Riproduzione fedele del testo
- Nessuna sintesi, interpretazione o sezione aggiuntiva

### Modalità Interpretativa
- Attiva quando intent=`procedural`, `classification`, `generic`
- Sintesi strutturata con citazioni
- Nessuna deduzione esterna

### Regole assolute

- L'LLM non può generare CELEX autonomamente
- Le fonti normative non devono essere generate dall'LLM
- Le fonti sono stampate solo dal codice Python
- Il context builder (`prompt.py`) deve accettare qualsiasi schema di metadata, senza assumere campi fissi

---

## 10. Supabase RPC

### `search_chunks_multi_type` (attiva)

```sql
search_chunks_multi_type(
  query_embedding vector(1536),
  match_count     int,
  type_filters    text[] default null   -- es. ARRAY['ARTICLE'], ARRAY['ANNEX_CODE']
)
```

- `type_filters = null` → ricerca globale su tutti i tipi
- Il confronto su `unit_type` è case-insensitive (`upper()`)
- Definita in `supabase_rpc.sql` — rideployare se si modifica il file

### Funzioni catalog (per `tools/scan_db.py`)

Definite in `tools/catalog.sql` — deployare **una volta sola**:

- `list_public_tables()` → tabelle pubbliche + stima righe
- `get_table_columns(p_table)` → colonne con tipo e nullability
- `sample_column_values(p_table, p_column, p_limit)` → valori distinti (anti-injection via `format()/%I`)

---

## 11. Scanner automatizzato (`tools/scan_db.py`)

Strumento per validare il registry esistente e profilare nuove tabelle.

### Utilizzo

```bash
python3 tools/scan_db.py              # report completo (testo)
python3 tools/scan_db.py --check-only # solo validazione registry
python3 tools/scan_db.py --json       # output JSON
python3 tools/scan_db.py --json --output report.json
python3 tools/scan_db.py --skip-tables t1,t2
```

### Prerequisito

Deployare `tools/catalog.sql` su Supabase prima del primo utilizzo.

### Cosa fa

**Validazione registry** (per ogni entry esistente):
1. Tabella esiste nel DB
2. `code_field` e `text_field` presenti
3. Dati non vuoti
4. Pattern coverage ≥ 80% sui campioni reali
5. Lookup di verifica con codice campione
6. Consistenza fonte (`celex_field` o `static_celex`)

**Profiling tabelle non in registry**:
- Campiona tutte le colonne utili
- Rileva `code_field` (pattern detection in due fasi: registry patterns → euristiche)
- Rileva `text_field` (hint per nome, fallback lunghezza media)
- Suggerisce `match_mode` (analisi relazioni di prefisso tra campioni)
- Genera **draft entry pronto da incollare** in `registry.py`

### Pattern detection (due fasi)

**Fase 1**: controlla se i campioni matchano un pattern già nel REGISTRY (confidence 0.95)
**Fase 2**: euristiche generali:
- Numerici a lunghezza variabile (≥4 chars di differenza) → prefix
- Numerici a lunghezza fissa → exact
- Alfanumerici a lunghezza fissa → exact
- Altrimenti → nessun pattern, ispezione manuale

---

## 12. Procedura onboarding nuovo DB

Quando si aggiunge una nuova tabella Supabase a CustomsAI:

```
1. Carica la tabella su Supabase (schema public)
   ↓
2. python3 tools/scan_db.py
   → il draft entry viene stampato automaticamente
   ↓
3. Rivedi il draft:
   - pattern corretto per i codici reali?
   - match_mode giusto? (exact = atomico, prefix = gerarchico)
   - source.celex e source.url compilati? (se static_celex)
   - serve display_code_field? (se la tabella ha codici + gerarchia visiva)
   ↓
4. Aggiungi l'entry in REGISTRY (registry.py)
   ↓
5. python3 tools/scan_db.py --check-only  → tutti ✅?
   ↓
6. python3 -m pytest tests/ -v            → tutti passed?
   ↓
7. python3 main.py "tuo codice di test"   → output corretto?
```

**Nessun altro file da modificare oltre a `registry.py`.**

---

## 13. Suite di test

```
tests/
├── test_registry.py   L1 – struttura REGISTRY, pattern dual-use e NC, priorità, case-insensitive
├── test_intent.py     L1 – keyword detection, priorità PROCEDURAL > CLASSIFICATION
├── test_sources.py    L1 – fonti celex_field/static_celex, deduplicazione, output vuoto
├── test_retrieval.py  L2 – lookup_collateral (exact/prefix/display_code), vector_search (mock)
├── test_pipeline.py   L3 – run() end-to-end: 7 scenari (code_specific, NC, fallback,
│                           procedural+code, generic, classification, no results)
└── test_scan_db.py    L1 – detect_pattern, detect_match_mode, _match_registry_patterns,
                            ScanResult.status, render_json/text, _draft_dict
```

Eseguire prima di ogni modifica al registry o al retrieval:

```bash
python3 -m pytest tests/ -v
```

I test di struttura (`test_registry.py`) verificano automaticamente ogni nuova entry del registry.

---

## 14. Logging obbligatorio

Stampare:

- `[routing] intent=… | code=… | db=…`
- `[collateral] {id} | {match_mode} '{code}' → N risultati`
- `[vector] type_filters=… → N risultati`
- `[normalization] embedding query: …`
- risposta finale e fonti

---

## 15. Limiti di contesto

Se il contesto supera `MAX_CONTEXT_CHARS` (default: 30000):

- `llm.generate_answer()` lancia `ValueError`
- `main.py` cattura l'eccezione, stampa messaggio chiaro ed esce
- Soluzione: ridurre `TOP_K` o aumentare `MAX_CONTEXT_CHARS` in `.env`

---

## 16. Cosa è vietato

❌ pattern di codice hardcoded fuori dal registry
❌ branch `if/else` per tipo di codice fuori dal registry
❌ CELEX hardcoded nel codice (solo nel registry per fonti statiche)
❌ LLM che genera CELEX o fonti normative
❌ classificazione automatica
❌ reasoning predittivo
❌ confronto versioni consolidate
❌ logica che assume un numero fisso di DB collaterali
❌ modifica di file diversi da `registry.py` per aggiungere un nuovo DB

---

## 17. Criteri di validazione

La versione è valida se:

✔ `python3 -m pytest tests/ -v` → tutti passed
✔ `python3 tools/scan_db.py --check-only` → tutti ✅
✔ Lookup dual-use funziona (exact match, fonti celex_field)
✔ Lookup nomenclatura NC funziona (prefix match, gerarchia con codici, fonti static_celex)
✔ Vector retrieval su chunks funziona
✔ Routing procedurale con codice combina DB collaterale + chunks
✔ Aggiungere un nuovo DB = solo una entry in `registry.py`
✔ Nessuna hallucination normativa

---

## 18. Filosofia

Prima stabilità.
Poi sofisticazione.

CustomsAI evolve per fasi controllate:

Fase 1 – Retrieval stabile su chunks ✅
Fase 2 – Registry multi-DB + retrieval unificato ✅
Fase 3 – Motore decisionale
Fase 4 – Reasoning normativo avanzato

Ogni fase deve essere validata prima di evolvere.

---

## 19. Changelog

### v4 (corrente)
- Implementato registry-first completo: `registry.py` con `detect_code_from_registry()`
- `retrieval.py` riscritto: rimossi pattern hardcoded, aggiunti `lookup_collateral()` e `vector_search()`
- `main.py` riscritto: routing a due variabili (intent + code), `_print_normative_sources()` gestisce `celex_field` e `static_celex`
- Aggiunto `display_code_field` per visualizzazione codice + gerarchia (es. nomenclature)
- Aggiornato `supabase_rpc.sql`: funzione `search_chunks_multi_type` con `vector(1536)` e `type_filters`
- Aggiunto `tools/scan_db.py`: scanner automatizzato con validazione registry e profiling nuove tabelle
- Aggiunto `tools/catalog.sql`: 3 funzioni RPC Supabase per introspezione
- Suite di test progressiva: 118 test su 6 file (L1 unit, L2 mock, L3 e2e)
- Formalizzata procedura onboarding nuovo DB (7 passi, solo `registry.py` da modificare)
- Fase 2 completata

### v3
- Introdotto registry config-driven per DB collaterali
- Aggiunta tabella `nomenclature` (NC, CELEX 31987R2658, prefix match)
- Formalizzata tabella `dual_use_items` come DB collaterale (exact match)
- Pipeline aggiornata: routing a due variabili (codice + intent)
- Fonti: due tipi (`celex_field`, `static_celex`)
- Vietato hardcoding di pattern e tabelle fuori dal registry

### v2
- Riallineato le regole allo stato reale del sistema
- Eliminato incoerenze della fase 1
- Formalizzato hybrid retrieval
- Formalizzato separazione fonti
- Bloccato logiche dominio-specifiche
- Preparato terreno per fase 2
