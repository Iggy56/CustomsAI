"""
Level 1 – Unit test: registry.py

Testa:
  - struttura delle entry del registry
  - rilevamento codice dual-use (exact, case-insensitive)
  - rilevamento codice NC / nomenclature (prefix)
  - priorità: dual_use prima di nomenclature
  - nessun match per query generiche
"""

import pytest
from registry import REGISTRY, detect_code_from_registry


# ── Struttura del registry ──────────────────────────────────────────────────

REQUIRED_FIELDS = ["id", "table", "code_field", "text_field", "pattern", "label", "match_mode", "source"]

def test_registry_has_entries():
    assert len(REGISTRY) >= 2

def test_registry_entry_structure():
    for entry in REGISTRY:
        for field in REQUIRED_FIELDS:
            assert field in entry, f"Entry '{entry.get('id')}' manca campo '{field}'"

def test_registry_ids_are_unique():
    ids = [e["id"] for e in REGISTRY]
    assert len(ids) == len(set(ids))

def test_registry_match_modes_are_valid():
    for entry in REGISTRY:
        assert entry["match_mode"] in ("exact", "prefix"), \
            f"Entry '{entry['id']}' ha match_mode non valido: {entry['match_mode']}"

def test_registry_source_types_are_valid():
    valid_types = {"celex_field", "static_celex"}
    for entry in REGISTRY:
        assert entry["source"]["type"] in valid_types, \
            f"Entry '{entry['id']}' ha source.type non valido: {entry['source']['type']}"

def test_static_celex_has_required_fields():
    for entry in REGISTRY:
        if entry["source"]["type"] == "static_celex":
            assert "celex" in entry["source"]
            assert "url" in entry["source"]


# ── Rilevamento codice dual-use ─────────────────────────────────────────────

@pytest.mark.parametrize("query,expected_code", [
    ("voglio esportare il bene 2B002", "2B002"),
    ("classificazione 1A001 nel regolamento", "1A001"),
    ("codice 3A225", "3A225"),
    ("bene 9E003", "9E003"),
])
def test_detect_dual_use(query, expected_code):
    entry, code = detect_code_from_registry(query)
    assert entry is not None
    assert entry["id"] == "dual_use"
    assert code == expected_code

def test_detect_dual_use_case_insensitive():
    """L'utente può scrivere in minuscolo: 2b002 deve matchare."""
    entry, code = detect_code_from_registry("bene 2b002")
    assert entry is not None
    assert entry["id"] == "dual_use"
    assert code == "2B002"  # normalizzato uppercase

def test_detect_dual_use_priority_over_nomenclature():
    """2B002 contiene cifre → potrebbe matchare anche il pattern NC.
    Deve vincere dual_use perché viene prima nel registry."""
    entry, code = detect_code_from_registry("2B002")
    assert entry["id"] == "dual_use"


# ── Rilevamento codice NC (nomenclature) ────────────────────────────────────

@pytest.mark.parametrize("query,expected_code", [
    ("voce doganale 8544", "8544"),
    ("classificazione 8544300000", "8544300000"),
    ("cosa è la voce 2507", "2507"),
])
def test_detect_nomenclature(query, expected_code):
    entry, code = detect_code_from_registry(query)
    assert entry is not None
    assert entry["id"] == "nomenclature"
    assert code == expected_code

def test_detect_nomenclature_not_dual_use():
    """8544 non deve essere rilevato come dual-use."""
    entry, _ = detect_code_from_registry("voce 8544")
    assert entry["id"] == "nomenclature"


# ── Nessun match ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "domanda generica senza codici",
    "cosa dice il regolamento?",
    "obblighi di esportazione",
    "",
])
def test_no_match(query):
    entry, code = detect_code_from_registry(query)
    assert entry is None
    assert code is None

def test_none_input():
    entry, code = detect_code_from_registry(None)
    assert entry is None
    assert code is None
