# .cursorrules

## 1. Missione di questa fase

Costruire una **prima versione ultra-base funzionante** del sistema RAG per interrogare normativa strutturata.

Il sistema deve:

- ricevere una domanda
- cercare i chunk rilevanti nel database vettoriale
- generare una risposta usando SOLO il contesto
- citare articoli e fonti
- gestire correttamente i casi in cui l’informazione non è presente

⚠️ Il sistema deve essere **generico**, non costruito su una normativa specifica.

Anche se attualmente il database contiene una sola normativa, l’app NON deve:

- assumere quale normativa sia presente
- fare riferimento a un regolamento specifico
- adattare il comportamento a un dominio specifico

Il sistema deve funzionare anche quando:
- l’informazione non esiste nel database
- la domanda è fuori ambito

Questa fase serve a VALIDARE il funzionamento, non a perfezionare il prodotto.

---

## 2. Obiettivi funzionali minimi

Il sistema deve:

1. generare embedding della domanda
2. **retrieval ibrido**: se la domanda contiene un codice normativo (es. 2B002), tentare prima il retrieval strutturato per `metadata.code`; altrimenti (o se nessun match) usare la vector search tramite RPC
3. recuperare i chunk più rilevanti (con text, metadata, title, source_url, similarity)
4. costruire il contesto con header metadata (TYPE, CELEX, Art, Code, Recital, ecc.) quando presenti
5. passare il contesto all’LLM
6. generare risposta citata
7. indicare chiaramente quando l’informazione non è presente
8. stampare risultato leggibile (inclusi type, celex, article/code, similarity in debug)

Se uno di questi passaggi fallisce → il sistema non è pronto.

---

## 3. Stack tecnico autorizzato

### Linguaggio
- Python 3.11+

### Librerie
- openai
- supabase
- python-dotenv

### Database
- Supabase PostgreSQL + pgvector

### Modelli
- Embeddings: `text-embedding-3-small` (predefinito; usare `text-embedding-3-large` solo se l’account OpenAI lo supporta)
- LLM: GPT (configurabile via `LLM_MODEL` in .env)
- Limite contesto: `MAX_CONTEXT_CHARS` in .env (default 30000), per evitare errori con contesti lunghi

NON introdurre librerie aggiuntive.

### Esecuzione
- Da terminale: `python3 main.py "domanda"` (su macOS usare `python3`).
- Variabili obbligatorie in .env: `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
- Opzionali: `LLM_MODEL`, `TOP_K`, `MAX_CONTEXT_CHARS`.

---

## 4. Architettura obbligatoria

Pipeline:

```
User Question
↓
Embedding domanda (sempre, per fallback)
↓
Codice normativo in domanda? (regex case-insensitive, es. 2B002 / 2b002)
   Sì → Retrieval strutturato (metadata.code) su tabella chunks
        → Se risultati: usa quelli (similarity=1.0)
        → Se nessuno: fallback a vector search
   No  → Vector search (RPC search_chunks)
↓
Top chunks (text, metadata, title, source_url, similarity)
↓
Context builder con header metadata (TYPE, CELEX, Art, Code, Recital…)
↓
LLM con contesto
↓
Risposta citata o messaggio di assenza informazioni
```

Separazione file:

```

config.py
embeddings.py
retrieval.py
prompt.py
llm.py
main.py

```

---

## 5. Schema dati atteso

Tabella Supabase: `chunks`

Campi utilizzati:

- `text` (text) – contenuto del chunk
- `metadata` (jsonb) – struttura tipo: type, celex, article, paragraph, letter, annex, code (a seconda della normativa)
- `title` (text)
- `source_url` (text)
- `embedding` (vector) – per la vector search

L’app mappa in `ChunkRow`: chunk_text, metadata (dict), title, source_url, similarity.

NON modificare lo schema del database.

Il codice NON deve assumere quale normativa sia presente.

---

## 6. Regole per il retrieval

### Retrieval ibrido
- **Codice normativo in domanda** (pattern `[0-9][A-Za-z][0-9]{3}`, case-insensitive, es. 2B002, 2b002, "codice 2b002", "(2b002)"): il codice rilevato viene normalizzato in maiuscolo per il lookup. Prima retrieval strutturato su `metadata->>'code'` (select su tabella, senza RPC). Se ci sono risultati, restituirli (similarity=1.0). Altrimenti fallback a vector search.
- **Nessun codice o nessun match strutturato**: usare RPC `search_chunks` (vector search) come prima.

### top_k
5–15 risultati (configurabile fino a 20), stesso limite per strutturato e vettoriale.

### ordinamento
- Strutturato: ordine naturale della select.
- Vector search: per similarità vettoriale.

### formato restituito (sempre uguale)
- chunk_text, metadata (dict), title, source_url, similarity (float o 1.0 per strutturato)

### contesto per LLM
- Header da metadata quando presenti (es. `[TYPE: article | CELEX: ... | Art: 12 | Code: 2B002]`), poi testo chunk e fonte.
- Il totale caratteri non deve superare `MAX_CONTEXT_CHARS` (es. 30000). Se supera, messaggio chiaro e stop.

Se non vengono trovati risultati:
→ il sistema deve informare l’utente.

---

## 7. Prompt LLM obbligatorio

Il modello DEVE:

- usare solo il contesto fornito
- non inventare informazioni
- non usare conoscenza esterna
- citare articoli quando disponibili
- dichiarare quando l’informazione non è presente

### Template

```

Usa esclusivamente le informazioni presenti nel CONTESTO.

Se la risposta non è presente, scrivi:
"Informazione non presente nel contesto fornito."

Fornisci:

1. Risposta sintetica
2. Articoli rilevanti (se presenti)
3. Ambito di applicazione (se disponibile)
4. Note o eccezioni (se presenti)

Cita sempre gli articoli quando disponibili.

````

---

## 8. Regole per la generazione della risposta

La risposta deve:

- essere sintetica e chiara
- citare articoli quando disponibili
- indicare se l’informazione è incompleta
- dichiarare quando non è presente nel contesto

NON deve:

- interpretare oltre il contesto
- fare deduzioni legali
- usare conoscenza esterna
- assumere quale normativa sia interrogata

---

## 9. Regole di qualità del codice

### Obbligatorio

- codice semplice e leggibile
- funzioni brevi e modulari
- type hints dove utili
- gestione errori API e rete
- output chiaro per debugging
- in `main.py` le eccezioni OpenAI (`APIError`, `APIConnectionError`) devono essere importate (es. da `openai`) dove vengono usate nell’except

### Commenti

Il codice deve essere commentato per spiegare:

- cosa fa ogni funzione
- perché viene eseguita
- cosa può essere migliorato in futuro

Esempio:

```python
# Generate embedding for the user question.
# This vector enables semantic search in the vector database.
````

---

## 10. Linee guida per la scrittura del codice

### Preferire

✔ chiarezza > astrazione
✔ esplicito > implicito
✔ debug facile > eleganza

### Evitare

❌ classi inutili
❌ design pattern complessi
❌ ottimizzazioni premature
❌ funzioni troppo generiche

---

## 11. Logging e debug

Stampare:

* domanda utente
* se rilevato codice normativo: `[hybrid] detected normative code: X`
* se usato retrieval strutturato: `[structured retrieval] code=X -> N result(s)` oppure `no match, fallback to vector search`
* per ogni chunk (debug): type, celex, article/code, similarity
* numero chunk recuperati
* articoli/code trovati (da metadata)
* lunghezza contesto
* risposta finale

Serve per valutare la qualità del retrieval (ibrido vs vettoriale) e della risposta.

---

## 12. Cosa NON sviluppare ora

❌ interfaccia grafica
❌ caching avanzato
❌ ottimizzazione performance
❌ multi-utente
❌ sicurezza avanzata
❌ orchestrazioni complesse
❌ classificazione automatica
❌ interpretazione normativa
❌ logica specifica per una normativa
❌ filtri hardcoded per dominio specifico

Focus: validazione funzionale generica.

---

## 13. Error handling obbligatorio

Gestire:

* nessun risultato retrieval
* errori API OpenAI
* errori connessione Supabase
* contesto troppo lungo (rispetto a `MAX_CONTEXT_CHARS`; aumentare il valore in .env o ridurre TOP_K se necessario)

In caso di errore:
stampare messaggio chiaro e interrompere il flusso.

---

## 14. Protocollo di incertezza

Se il modello o il codice non è sicuro:

1. NON inventare comportamenti.
2. NON introdurre logiche specifiche per normative.
3. NON modificare architettura.
4. Preferire soluzione semplice e sicura.
5. Segnalare dubbi nei commenti.
6. Fermare il flusso se i dati non sono affidabili.

---

## 15. Criteri per considerare la versione riuscita

La versione è valida se:

✔ recupera chunk rilevanti
✔ cita articoli corretti quando disponibili
✔ non inventa informazioni
✔ segnala quando i dati non sono presenti
✔ funziona anche fuori ambito
✔ produce risposte utili e verificabili

---

## 16. Filosofia di sviluppo

Questo codice non deve essere perfetto.
Deve essere:

* verificabile
* comprensibile
* migliorabile
* solido nelle basi

Prima validiamo il funzionamento.
Poi miglioreremo precisione e UX.

---
