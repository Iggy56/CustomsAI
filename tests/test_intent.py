"""
Level 1 – Unit test: intent detection (retrieval.detect_intent)

Testa che l'intent sia rilevato correttamente dalle keyword della query.
Nessuna dipendenza esterna.
"""

import pytest
from retrieval import detect_intent, Intent


# ── PROCEDURAL ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "cosa devo fare per esportare questo bene",
    "quali sono gli obblighi per l'esportazione",
    "ho bisogno di una autorizzazione?",
    "qual è la procedura per inviare all'estero",
    "devo esportare il prodotto",
])
def test_procedural_intent(query):
    assert detect_intent(query) == Intent.PROCEDURAL

@pytest.mark.parametrize("keyword", [
    "esportare", "obblighi", "cosa devo fare", "procedura", "autorizzazione",
])
def test_procedural_keywords_individually(keyword):
    assert detect_intent(f"domanda con {keyword}") == Intent.PROCEDURAL


# ── CLASSIFICATION ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "che codice NC ha questo prodotto?",
    "qual è la voce doganale del cavo",
    "come funziona la classificazione doganale",
])
def test_classification_intent(query):
    assert detect_intent(query) == Intent.CLASSIFICATION

@pytest.mark.parametrize("keyword", [
    "che codice", "voce doganale", "classificazione",
])
def test_classification_keywords_individually(keyword):
    assert detect_intent(f"domanda su {keyword}") == Intent.CLASSIFICATION


# ── GENERIC ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "descrivi il regolamento dual-use",
    "cosa dice l'articolo 3",
    "elenco dei beni soggetti a controllo",
    "",
    "2B002",   # solo codice, nessuna keyword procedurale o classificazione
])
def test_generic_intent(query):
    assert detect_intent(query) == Intent.GENERIC


# ── Priorità: PROCEDURAL batte CLASSIFICATION ────────────────────────────────

def test_procedural_beats_classification():
    """Se la query ha sia keyword classificazione che procedurale, vince PROCEDURAL."""
    query = "che codice devo usare per esportare?"
    assert detect_intent(query) == Intent.PROCEDURAL
