"""
Level 2 – Integration test: retrieval.py (Supabase mockato)

Testa lookup_collateral() e vector_search() senza chiamate reali al DB.
Usa unittest.mock per simulare il client Supabase.
"""

import pytest
from unittest.mock import MagicMock, patch

from retrieval import lookup_collateral, vector_search


# ── Fixture: entry registry ───────────────────────────────────────────────────

@pytest.fixture
def dual_use_entry():
    return {
        "id":         "dual_use",
        "table":      "dual_use_items",
        "code_field": "code",
        "text_field": "description",
        "match_mode": "exact",
        "source":     {"type": "celex_field"},
    }


@pytest.fixture
def nomenclature_entry():
    return {
        "id":         "nomenclature",
        "table":      "nomenclature",
        "code_field": "goods_code",
        "text_field": "description",
        "match_mode": "prefix",
        "source":     {
            "type":  "static_celex",
            "celex": "31987R2658",
            "url":   "https://eur-lex.europa.eu/...",
        },
    }


# ── Helpers per costruire mock client ─────────────────────────────────────────

def _mock_client_exact(rows: list[dict]) -> MagicMock:
    """Mock per query con .eq() (exact match)."""
    mock = MagicMock()
    (mock.table.return_value
         .select.return_value
         .eq.return_value
         .limit.return_value
         .execute.return_value
         .data) = rows
    return mock


def _mock_client_prefix(rows: list[dict]) -> MagicMock:
    """Mock per query con .like() (prefix match)."""
    mock = MagicMock()
    (mock.table.return_value
         .select.return_value
         .like.return_value
         .limit.return_value
         .execute.return_value
         .data) = rows
    return mock


def _mock_client_rpc(rows: list[dict]) -> MagicMock:
    """Mock per RPC (vector search)."""
    mock = MagicMock()
    mock.rpc.return_value.execute.return_value.data = rows
    return mock


# ── lookup_collateral – exact match ──────────────────────────────────────────

@patch("retrieval._get_client")
def test_lookup_collateral_exact_returns_results(mock_get_client, dual_use_entry):
    rows = [{"code": "2B002", "description": "Laser systems", "celex_consolidated": "32021R0821"}]
    mock_get_client.return_value = _mock_client_exact(rows)

    results = lookup_collateral(dual_use_entry, "2B002")

    assert len(results) == 1
    assert results[0]["chunk_text"] == "Laser systems"
    assert results[0]["similarity"] == 1.0
    assert results[0]["celex_consolidated"] == "32021R0821"


@patch("retrieval._get_client")
def test_lookup_collateral_exact_empty(mock_get_client, dual_use_entry):
    mock_get_client.return_value = _mock_client_exact([])

    results = lookup_collateral(dual_use_entry, "9Z999")

    assert results == []


@patch("retrieval._get_client")
def test_lookup_collateral_exact_uses_eq(mock_get_client, dual_use_entry):
    """Verifica che exact match usi .eq() e non .like()."""
    mock_get_client.return_value = _mock_client_exact([])

    lookup_collateral(dual_use_entry, "2B002")

    mock_client = mock_get_client.return_value
    mock_client.table.return_value.select.return_value.eq.assert_called_once_with("code", "2B002")


# ── lookup_collateral – prefix match ─────────────────────────────────────────

@patch("retrieval._get_client")
def test_lookup_collateral_prefix_returns_hierarchy(mock_get_client, nomenclature_entry):
    rows = [
        {"goods_code": "8544000000 80", "description": "Insulated wire",   "celex_consolidated": None},
        {"goods_code": "8544200000 10", "description": "Coaxial cable",    "celex_consolidated": None},
        {"goods_code": "8544300000 10", "description": "Ignition wiring",  "celex_consolidated": None},
    ]
    mock_get_client.return_value = _mock_client_prefix(rows)

    results = lookup_collateral(nomenclature_entry, "8544")

    assert len(results) == 3
    assert results[0]["chunk_text"] == "Insulated wire"
    assert results[0]["celex_consolidated"] is None  # static_celex, non celex_field


@patch("retrieval._get_client")
def test_lookup_collateral_prefix_uses_like(mock_get_client, nomenclature_entry):
    """Verifica che prefix match usi .like() con pattern '{code}%'."""
    mock_get_client.return_value = _mock_client_prefix([])

    lookup_collateral(nomenclature_entry, "8544")

    mock_client = mock_get_client.return_value
    mock_client.table.return_value.select.return_value.like.assert_called_once_with(
        "goods_code", "8544%"
    )


# ── lookup_collateral – match_mode non valido ─────────────────────────────────

@patch("retrieval._get_client")
def test_lookup_collateral_invalid_match_mode(mock_get_client):
    bad_entry = {
        "id": "bad", "table": "t", "code_field": "c", "text_field": "t",
        "match_mode": "fuzzy",  # non supportato
        "source": {"type": "celex_field"},
    }
    mock_get_client.return_value = MagicMock()

    with pytest.raises(ValueError, match="match_mode non supportato"):
        lookup_collateral(bad_entry, "XXX")


# ── lookup_collateral – metadata ──────────────────────────────────────────────

@patch("retrieval._get_client")
def test_lookup_collateral_display_code_field_formatting(mock_get_client):
    """
    Con display_code_field, chunk_text deve includere il codice numerico
    e l'indentazione gerarchica basata su 'indent'.
    """
    entry_with_display = {
        "id":                "nomenclature",
        "table":             "nomenclature",
        "code_field":        "goods_code",
        "text_field":        "description",
        "match_mode":        "prefix",
        "display_code_field": "goods_code",
        "source":            {"type": "static_celex", "celex": "31987R2658"},
    }
    rows = [
        {"goods_code": "8544000000 80", "description": "Insulated wire",  "indent": None},
        {"goods_code": "8544200000 10", "description": "Coaxial cable",   "indent": "-"},
        {"goods_code": "8544300000 10", "description": "Ignition wiring", "indent": "- -"},
    ]
    mock_get_client.return_value = _mock_client_prefix(rows)

    results = lookup_collateral(entry_with_display, "8544")

    # Voce principale: nessuna indentazione
    assert results[0]["chunk_text"].startswith("8544000000")
    assert "Insulated wire" in results[0]["chunk_text"]

    # Primo livello: 2 spazi di indentazione
    assert results[1]["chunk_text"].startswith("  8544200000")
    assert "Coaxial cable" in results[1]["chunk_text"]

    # Secondo livello: 4 spazi di indentazione
    assert results[2]["chunk_text"].startswith("    8544300000")
    assert "Ignition wiring" in results[2]["chunk_text"]


@patch("retrieval._get_client")
def test_lookup_collateral_display_code_strips_suffix(mock_get_client):
    """Il suffisso ' 80' del goods_code deve essere rimosso dalla visualizzazione."""
    entry_with_display = {
        "id":                "nomenclature",
        "table":             "nomenclature",
        "code_field":        "goods_code",
        "text_field":        "description",
        "match_mode":        "prefix",
        "display_code_field": "goods_code",
        "source":            {"type": "static_celex", "celex": "31987R2658"},
    }
    rows = [{"goods_code": "8544000000 80", "description": "Insulated wire", "indent": None}]
    mock_get_client.return_value = _mock_client_prefix(rows)

    results = lookup_collateral(entry_with_display, "8544")

    assert "8544000000 80" not in results[0]["chunk_text"]
    assert "8544000000" in results[0]["chunk_text"]


@patch("retrieval._get_client")
def test_lookup_collateral_metadata_contains_code(mock_get_client, dual_use_entry):
    rows = [{"code": "1A001", "description": "Acoustic wave devices", "celex_consolidated": "32021R0821"}]
    mock_get_client.return_value = _mock_client_exact(rows)

    results = lookup_collateral(dual_use_entry, "1A001")

    assert results[0]["metadata"]["code"] == "1A001"
    assert results[0]["metadata"]["source_id"] == "dual_use"


# ── vector_search ─────────────────────────────────────────────────────────────

FAKE_EMBEDDING = [0.1] * 1536


@patch("retrieval._get_client")
def test_vector_search_returns_results(mock_get_client):
    rows = [
        {"text": "Art. 3 del regolamento", "metadata": {}, "celex_consolidated": "32021R0821", "similarity": 0.91},
    ]
    mock_get_client.return_value = _mock_client_rpc(rows)

    results = vector_search(FAKE_EMBEDDING)

    assert len(results) == 1
    assert results[0]["chunk_text"] == "Art. 3 del regolamento"
    assert results[0]["similarity"] == 0.91


@patch("retrieval._get_client")
def test_vector_search_empty(mock_get_client):
    mock_get_client.return_value = _mock_client_rpc([])

    results = vector_search(FAKE_EMBEDDING)

    assert results == []


@patch("retrieval._get_client")
def test_vector_search_passes_type_filters(mock_get_client):
    """Verifica che type_filters sia passato correttamente all'RPC."""
    mock_get_client.return_value = _mock_client_rpc([])

    vector_search(FAKE_EMBEDDING, type_filters=["ANNEX_CODE"])

    mock_client = mock_get_client.return_value
    call_kwargs = mock_client.rpc.call_args[0][1]  # secondo argomento posizionale
    assert call_kwargs["type_filters"] == ["ANNEX_CODE"]


@patch("retrieval._get_client")
def test_vector_search_no_filters_passes_none(mock_get_client):
    mock_get_client.return_value = _mock_client_rpc([])

    vector_search(FAKE_EMBEDDING, type_filters=None)

    mock_client = mock_get_client.return_value
    call_kwargs = mock_client.rpc.call_args[0][1]
    assert call_kwargs["type_filters"] is None


@patch("retrieval._get_client")
def test_vector_search_metadata_parsed(mock_get_client):
    """Il campo metadata viene parsato da stringa JSON se necessario."""
    rows = [
        {"text": "testo", "metadata": '{"unit_type": "ARTICLE"}', "celex_consolidated": "X", "similarity": 0.8},
    ]
    mock_get_client.return_value = _mock_client_rpc(rows)

    results = vector_search(FAKE_EMBEDDING)

    assert results[0]["metadata"] == {"unit_type": "ARTICLE"}
