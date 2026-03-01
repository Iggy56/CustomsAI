# CustomsAI

Motore normativo **AI-first** per interrogare normativa strutturata e sistemi di classificazione doganale.
Il sistema è deterministico, tracciabile e auditabile: nessun routing basato su LLM, nessuna fonte generata dall'AI.

---

## Come funziona

```
Domanda
  │
  ├─ detect_intent()          → codice_diretto | procedurale | classificazione | generico
  ├─ detect_code_from_registry() → (entry, codice) dal registry config-driven
  │
  ├─ CODE_SPECIFIC → lookup_collateral() → output diretto (nessun LLM)
  ├─ PROCEDURAL   → lookup_collateral() + vector_search() → LLM
  └─ GENERIC/CLASS → vector_search() → LLM
       │
       └─ Fonti stampate da Python (deterministicamente)
```

**Registry-first**: ogni DB collaterale è definito in `registry.py`.
Aggiungere un nuovo database significa aggiungere una voce al registry — nessun'altra modifica al codice.

---

## Requisiti

- Python 3.11+
- Account OpenAI (API key)
- Progetto Supabase con PostgreSQL + pgvector

---

## Installazione

```bash
# 1. Crea ambiente virtuale
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux

# 2. Installa dipendenze
pip install -r requirements.txt

# 3. Configura variabili d'ambiente
cp .env.example .env
```

Variabili in `.env`:

| Variabile | Obbligatoria | Default | Descrizione |
|-----------|:---:|---------|-------------|
| `OPENAI_API_KEY` | Sì | — | Chiave API OpenAI |
| `SUPABASE_URL` | Sì | — | URL progetto Supabase |
| `SUPABASE_SERVICE_KEY` | Sì | — | Service key Supabase |
| `LLM_MODEL` | No | `gpt-4o-mini` | Modello chat |
| `TOP_K` | No | `15` | Chunk da recuperare (5–20) |
| `MAX_CONTEXT_CHARS` | No | `30000` | Limite contesto inviato all'LLM |

Il modello di embedding è configurato in `config.py` (`text-embedding-3-small`, vector 1536).

---

## Setup Supabase

### 1. Funzioni RPC principali

Esegui `supabase_rpc.sql` nel SQL Editor di Supabase.
Crea la funzione `search_chunks_multi_type(query_embedding vector(1536), match_count int, type_filters text[])` per la ricerca vettoriale con filtro per tipo di chunk.

### 2. Funzioni di catalogo (per lo scanner)

Esegui `tools/catalog.sql` nel SQL Editor di Supabase.
Crea tre funzioni di introspezione:
- `list_public_tables()` — tabelle pubbliche con stima righe
- `get_table_columns(p_table)` — colonne con tipo e nullability
- `sample_column_values(p_table, p_col, p_limit)` — valori distinti da una colonna

---

## Utilizzo

### Query normativa

```bash
python3 main.py "Cosa prevede il codice 2B002?"
python3 main.py "Quali obblighi per esportare apparecchiature laser?"
python3 main.py "Voce doganale 8544"
```

Il rilevamento del codice è **case-insensitive** (2b002 → normalizzato 2B002).

**Quattro modalità di risposta:**

| Intent | Trigger | Comportamento |
|--------|---------|---------------|
| `CODE_SPECIFIC` | Codice nel registry + nessun trigger procedurale | Trascrizione diretta, nessun LLM |
| `PROCEDURAL` | Parole chiave: esportare, obblighi, autorizzazione… | LLM con contesto collaterale + vettoriale |
| `CLASSIFICATION` | Parole chiave: classificazione, voce doganale… | LLM con filtro `ANNEX_CODE` |
| `GENERIC` | Default | LLM con ricerca vettoriale |

### Scanner automatico

Lo scanner analizza il database Supabase, valida le entry del registry e profila le tabelle non ancora registrate.

```bash
# Scan completo con report testuale
python3 tools/scan_db.py

# Report JSON (per integrazione/automazione)
python3 tools/scan_db.py --json

# Salva report su file
python3 tools/scan_db.py --output report.json --json

# Solo validazione registry (no profiling nuove tabelle)
python3 tools/scan_db.py --check-only

# Escludi tabelle
python3 tools/scan_db.py --skip-tables log_table,temp_data
```

Il report include:
- Validazione di ogni entry del registry (6 check: tabella esistente, campi presenti, dati, copertura pattern ≥80%, lookup campione, coerenza source)
- Profiling delle tabelle non registrate con rilevamento automatico del pattern e draft entry pronto per `registry.py`

---

## Struttura del progetto

```
registry.py           # Config-driven: REGISTRY list + detect_code_from_registry()
main.py               # Pipeline orchestratore
config.py             # Variabili env e costanti
embeddings.py         # Generazione embedding (OpenAI)
retrieval.py          # Retrieval: detect_intent, lookup_collateral, vector_search
prompt.py             # Context builder + prompt LLM
llm.py                # Chiamata LLM
query_normalizer.py   # Normalizzazione query

supabase_rpc.sql      # Funzione search_chunks_multi_type per Supabase

tools/
  scan_db.py          # Scanner automatico DB
  catalog.sql         # Funzioni RPC di introspezione per Supabase

tests/
  test_registry.py    # Unit test registry.py
  test_intent.py      # Unit test detect_intent()
  test_sources.py     # Unit test _print_normative_sources()
  test_retrieval.py   # Test retrieval con mock Supabase
  test_pipeline.py    # Test pipeline end-to-end con mock
  test_scan_db.py     # Unit test scan_db.py (funzioni pure)
```

---

## DB collaterali registrati

| ID | Tabella | Pattern | Fonte |
|----|---------|---------|-------|
| `dual_use` | `dual_use_items` | `[0-9][A-Z][0-9]{3}` (es. 2B002) | CELEX dal campo DB |
| `nomenclature` | `nomenclature` | `\d{4,10}` (es. 8544) | Reg. CEE 2658/87 (statico) |

Per aggiungere un nuovo DB: aggiungi una voce a `REGISTRY` in `registry.py`. Nessun'altra modifica necessaria.

---

## Test

```bash
python3 -m pytest tests/ -v
```

118 test distribuiti su 3 livelli:
- **L1** — funzioni pure, nessuna dipendenza esterna
- **L2** — mock Supabase client
- **L3** — pipeline end-to-end con mock completo

---

## Aggiungere un nuovo database

1. Carica i dati in Supabase (tabella nello schema `public`)
2. Esegui `python3 tools/scan_db.py` per profilare la tabella
3. Copia il draft entry generato dallo scanner
4. Incollalo in `REGISTRY` in `registry.py` e completa i campi `???`
5. Esegui i test: `python3 -m pytest tests/ -v`
6. Verifica live: `python3 main.py "domanda con il nuovo codice"`

---

## Licenza

Uso interno / da definire.
