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
2. eseguire vector search su Supabase
3. recuperare i chunk più rilevanti
4. passare il contesto all’LLM
5. generare risposta citata
6. indicare chiaramente quando l’informazione non è presente
7. stampare risultato leggibile

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
Embedding domanda
↓
Vector search (Supabase)
↓
Top chunks rilevanti
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

- chunk_text (text)
- article_number (text)
- title (text)
- source_url (text)
- embedding (vector)

NON modificare lo schema.

Il codice NON deve assumere quale normativa sia presente.

---

## 6. Regole per il retrieval

### top_k iniziale
5–15 risultati (configurabile fino a 20)

### ordinamento
per similarità vettoriale

### contesto restituito
- testo chunk
- articolo
- fonte

### contesto
- Il totale dei caratteri del contesto non deve superare `MAX_CONTEXT_CHARS` (es. 30000).
- Se il contesto supera il limite, il flusso si interrompe con messaggio chiaro.

Se non vengono trovati risultati rilevanti:
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
* numero chunk recuperati
* articoli trovati
* lunghezza contesto
* risposta finale

Questo serve per valutare la qualità del retrieval e della risposta.

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
