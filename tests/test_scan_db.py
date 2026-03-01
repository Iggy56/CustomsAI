"""
Test per tools/scan_db.py – funzioni pure (nessuna dipendenza esterna).

Livello 1: detect_pattern, detect_match_mode, _match_registry_patterns,
           _apply_heuristics, ScanResult.status, render_json_report, _draft_dict.
"""

import json
import pytest
import sys
from pathlib import Path

# Il modulo tools/scan_db.py aggiunge già il root al path, ma i test
# sono eseguiti dalla root del progetto, quindi l'import funziona direttamente.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.scan_db import (
    detect_pattern,
    detect_match_mode,
    _match_registry_patterns,
    _apply_heuristics,
    _draft_dict,
    render_json_report,
    render_text_report,
    ScanResult,
    DraftEntry,
    Check,
)


# ── _match_registry_patterns ─────────────────────────────────────────────────

class TestMatchRegistryPatterns:

    def test_dual_use_samples_match(self):
        samples = ["2B002", "1A001", "3A225", "9E003"]
        pattern, mode, source_id = _match_registry_patterns(samples)
        assert pattern is not None
        assert source_id == "dual_use"
        assert mode == "exact"

    def test_dual_use_case_insensitive(self):
        samples = ["2b002", "1a001"]
        pattern, mode, source_id = _match_registry_patterns(samples)
        assert source_id == "dual_use"

    def test_nomenclature_samples_match(self):
        samples = ["8544000000 80", "8544200000 10", "8544300000 10"]
        pattern, mode, source_id = _match_registry_patterns(samples)
        assert pattern is not None
        assert source_id == "nomenclature"

    def test_unknown_pattern_no_match(self):
        samples = ["XYZ-001", "ABC-999", "DEF-123"]
        pattern, mode, source_id = _match_registry_patterns(samples)
        assert pattern is None
        assert source_id is None

    def test_empty_samples_no_match(self):
        pattern, mode, source_id = _match_registry_patterns([])
        assert pattern is None

    def test_partial_match_below_threshold(self):
        """Solo 1 campione su 5 matcha il pattern dual-use → non supera la soglia."""
        samples = ["2B002", "XXXXXX", "YYYYYY", "ZZZZZZ", "WWWWWW"]
        pattern, mode, source_id = _match_registry_patterns(samples)
        assert source_id != "dual_use" or pattern is None


# ── _apply_heuristics ────────────────────────────────────────────────────────

class TestApplyHeuristics:

    def test_numeric_fixed_length(self):
        samples = ["12345678", "87654321", "11223344"]
        pattern, mode, confidence, desc = _apply_heuristics(samples)
        assert pattern is not None
        assert "8" in pattern  # 8 cifre
        assert mode == "exact"
        assert confidence >= 0.70

    def test_numeric_variable_length(self):
        """Lunghezza 4-10 cifre → prefix suggerito."""
        samples = ["8544", "854420", "85443000", "8544300000"]
        pattern, mode, confidence, desc = _apply_heuristics(samples)
        assert pattern is not None
        assert mode == "prefix"

    def test_alphanumeric_fixed_length(self):
        samples = ["AB1234", "CD5678", "EF9012"]
        pattern, mode, confidence, desc = _apply_heuristics(samples)
        assert pattern is not None
        assert mode == "exact"

    def test_unrecognized_pattern(self):
        samples = ["foo-bar", "baz/qux", "hello-world"]
        pattern, mode, confidence, desc = _apply_heuristics(samples)
        assert pattern is None
        assert confidence == 0.0

    def test_empty_samples(self):
        pattern, mode, confidence, desc = _apply_heuristics([])
        assert pattern is None
        assert confidence == 0.0


# ── detect_pattern ────────────────────────────────────────────────────────────

class TestDetectPattern:

    def test_dual_use_returns_registry_pattern(self):
        samples = ["2B002", "1A001", "3E225"]
        pattern, mode, confidence, notes = detect_pattern(samples)
        assert confidence == 0.95
        assert "dual_use" in notes[0]

    def test_nomenclature_returns_registry_pattern(self):
        samples = ["8544000000 80", "8544200000 10"]
        pattern, mode, confidence, notes = detect_pattern(samples)
        assert confidence == 0.95
        assert "nomenclature" in notes[0]

    def test_unknown_numeric_uses_heuristics(self):
        samples = ["12345678", "87654321", "55667788"]
        pattern, mode, confidence, notes = detect_pattern(samples)
        assert pattern is not None
        assert confidence >= 0.65

    def test_empty_samples_zero_confidence(self):
        pattern, mode, confidence, notes = detect_pattern([])
        assert pattern is None
        assert confidence == 0.0

    def test_unrecognized_returns_none_pattern(self):
        samples = ["foo!bar", "baz@qux", "hello#world"]
        pattern, mode, confidence, notes = detect_pattern(samples)
        assert pattern is None
        assert confidence == 0.0
        assert len(notes) > 0

    def test_low_confidence_adds_note(self):
        """Confidence <0.70 deve aggiungere una nota di avviso."""
        # Alfanumerico quasi-fisso con confidence 0.65
        samples = ["AB1234", "CD5678", "EF9012"]
        pattern, mode, confidence, notes = detect_pattern(samples)
        if confidence < 0.70:
            assert any("manualmente" in n.lower() for n in notes)


# ── detect_match_mode ────────────────────────────────────────────────────────

class TestDetectMatchMode:

    def test_hierarchical_samples_prefix(self):
        """Campioni con relazioni di prefisso → prefix."""
        samples = ["8544", "85442", "854420", "8544200000"]
        assert detect_match_mode(samples) == "prefix"

    def test_uniform_samples_exact(self):
        """Campioni senza relazioni di prefisso → exact."""
        samples = ["2B002", "1A001", "3A225", "9E003"]
        assert detect_match_mode(samples) == "exact"

    def test_large_length_range_prefix(self):
        """Differenza >= 4 caratteri → prefix."""
        samples = ["1234", "12345678"]
        assert detect_match_mode(samples) == "prefix"

    def test_single_sample_exact(self):
        assert detect_match_mode(["2B002"]) == "exact"

    def test_empty_exact(self):
        assert detect_match_mode([]) == "exact"

    def test_nc_codes_with_suffix_strips_correctly(self):
        """
        goods_code ha formato '8544000000 80': lo split rimuove il suffisso.
        Tutti i valori sono 10 digit → stessa lunghezza → detect_match_mode
        restituisce 'exact' (non può inferire la gerarchia dalla sola lunghezza).
        Il match_mode 'prefix' per nomenclature viene da _match_registry_patterns,
        non da detect_match_mode.
        """
        samples = ["8544000000 80", "8544200000 10", "8544300000 10"]
        # Stessa lunghezza dopo lo strip → nessuna relazione di prefisso rilevabile
        assert detect_match_mode(samples) == "exact"

    def test_mixed_length_nc_prefix(self):
        """Codici di lunghezza molto diversa (4 vs 10) → prefix rilevato correttamente."""
        samples = ["8544", "85442", "854420", "8544200000"]
        assert detect_match_mode(samples) == "prefix"


# ── ScanResult.status ────────────────────────────────────────────────────────

class TestScanResultStatus:

    def test_all_passed_is_ok(self):
        r = ScanResult(entry_id="x", table="t", row_estimate=100)
        r.checks = [Check("a", True), Check("b", True), Check("c", True)]
        assert r.status == "ok"

    def test_any_failed_is_error(self):
        r = ScanResult(entry_id="x", table="t", row_estimate=100)
        r.checks = [Check("a", True), Check("b", False, "problema")]
        assert r.status == "error"

    def test_empty_checks_is_ok(self):
        r = ScanResult(entry_id="x", table="t", row_estimate=0)
        assert r.status == "ok"


# ── _draft_dict ──────────────────────────────────────────────────────────────

class TestDraftDict:

    def test_celex_field_source(self):
        d = DraftEntry(
            table="test_table", row_estimate=100,
            code_field="code", text_field="description",
            pattern=r"\b\d{8}\b", match_mode="exact",
            has_celex_field=True, confidence=0.80,
        )
        result = _draft_dict(d)
        assert result["source"]["type"] == "celex_field"
        assert result["id"] == "test_table"
        assert result["code_field"] == "code"
        assert result["match_mode"] == "exact"

    def test_static_celex_source(self):
        d = DraftEntry(
            table="my_table", row_estimate=50,
            code_field="ref", text_field="name",
            pattern=r"\b[A-Z]{2}\d{4}\b", match_mode="exact",
            has_celex_field=False, confidence=0.70,
        )
        result = _draft_dict(d)
        src = result["source"]
        assert src["type"] == "static_celex"
        assert src["celex"] == "???"
        assert src["url"] == "???"

    def test_missing_fields_use_placeholder(self):
        d = DraftEntry(
            table="t", row_estimate=0,
            code_field=None, text_field=None,
            pattern=None, match_mode="exact",
            has_celex_field=False, confidence=0.0,
        )
        result = _draft_dict(d)
        assert result["code_field"] == "???"
        assert result["pattern"] == "???"

    def test_label_from_table_name(self):
        d = DraftEntry(
            table="sanctions_list", row_estimate=500,
            code_field="code", text_field="name",
            pattern=r"\S+", match_mode="exact",
            has_celex_field=False, confidence=0.5,
        )
        result = _draft_dict(d)
        assert result["label"] == "Sanctions List"


# ── render_json_report ───────────────────────────────────────────────────────

class TestRenderJsonReport:

    def _make_scan_result(self, ok=True):
        r = ScanResult(entry_id="dual_use", table="dual_use_items", row_estimate=1000)
        r.checks = [Check("table_exists", ok, "" if ok else "Tabella mancante")]
        return r

    def _make_draft(self, with_code=True):
        return DraftEntry(
            table="new_table", row_estimate=200,
            code_field="code" if with_code else None,
            text_field="description",
            pattern=r"\b\d{8}\b" if with_code else None,
            match_mode="exact",
            has_celex_field=False,
            confidence=0.75 if with_code else 0.0,
            notes=["Test note"],
            sample_codes=["12345678"],
        )

    def test_output_is_valid_json(self):
        report = render_json_report([], [])
        data = json.loads(report)
        assert "scan_date" in data
        assert "registry_validation" in data
        assert "unregistered_tables" in data

    def test_registry_entry_in_output(self):
        report = render_json_report([self._make_scan_result()], [])
        data = json.loads(report)
        assert len(data["registry_validation"]) == 1
        assert data["registry_validation"][0]["id"] == "dual_use"
        assert data["registry_validation"][0]["status"] == "ok"

    def test_failed_registry_status_error(self):
        report = render_json_report([self._make_scan_result(ok=False)], [])
        data = json.loads(report)
        assert data["registry_validation"][0]["status"] == "error"

    def test_draft_entry_in_output(self):
        report = render_json_report([], [self._make_draft()])
        data = json.loads(report)
        assert len(data["unregistered_tables"]) == 1
        entry = data["unregistered_tables"][0]
        assert entry["draft_entry"] is not None
        assert entry["draft_entry"]["table"] == "new_table"

    def test_no_code_field_draft_entry_is_none(self):
        report = render_json_report([], [self._make_draft(with_code=False)])
        data = json.loads(report)
        assert data["unregistered_tables"][0]["draft_entry"] is None

    def test_notes_and_samples_present(self):
        report = render_json_report([], [self._make_draft()])
        data = json.loads(report)
        entry = data["unregistered_tables"][0]
        assert "Test note" in entry["notes"]
        assert "12345678" in entry["sample_codes"]


# ── render_text_report (smoke test) ─────────────────────────────────────────

class TestRenderTextReport:

    def test_contains_header(self):
        out = render_text_report([], [])
        assert "CustomsAI" in out
        assert "Registry Scan Report" in out

    def test_shows_registry_entry(self):
        r = ScanResult(entry_id="dual_use", table="dual_use_items", row_estimate=500)
        r.checks = [Check("table_exists", True)]
        out = render_text_report([r], [])
        assert "dual_use" in out
        assert "✅" in out

    def test_shows_failed_check(self):
        r = ScanResult(entry_id="bad", table="missing_table", row_estimate=0)
        r.checks = [Check("table_exists", False, "Tabella non trovata")]
        out = render_text_report([r], [])
        assert "❌" in out
        assert "Tabella non trovata" in out

    def test_shows_draft_for_code_based_table(self):
        d = DraftEntry(
            table="new_codes", row_estimate=300,
            code_field="code", text_field="description",
            pattern=r"\b\d{6}\b", match_mode="exact",
            has_celex_field=False, confidence=0.80,
            sample_codes=["123456"],
        )
        out = render_text_report([], [d])
        assert "new_codes" in out
        assert "Draft per registry.py" in out

    def test_shows_support_table(self):
        d = DraftEntry(
            table="log_table", row_estimate=5000,
            code_field=None, text_field=None,
            pattern=None, match_mode="exact",
            has_celex_field=False, confidence=0.0,
            notes=["Nessun campo codice rilevato"],
        )
        out = render_text_report([], [d])
        assert "log_table" in out
        assert "supporto" in out.lower()
