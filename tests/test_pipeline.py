"""
Level 3 – End-to-end test: pipeline main.run() (tutto mockato)

Testa i 5 scenari di routing della pipeline v3:
  1. CODE_SPECIFIC dual-use   → lookup collaterale, nessun LLM, fonti celex_field
  2. CODE_SPECIFIC NC         → lookup collaterale, nessun LLM, fonti static_celex
  3. CODE_SPECIFIC fallback   → lookup vuoto → vector search → LLM
  4. PROCEDURAL + codice      → lookup collaterale + vector → LLM
  5. GENERIC (nessun codice)  → solo vector → LLM
  6. CLASSIFICATION           → vector con filtro ANNEX_CODE → LLM
  7. Nessun risultato         → messaggio e uscita

Tutti i layer esterni (embeddings, retrieval DB, LLM) sono mockati.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from registry import REGISTRY


# ── Dati di fixture ───────────────────────────────────────────────────────────

DUAL_USE_ENTRY         = next(e for e in REGISTRY if e["id"] == "dual_use")
NOMENCLATURE_ENTRY     = next(e for e in REGISTRY if e["id"] == "nomenclature")
DU_CORRELATIONS_ENTRY  = next(e for e in REGISTRY if e["id"] == "dual_use_correlations")

FAKE_EMBEDDING = [0.0] * 1536

DUAL_USE_CHUNK = {
    "chunk_text": "2B002: Acoustic wave devices...",
    "metadata":   {"code": "2B002", "source_id": "dual_use"},
    "celex_consolidated": "32021R0821",
    "similarity": 1.0,
}

NC_CHUNK = {
    "chunk_text": "8544: Insulated wire and cable...",
    "metadata":   {"code": "8544000000 80", "source_id": "nomenclature"},
    "celex_consolidated": None,
    "similarity": 1.0,
}

ARTICLE_CHUNK = {
    "chunk_text": "Art. 3 – Obblighi dell'esportatore...",
    "metadata":   {"unit_type": "ARTICLE"},
    "celex_consolidated": "32021R0821",
    "similarity": 0.88,
}

MOCK_LLM_ANSWER = "Risposta interpretativa mock."


# ── Helper: mock embeddings ───────────────────────────────────────────────────

def _patch_embedding():
    return patch("embeddings.get_embedding", return_value=FAKE_EMBEDDING)


# ── Scenario 1: CODE_SPECIFIC dual-use ───────────────────────────────────────

def test_code_specific_dual_use_no_llm(capsys):
    """
    Query con codice dual-use → testo diretto, LLM NON chiamato,
    fonti da celex_field.
    """
    with patch("main.detect_code_from_registry", return_value=[(DUAL_USE_ENTRY, "2B002")]), \
         patch("retrieval.lookup_collateral", return_value=[DUAL_USE_CHUNK]), \
         patch("retrieval.vector_search") as mock_vec, \
         patch("llm.generate_answer") as mock_llm:

        from main import run
        run("dimmi il bene 2B002")

    out = capsys.readouterr().out
    assert "TESTO NORMATIVO" in out
    assert "2B002" in out
    assert "32021R0821" in out
    assert "FONTI NORMATIVE" in out
    mock_llm.assert_not_called()
    mock_vec.assert_not_called()


# ── Scenario 2: CODE_SPECIFIC NC (static_celex) ──────────────────────────────

def test_code_specific_nomenclature_static_celex(capsys):
    """
    Query con codice NC → testo diretto, fonti da static_celex (non da chunk).
    """
    with patch("main.detect_code_from_registry", return_value=[(NOMENCLATURE_ENTRY, "8544")]), \
         patch("retrieval.lookup_collateral", return_value=[NC_CHUNK]), \
         patch("llm.generate_answer") as mock_llm:

        from main import run
        run("cosa è la voce 8544")

    out = capsys.readouterr().out
    assert "TESTO NORMATIVO" in out
    assert "8544" in out
    assert "31987R2658" in out       # CELEX statico del registry
    assert "Nomenclatura Combinata" in out
    mock_llm.assert_not_called()


# ── Scenario 2b: multi-match NC (nomenclature=results, correlations=vuoto) ───

def test_code_specific_nc_partial_match_no_du_source(capsys):
    """
    Query con codice NC che matcha due entry (nomenclature + dual_use_correlations).
    nomenclature restituisce risultati, dual_use_correlations restituisce vuoto.
    → La fonte DU NON deve comparire nelle FONTI NORMATIVE.
    """
    NC_MATCH = [(NOMENCLATURE_ENTRY, "8708"), (DU_CORRELATIONS_ENTRY, "8708")]

    def _side_effect(entry, code):
        if entry["id"] == "nomenclature":
            return [NC_CHUNK]
        return []   # dual_use_correlations: 0 risultati

    with patch("main.detect_code_from_registry", return_value=NC_MATCH), \
         patch("retrieval.lookup_collateral", side_effect=_side_effect), \
         patch("llm.generate_answer") as mock_llm:

        from main import run
        run("cosa è la voce 8708")

    out = capsys.readouterr().out
    assert "TESTO NORMATIVO" in out
    assert "31987R2658" in out          # fonte nomenclature presente
    assert "32021R0821" not in out      # fonte DU assente (0 risultati)
    mock_llm.assert_not_called()


# ── Scenario 3: CODE_SPECIFIC con lookup vuoto → fallback vector + LLM ───────

def test_code_specific_fallback_to_vector(capsys):
    """
    Lookup collaterale vuoto → fallback a vector search → LLM interpretativo.
    """
    with patch("main.detect_code_from_registry", return_value=[(DUAL_USE_ENTRY, "9Z999")]), \
         patch("retrieval.lookup_collateral", return_value=[]), \
         _patch_embedding(), \
         patch("retrieval.vector_search", return_value=[ARTICLE_CHUNK]), \
         patch("llm.generate_answer", return_value=MOCK_LLM_ANSWER):

        from main import run
        run("9Z999")

    out = capsys.readouterr().out
    assert MOCK_LLM_ANSWER in out
    assert "RISPOSTA" in out


# ── Scenario 4: PROCEDURAL + codice → collaterale + vector → LLM ─────────────

def test_procedural_with_code(capsys):
    """
    Query procedurale con codice → collaterale + vector search → LLM.
    """
    with patch("main.detect_code_from_registry", return_value=[(DUAL_USE_ENTRY, "2B002")]), \
         patch("retrieval.lookup_collateral", return_value=[DUAL_USE_CHUNK]), \
         _patch_embedding(), \
         patch("retrieval.vector_search", return_value=[ARTICLE_CHUNK]), \
         patch("llm.generate_answer", return_value=MOCK_LLM_ANSWER) as mock_llm:

        from main import run
        run("cosa devo fare per esportare il bene 2B002")

    out = capsys.readouterr().out
    assert MOCK_LLM_ANSWER in out
    mock_llm.assert_called_once()

    # Il contesto passato all'LLM deve includere sia il chunk collaterale che quello vettoriale
    context_arg = mock_llm.call_args[0][1]
    assert "2B002" in context_arg
    assert "Art. 3" in context_arg


# ── Scenario 5: GENERIC (nessun codice) → solo vector → LLM ──────────────────

def test_generic_no_code(capsys):
    """
    Query senza codice → vector search globale → LLM interpretativo.
    """
    with patch("main.detect_code_from_registry", return_value=[]), \
         _patch_embedding(), \
         patch("retrieval.vector_search", return_value=[ARTICLE_CHUNK]), \
         patch("llm.generate_answer", return_value=MOCK_LLM_ANSWER) as mock_llm:

        from main import run
        run("quali sono gli obblighi generali di esportazione")

    out = capsys.readouterr().out
    assert MOCK_LLM_ANSWER in out
    mock_llm.assert_called_once()


# ── Scenario 6: CLASSIFICATION → vector con filtro ANNEX_CODE ────────────────

def test_classification_uses_annex_code_filter(capsys):
    """
    Query di classificazione → vector_search chiamato con type_filters=["ANNEX_CODE"].
    """
    annex_chunk = {
        "chunk_text": "1A001: Acoustic wave devices...",
        "metadata":   {"unit_type": "ANNEX_CODE"},
        "celex_consolidated": "32021R0821",
        "similarity": 0.9,
    }

    with patch("main.detect_code_from_registry", return_value=[]), \
         _patch_embedding(), \
         patch("retrieval.vector_search", return_value=[annex_chunk]) as mock_vec, \
         patch("llm.generate_answer", return_value=MOCK_LLM_ANSWER):

        from main import run
        run("che codice doganale ha questo prodotto?")

    mock_vec.assert_called_once()
    call_kwargs = mock_vec.call_args[1]
    assert call_kwargs.get("type_filters") == ["ANNEX_CODE"]


# ── Scenario 7: nessun risultato → messaggio e sys.exit ──────────────────────

def test_no_results_exits(capsys):
    """
    Se non ci sono risultati, la pipeline stampa messaggio e termina.
    """
    with patch("main.detect_code_from_registry", return_value=[]), \
         _patch_embedding(), \
         patch("retrieval.vector_search", return_value=[]):

        with pytest.raises(SystemExit) as exc_info:
            from main import run
            run("domanda senza risultati")

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Nessun risultato" in out


# ── Robustezza: domanda vuota ─────────────────────────────────────────────────

def test_empty_question_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        from main import run
        run("")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Errore" in out
