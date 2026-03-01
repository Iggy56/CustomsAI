"""
Level 1 – Unit test: fonti normative (main._print_normative_sources)

Testa che le fonti siano stampate correttamente per entrambi i tipi:
  - celex_field  (da chunks.celex_consolidated)
  - static_celex (da registry entry)

Nessuna dipendenza esterna.
"""

import pytest
from main import _print_normative_sources, _eurlex_link


# ── _eurlex_link ──────────────────────────────────────────────────────────────

def test_eurlex_link_format():
    link = _eurlex_link("32021R0821")
    assert link == "https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:32021R0821"

def test_eurlex_link_various_celex():
    for celex in ["31987R2658", "32019R2220", "32021R0821"]:
        link = _eurlex_link(celex)
        assert celex in link
        assert link.startswith("https://")


# ── Fonti da celex_field (chunks) ─────────────────────────────────────────────

def test_sources_celex_field_prints_celex(capsys):
    chunks = [{"celex_consolidated": "32021R0821", "chunk_text": "..."}]
    _print_normative_sources(chunks, registry_entries=[])
    out = capsys.readouterr().out
    assert "32021R0821" in out
    assert "FONTI NORMATIVE" in out

def test_sources_celex_field_no_duplicates(capsys):
    """Lo stesso CELEX presente in più chunk deve comparire una sola volta
    come riga 'CELEX: ...' (non duplicato, anche se l'URL lo contiene anch'esso)."""
    chunks = [
        {"celex_consolidated": "32021R0821", "chunk_text": "chunk 1"},
        {"celex_consolidated": "32021R0821", "chunk_text": "chunk 2"},
        {"celex_consolidated": "32019R2220", "chunk_text": "chunk 3"},
    ]
    _print_normative_sources(chunks, registry_entries=[])
    out = capsys.readouterr().out
    celex_lines = [line for line in out.splitlines() if line.startswith("CELEX:")]
    assert celex_lines.count("CELEX: 32021R0821") == 1
    assert any("32019R2220" in line for line in celex_lines)

def test_sources_celex_field_multiple(capsys):
    chunks = [
        {"celex_consolidated": "32021R0821", "chunk_text": "a"},
        {"celex_consolidated": "32019R2220", "chunk_text": "b"},
    ]
    _print_normative_sources(chunks, registry_entries=[])
    out = capsys.readouterr().out
    assert "32021R0821" in out
    assert "32019R2220" in out


# ── Fonti da static_celex (registry entry) ───────────────────────────────────

NOMENCLATURE_ENTRY = {
    "source": {
        "type": "static_celex",
        "celex": "31987R2658",
        "url": "https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=celex:31987R2658",
        "label": "Nomenclatura Combinata (Reg. CEE 2658/87)",
    }
}

def test_sources_static_celex_prints_celex(capsys):
    _print_normative_sources([], registry_entries=[NOMENCLATURE_ENTRY])
    out = capsys.readouterr().out
    assert "31987R2658" in out
    assert "Nomenclatura Combinata" in out
    assert "FONTI NORMATIVE" in out

def test_sources_static_celex_prints_url(capsys):
    _print_normative_sources([], registry_entries=[NOMENCLATURE_ENTRY])
    out = capsys.readouterr().out
    assert NOMENCLATURE_ENTRY["source"]["url"] in out


# ── Fonti combinate ───────────────────────────────────────────────────────────

def test_sources_both_printed(capsys):
    """static_celex dal registry + celex_field dai chunk devono apparire entrambi."""
    chunks = [{"celex_consolidated": "32021R0821", "chunk_text": "..."}]
    _print_normative_sources(chunks, registry_entries=[NOMENCLATURE_ENTRY])
    out = capsys.readouterr().out
    assert "31987R2658" in out
    assert "32021R0821" in out


# ── Nessuna fonte: nessun output ──────────────────────────────────────────────

def test_sources_empty_no_output(capsys):
    _print_normative_sources([], registry_entries=[])
    out = capsys.readouterr().out
    assert out == ""

def test_sources_chunks_without_celex_no_output(capsys):
    chunks = [{"celex_consolidated": None, "chunk_text": "..."}, {"chunk_text": "..."}]
    _print_normative_sources(chunks, registry_entries=[])
    out = capsys.readouterr().out
    assert out == ""

def test_sources_celex_field_source_type_no_static(capsys):
    """Se registry entry ha type=celex_field, non stampa CELEX fisso."""
    entry_celex_field = {"source": {"type": "celex_field"}}
    chunks = [{"celex_consolidated": "32021R0821", "chunk_text": "..."}]
    _print_normative_sources(chunks, registry_entries=[entry_celex_field])
    out = capsys.readouterr().out
    # Solo il CELEX dal chunk, nessun CELEX fisso dal registry
    assert "32021R0821" in out
    assert "celex_field" not in out
