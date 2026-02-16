# CustomsAI

Pipeline **RAG** (Retrieval-Augmented Generation) per interrogare normativa strutturata: domanda → embedding → ricerca vettoriale su Supabase → risposta dell’LLM basata solo sul contesto recuperato, con citazioni di articoli e fonti.

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

- La tabella **`chunks`** deve avere almeno: `text`, `article_ref`, `title`, `source_url`, `embedding` (tipo `vector`).
- La ricerca per similarità avviene tramite la funzione RPC **`search_chunks`**. Esegui lo script SQL nel progetto:
  - Apri **Supabase → SQL Editor** e lancia il contenuto di `supabase_rpc.sql`.

**Dimensioni del vettore:**  
Lo script prevede `vector(3072)` per `text-embedding-3-large`. Se usi **`text-embedding-3-small`** (predefinito del progetto), la dimensione è **1536**: adatta in `supabase_rpc.sql` e nella definizione della colonna `embedding` a `vector(1536)`.

---

## Utilizzo

Da terminale, dalla root del progetto:

```bash
python3 main.py "La tua domanda sulla normativa"
```

Esempio:

```bash
python3 main.py "Quali sono gli obblighi per l'importazione?"
```

In output vedrai: domanda, numero di chunk recuperati, articoli trovati, lunghezza del contesto e la risposta generata (con eventuali citazioni). Se l’informazione non è nel database, il sistema lo segnala invece di inventare risposte.

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
config.py      # Caricamento .env e costanti (modelli, TOP_K, limiti)
embeddings.py  # Generazione embedding della domanda (OpenAI)
retrieval.py   # Ricerca vettoriale su Supabase (RPC search_chunks)
prompt.py      # Costruzione messaggi per l’LLM (contesto + istruzioni)
llm.py         # Chiamata all’LLM per la risposta citata
main.py        # Pipeline: domanda → embedding → retrieval → LLM → output
supabase_rpc.sql  # Script per creare la funzione search_chunks in Supabase
```

---

## Licenza

Uso interno / da definire.
