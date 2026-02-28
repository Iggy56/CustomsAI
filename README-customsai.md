# CustomsAI

Pipeline **RAG** (Retrieval-Augmented Generation) per interrogare normativa strutturata con **retrieval ibrido** (strutturato + semantico):

- Se la domanda contiene un **codice normativo** (es. 2B002 o 2b002; rilevamento **case-insensitive**, normalizzato in maiuscolo per il DB), il sistema tenta prima il retrieval strutturato per `metadata.code` sulla tabella `chunks`.
- In assenza di codice o di risultati strutturati, viene usata la **ricerca vettoriale** (embedding + RPC su Supabase).

Il contesto inviato all’LLM include **metadata** (tipo, CELEX, articolo, code, recital, ecc.) per citazioni precise. La risposta è basata **solo** sul contesto recuperato.

**Due modalità di risposta LLM:** (1) **Codice diretto**: quando la domanda contiene un codice e il retrieval è strutturato, l’LLM riproduce fedelmente il testo normativo (niente sintesi né interpretazione). (2) **Domanda interpretativa**: per domande concettuali, risposta strutturata con sintesi e citazioni.

Il sistema è **generico**: non dipende da una normativa specifica e funziona su qualsiasi contenuto normativo memorizzato in chunk nel database.

---

## Requisiti

- **Python 3.11+**
- Account **OpenAI** (API key)
- Progetto **Supabase** con PostgreSQL e pgvector

---

## Installazione

1. Clona o scarica il progetto e entra nella cartella.

2. Crea un ambiente virtuale (consigliato):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   ```

3. Installa le dipendenze:
   ```bash
   pip install -r requirements.txt
   ```

4. Configura le variabili d’ambiente. Copia `.env.example` in `.env` e compila:
   ```bash
   cp .env.example .env
   ```
   In `.env` imposta almeno:
   - `OPENAI_API_KEY` – chiave API OpenAI
   - `SUPABASE_URL` – URL del progetto Supabase
   - `SUPABASE_SERVICE_KEY` – service key Supabase (necessaria per la RPC)

   Opzionali: `LLM_MODEL`, `TOP_K`, `MAX_CONTEXT_CHARS` (vedi sotto).

---

## Supabase

### Tabella e funzione RPC

- La tabella **`chunks`** deve avere: `text`, `metadata` (jsonb), `title`, `source_url`, `embedding` (tipo `vector`).  
  In `metadata` possono essere presenti, a seconda della normativa: `type`, `celex`, `article`, `paragraph`, `letter`, `annex`, `code`, ecc.
- La **ricerca vettoriale** usa la funzione RPC **`search_chunks`**, che restituisce `text`, `metadata`, `title`, `source_url`, `similarity`.  
  Esegui lo script SQL nel progetto: apri **Supabase → SQL Editor** e lancia il contenuto di `supabase_rpc.sql`.
- Il **retrieval strutturato** (quando la domanda contiene un codice tipo 2B002 o 2b002; rilevamento case-insensitive) interroga direttamente la tabella con filtro `metadata->>'code' = codice` (codice normalizzato in maiuscolo); non usa la RPC.

**Dimensioni del vettore:**  
Lo script prevede `vector(3072)` per `text-embedding-3-large`. Se usi **`text-embedding-3-small`** (predefinito), la dimensione è **1536**: adatta in `supabase_rpc.sql` e nella definizione della colonna `embedding` a `vector(1536)`.

---

## Utilizzo

Da terminale, dalla root del progetto:

```bash
python3 main.py "La tua domanda sulla normativa"
```

Esempi:

```bash
python3 main.py "Quali sono gli obblighi per l'importazione?"
python3 main.py "Cosa prevede il codice 2B002?"
python3 main.py "cosa dice il codice 2b002?"
```

Il rilevamento del codice è **case-insensitive** (2b002 e 2B002 sono entrambi riconosciuti e normalizzati in maiuscolo). Con una domanda che contiene un codice il sistema esegue il retrieval strutturato su `metadata.code` e usa la modalità **codice diretto**: l’LLM trascrive il testo normativo senza sintetizzare. Per domande generiche (es. "quali obblighi…") si usa la modalità **interpretativa** (sintesi e citazioni). In output: domanda, codice rilevato (se presente), tipo di retrieval, chunk con type/celex/article/code e similarity, lunghezza contesto e risposta. Se l’informazione non è nel database, il sistema lo segnala invece di inventare risposte.

---

## Configurazione (.env)

| Variabile | Obbligatoria | Default | Descrizione |
|-----------|--------------|---------|-------------|
| `OPENAI_API_KEY` | Sì | — | Chiave API OpenAI |
| `SUPABASE_URL` | Sì | — | URL progetto Supabase |
| `SUPABASE_SERVICE_KEY` | Sì | — | Service key Supabase |
| `LLM_MODEL` | No | `gpt-4o-mini` | Modello chat (es. `gpt-4o`) |
| `TOP_K` | No | `15` | Numero di chunk da recuperare (5–20) |
| `MAX_CONTEXT_CHARS` | No | `30000` | Limite caratteri del contesto inviato all’LLM |

Il modello per gli **embedding** è impostato in `config.py` (`text-embedding-3-small`).

---

## Struttura del progetto

```
config.py         # Caricamento .env e costanti (modelli, TOP_K, limiti)
embeddings.py     # Generazione embedding della domanda (OpenAI)
retrieval.py      # Retrieval ibrido: rilevamento codice normativo, structured by metadata.code o vector search (RPC search_chunks)
prompt.py         # Contesto con header metadata; due prompt: "codice diretto" (trascrizione fedele) e interpretativo (sintesi)
llm.py            # Chiamata all’LLM per la risposta citata
main.py           # Pipeline: domanda → embedding → retrieval ibrido → context → LLM → output
supabase_rpc.sql  # Script per la funzione search_chunks (vector search) in Supabase
```

---

## Licenza

Uso interno / da definire.
