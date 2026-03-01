# .cursorrules – CustomsAI v2

## 1. Missione attuale del sistema

CustomsAI non è più un RAG sperimentale.

È un **motore normativo AI-first** per interrogare normativa strutturata,
con comportamento deterministico, tracciabile e verificabile.

Obiettivo:

- ricevere una domanda
- determinare il tipo di interrogazione
- eseguire retrieval strutturato o vettoriale
- generare risposta SOLO dal contesto
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
- Nessuna generazione di fonti da parte dell’LLM
- Nessuna conoscenza esterna

### Database-first

Il database è la fonte di verità normativa.

Se un CELEX non è nei chunk → non può essere citato.

---

## 3. Pipeline obbligatoria

```

User Question
↓
Embedding domanda (sempre)
↓
Hybrid Retrieval
├─ Codice normativo rilevato?
│      ├─ Retrieval strutturato (metadata.code)
│      └─ Se nessun match → fallback vector
└─ Nessun codice → Vector search (RPC)
↓
Top chunks (text, metadata, title, source_url, similarity)
↓
Context builder con header metadata
↓
LLM (modalità interpretativa o codice diretto)
↓
Risposta
↓
Fonti normative stampate deterministicamente da Python

```

---

## 4. Regole di retrieval

### 4.1 Retrieval ibrido

Pattern codice:
```

[0-9][A-Za-z][0-9]{3}

```

Se presente:

- tentare retrieval strutturato su `metadata->>'code'`
- similarity = 1.0
- se nessun risultato → fallback vector search

Altrimenti:

- usare RPC `search_chunks`

### 4.2 Nessun filtro per dominio

È vietato:

- filtrare per CELEX
- filtrare per type (article-first)
- adattare retrieval a normativa specifica

Il sistema deve funzionare con qualsiasi normativa caricata.

---

## 5. Regole per il prompt LLM

Due modalità:

### Modalità Codice Diretto
- Riproduzione fedele del testo
- Nessuna sintesi
- Nessuna interpretazione
- Nessuna sezione aggiuntiva

### Modalità Interpretativa
- Sintesi strutturata
- Citazione articoli quando presenti
- Nessuna deduzione esterna

### Regole assolute

- L’LLM non può generare CELEX autonomamente
- Le fonti normative non devono essere generate dall’LLM
- Le fonti sono stampate solo dal codice Python

---

## 6. Fonti normative

Le fonti devono essere:

- Derivate esclusivamente da `celex_consolidated` nei chunk
- Stampate deterministicamente da Python
- Non generate dal modello

Formato:

```

---

FONTI NORMATIVE

CELEX: XXXXX
[https://eur-lex.europa.eu/](https://eur-lex.europa.eu/)...
-----------------------------------------------------------

```

---

## 7. Logging obbligatorio

Stampare:

- domanda utente
- codice rilevato (se presente)
- numero risultati strutturati
- numero risultati vettoriali
- per ogni chunk: type, celex, article/code, similarity
- lunghezza contesto
- risposta finale

---

## 8. Limiti di contesto

Se il contesto supera `MAX_CONTEXT_CHARS`:

- interrompere flusso
- stampare messaggio chiaro
- suggerire aumento valore o riduzione TOP_K

---

## 9. Cosa è vietato sviluppare in questa fase

❌ logica dominio-specifica  
❌ routing per normativa specifica  
❌ CELEX hardcoded  
❌ classificazione automatica  
❌ reasoning predittivo  
❌ confronto versioni consolidate  
❌ multi-database logic  

Focus: stabilità retrieval + correttezza normativa.

---

## 10. Criteri di validazione

La versione è valida se:

✔ Hybrid retrieval funziona  
✔ Vector retrieval funziona  
✔ Nessuna hallucination normativa  
✔ Fonti sempre corrette  
✔ Funziona fuori ambito  
✔ Codice leggibile e modulare  

---

## 11. Filosofia

Prima stabilità.
Poi sofisticazione.

CustomsAI evolve per fasi controllate:

Fase 1 – Retrieval stabile  
Fase 2 – Miglioramento semantico  
Fase 3 – Motore decisionale  
Fase 4 – Reasoning normativo avanzato  

Ogni fase deve essere validata prima di evolvere.
```

---

# 🎯 Cosa abbiamo fatto

* Riallineato le regole allo stato reale del sistema
* Eliminato incoerenze della fase 1
* Formalizzato hybrid retrieval
* Formalizzato separazione fonti
* Bloccato logiche dominio-specifiche
* Preparato terreno per fase 2

---