# CustomsAI

Motore normativo **AI-first** per interrogare normativa strutturata e sistemi di classificazione doganale.
Il sistema è deterministico, tracciabile e auditabile: nessun routing LLM, nessuna fonte generata dall'AI.

---

## Come funziona

```
Domanda
  │
  ├─ detect_intent()              → code_specific | procedural | classification | generic
  ├─ detect_code_from_registry()  → list[(entry, code)] — tutti i match dal registry
  │
  ├─ CODE_SPECIFIC  → lookup_collateral() → testo diretto (nessun LLM)
  ├─ PROCEDURAL     → lookup_collateral()
  │                    + correlation graph NC→DU (_extract_linked_codes)
  │                    + annex lookup + vector search DU-focused
  │                    → LLM analytical mode + DISCLAIMER
  └─ GENERIC/CLASS  → vector_search() → LLM + DISCLAIMER
       │
       └─ Fonti stampate da Python (solo per entry con risultati)
```

**Registry-first**: ogni DB collaterale è definito in `registry.py`.
Aggiungere un nuovo database = aggiungere una entry al registry, nessun'altra modifica.

---

## Requisiti

- Python 3.11+
- Account OpenAI (API key)
- Progetto Supabase con PostgreSQL + pgvector

---

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Variabili in `.env`:

| Variabile | Obbligatoria | Default | Descrizione |
|-----------|:---:|---------|-------------|
| `OPENAI_API_KEY` | Sì | — | Chiave API OpenAI |
| `SUPABASE_URL` | Sì | — | URL progetto Supabase |
| `SUPABASE_SERVICE_KEY` | Sì | — | Service key Supabase |
| `LLM_MODEL` | No | `gpt-4o-mini` | Modello chat |
| `TOP_K` | No | `15` | Chunk da recuperare |
| `MAX_CONTEXT_CHARS` | No | `30000` | Limite contesto LLM |

---

## Setup Supabase

Esegui `supabase_rpc.sql` nel SQL Editor per creare `search_chunks_multi_type`.
Esegui `tools/catalog.sql` per le funzioni di introspezione usate dallo scanner.

---

## Utilizzo

### Interfaccia web (Streamlit)

```bash
python3 -m streamlit run app.py
```

- Form input con spinner, expander routing (collassato)
- `mode=direct`: testo normativo EUR-Lex formattato in markdown + expander con testo originale monospace
- `mode=llm`: risposta LLM strutturata (analytical o standard) con DISCLAIMER
- Fonti normative con link CELEX cliccabili, storico sessione

### CLI

```bash
python3 main.py "Cosa prevede il codice 2B002?"
python3 main.py "Quali obblighi per esportare voce doganale 8544?"
python3 main.py "Che codice dual-use è 8A001?"
```

### Quattro modalità di risposta

| Intent | Trigger | Comportamento |
|--------|---------|---------------|
| `CODE_SPECIFIC` | Codice + no keyword procedurale | Testo diretto, nessun LLM |
| `PROCEDURAL` | Codice + "esportare", "obblighi", "autorizzazione"… | LLM analytical (articolo per articolo) + DISCLAIMER |
| `CLASSIFICATION` | "classificazione", "voce doganale"… | LLM con filtro ANNEX_CODE |
| `GENERIC` | Default | LLM con ricerca vettoriale globale |

### Scanner automatico

```bash
python3 tools/scan_db.py              # validazione registry + profiling tabelle
python3 tools/scan_db.py --check-only # solo validazione registry
python3 tools/scan_db.py --json       # output JSON
```

---

## Struttura del progetto

```
main.py               # Pipeline: query() → QueryResult, run() (CLI)
                      #   + _format_eurlex_text(), correlation graph helpers
app.py                # Interfaccia web Streamlit
registry.py           # REGISTRY + detect_code_from_registry()
config.py             # Variabili env e costanti
embeddings.py         # Generazione embedding (OpenAI)
retrieval.py          # detect_intent, lookup_collateral, vector_search,
                      #   get_annex_chunks_by_codes
prompt.py             # Context builder + prompts + DISCLAIMER
llm.py                # Chiamata LLM
query_normalizer.py   # Normalizzazione query
supabase_rpc.sql      # Funzione search_chunks_multi_type

tools/
  scan_db.py          # Scanner automatico DB
  catalog.sql         # Funzioni RPC Supabase per introspezione

tests/                # 120 test su 6 file (pytest)
```

---

## DB collaterali registrati

| ID | Tabella | Pattern | Match | Note |
|----|---------|---------|-------|------|
| `dual_use` | `dual_use_items` | `[0-9][A-Z][0-9]{3}` | exact | CELEX dal campo DB |
| `nomenclature` | `nomenclature` | `\d{4,10}` | prefix | Reg. CEE 2658/87 |
| `dual_use_correlations` | `dual_use_correlations` | `\d{4,10}` | prefix | `links_to: dual_use` |

`nomenclature` e `dual_use_correlations` condividono il pattern → **multi-match** per codici NC.
`links_to: "dual_use"` attiva il correlation graph NC→DU nel routing PROCEDURAL.

---

## Test

```bash
python3 -m pytest tests/ -v
```

120 test su 3 livelli: L1 (funzioni pure), L2 (mock Supabase), L3 (pipeline end-to-end).

---

## Aggiungere un nuovo database

1. Carica i dati in Supabase
2. `python3 tools/scan_db.py` → leggi il draft entry generato
3. Aggiungi l'entry in `registry.py` (completa i campi `???` se presenti)
4. `python3 -m pytest tests/ -v` → tutti passed?
5. `python3 main.py "domanda con il nuovo codice"` → output corretto?

---

## Licenza

Uso interno / da definire.
