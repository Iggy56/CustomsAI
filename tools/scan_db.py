"""
CustomsAI – Automated DB Scanner  (tools/scan_db.py)

Scansiona tutte le tabelle Supabase, valida le entry del registry
e profila le tabelle non ancora registrate, generando draft entry
pronti da incollare in registry.py.

Utilizzo:
    python3 tools/scan_db.py                        # report testuale completo
    python3 tools/scan_db.py --check-only           # solo validazione registry
    python3 tools/scan_db.py --json                 # output JSON
    python3 tools/scan_db.py --json --output r.json # salva su file
    python3 tools/scan_db.py --skip-tables t1,t2    # escludi tabelle extra

Prerequisiti:
    Deployare tools/catalog.sql su Supabase prima del primo utilizzo.
"""

import re
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date

# Aggiungi la root del progetto al path per importare config e registry
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from registry import REGISTRY
from supabase import create_client, Client


# ──────────────────────────────────────────────────────────────
# Costanti
# ──────────────────────────────────────────────────────────────

# Tabelle di sistema da ignorare nel profiling
SYSTEM_TABLES_SKIP: set[str] = {
    "chunks",               # tabella principale (vector search, non collaterale)
    "dual_use_items",       # già in REGISTRY
    "nomenclature",         # già in REGISTRY
    "spatial_ref_sys",      # PostGIS
    "schema_migrations",    # Supabase
    "pg_stat_statements",   # PostgreSQL
}

# Colonne da ignorare nel campionamento (metadati, date, geometrie)
SKIP_COLS: set[str] = {
    "id", "created_at", "updated_at", "imported_at",
    "start_date", "end_date", "consolidation_date",
    "hier_pos", "indent", "language_col", "descr_start_date",
    "language", "embedding",
}

# Tipi PostgreSQL non campionabili utilmente
SKIP_TYPES: set[str] = {"vector", "user-defined", "bytea", "oid"}

# Hint per il rilevamento dei campi
CODE_FIELD_HINTS: list[str] = [
    "code", "codice", "goods_code", "key", "identifier", "ref", "numero",
]
TEXT_FIELD_HINTS: list[str] = [
    "description", "descr", "descrizione", "text", "testo",
    "label", "nome", "name", "content",
]

# Soglie
PATTERN_COVERAGE_WARN: float = 0.80   # % minima per considerare un pattern valido
CONFIDENCE_THRESHOLD:  float = 0.30   # sotto questa soglia: nessun suggerimento
SAMPLE_SIZE:           int   = 20     # campioni per rilevamento pattern
SAMPLE_SIZE_VALIDATION: int  = 30     # campioni per verifica pattern coverage


# ──────────────────────────────────────────────────────────────
# Eccezioni
# ──────────────────────────────────────────────────────────────

class CatalogNotDeployedError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────
# Strutture dati
# ──────────────────────────────────────────────────────────────

@dataclass
class ColumnInfo:
    name:        str
    data_type:   str
    is_nullable: bool


@dataclass
class Check:
    name:   str
    passed: bool
    detail: str = ""


@dataclass
class ScanResult:
    """Risultato della validazione di una entry del registry."""
    entry_id:     str
    table:        str
    row_estimate: int
    checks:       list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(not c.passed for c in self.checks):
            return "error"
        return "ok"


@dataclass
class DraftEntry:
    """Profilo di una tabella non in registry, con draft entry suggerita."""
    table:          str
    row_estimate:   int
    code_field:     str | None
    text_field:     str | None
    pattern:        str | None
    match_mode:     str
    has_celex_field: bool
    confidence:     float
    notes:          list[str] = field(default_factory=list)
    sample_codes:   list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Layer 2 – Catalog RPC
# ──────────────────────────────────────────────────────────────

def _get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _check_catalog_deployed(client: Client) -> None:
    """
    Verifica che le RPC catalog siano deployate.
    Lancia CatalogNotDeployedError con istruzioni se mancanti.
    """
    try:
        client.rpc("list_public_tables", {}).execute()
    except Exception as e:
        msg = str(e)
        if any(k in msg for k in ("PGRST202", "Could not find the function", "function")):
            raise CatalogNotDeployedError(
                "\n[ERRORE] Le funzioni catalog non sono deployate su Supabase.\n"
                "\nSoluzione: esegui tools/catalog.sql nel SQL Editor di Supabase:\n"
                "  https://<tuo-progetto>.supabase.co/project/default/sql/new\n"
                "\nOppure via Supabase CLI:\n"
                "  supabase db push\n"
            ) from e
        raise


def list_tables(client: Client) -> list[tuple[str, int]]:
    resp = client.rpc("list_public_tables", {}).execute()
    return [
        (r["table_name"], int(r.get("row_estimate") or 0))
        for r in (resp.data or [])
    ]


def get_columns(client: Client, table: str) -> list[ColumnInfo]:
    resp = client.rpc("get_table_columns", {"p_table": table}).execute()
    return [
        ColumnInfo(
            name=r["column_name"],
            data_type=r["data_type"].lower(),
            is_nullable=bool(r.get("is_nullable", True)),
        )
        for r in (resp.data or [])
    ]


def sample_values(
    client: Client, table: str, col: str, n: int = SAMPLE_SIZE
) -> list[str]:
    try:
        resp = client.rpc("sample_column_values", {
            "p_table": table, "p_column": col, "p_limit": n,
        }).execute()
        return [r["value"] for r in (resp.data or []) if r.get("value")]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────
# Layer 3 – Pattern detection
# ──────────────────────────────────────────────────────────────

def _match_registry_patterns(
    samples: list[str],
) -> tuple[str | None, str | None, str | None]:
    """
    Fase 1: controlla se i campioni corrispondono a un pattern già nel REGISTRY.
    Restituisce (pattern, match_mode, entry_id) o (None, None, None).
    """
    if not samples:
        return None, None, None

    for entry in REGISTRY:
        regex = re.compile(entry["pattern"], re.IGNORECASE)
        hits = sum(1 for s in samples if regex.search(s.strip()))
        if hits / len(samples) >= PATTERN_COVERAGE_WARN:
            return entry["pattern"], entry["match_mode"], entry["id"]

    return None, None, None


def _apply_heuristics(
    samples: list[str],
) -> tuple[str | None, str, float, str]:
    """
    Fase 2: euristiche generali per rilevare il pattern dai campioni.
    Restituisce (pattern, match_mode, confidence, descrizione).
    """
    if not samples:
        return None, "exact", 0.0, "Nessun campione"

    # Normalizza: rimuovi il suffisso ' XX' come in goods_code "8544000000 80"
    clean = [s.strip().split()[0] for s in samples]

    # Tutti numerici
    if all(re.match(r"^\d+$", s) for s in clean):
        lengths = [len(s) for s in clean]
        min_l, max_l = min(lengths), max(lengths)
        if max_l - min_l >= 4:
            return (
                rf"\b\d{{{min_l},{max_l}}}\b", "prefix", 0.75,
                f"Numerici variabili ({min_l}–{max_l} cifre) → probabile gerarchia",
            )
        elif min_l == max_l:
            return (
                rf"\b\d{{{min_l}}}\b", "exact", 0.80,
                f"Numerici a lunghezza fissa ({min_l} cifre)",
            )
        else:
            return (
                rf"\b\d{{{min_l},{max_l}}}\b", "exact", 0.65,
                f"Numerici quasi-fissi ({min_l}–{max_l} cifre)",
            )

    # Alfanumerici a lunghezza uniforme (es. "AB1234")
    if all(re.match(r"^[A-Z0-9]+$", s, re.IGNORECASE) for s in clean):
        lengths = [len(s) for s in clean]
        if min(lengths) == max(lengths):
            n = lengths[0]
            return (
                rf"\b[A-Z0-9]{{{n}}}\b", "exact", 0.65,
                f"Alfanumerico a lunghezza fissa ({n} caratteri)",
            )

    return None, "exact", 0.0, "Nessun pattern rilevabile automaticamente"


def detect_pattern(
    samples: list[str],
) -> tuple[str | None, str, float, list[str]]:
    """
    Rileva pattern e match_mode da una lista di valori campionati.
    Restituisce (pattern, match_mode, confidence, note).

    Strategia:
      Fase 1 – confronto con pattern già nel REGISTRY (priorità assoluta)
      Fase 2 – euristiche generali
      Fallback – nessun pattern rilevato
    """
    if not samples:
        return None, "exact", 0.0, ["Nessun campione disponibile"]

    notes: list[str] = []

    # Fase 1
    known_p, known_mode, source_id = _match_registry_patterns(samples)
    if known_p:
        notes.append(f"Pattern corrisponde all'entry registry: '{source_id}'")
        return known_p, known_mode, 0.95, notes

    # Fase 2
    pattern, mode, confidence, description = _apply_heuristics(samples)
    if pattern:
        notes.append(description)
        if confidence < 0.70:
            notes.append("Confidence bassa – verificare il pattern manualmente")
        return pattern, mode, confidence, notes

    notes.append("Nessun pattern rilevato – ispezione manuale necessaria")
    return None, "exact", 0.0, notes


def detect_match_mode(samples: list[str]) -> str:
    """
    Suggerisce 'exact' o 'prefix' basandosi sull'analisi delle relazioni
    di prefisso tra i campioni.
    """
    if not samples:
        return "exact"

    clean = [s.strip().split()[0] for s in samples]
    n = len(clean)
    if n < 2:
        return "exact"

    prefix_pairs = sum(
        1
        for i in range(n)
        for j in range(i + 1, n)
        if clean[i].startswith(clean[j]) or clean[j].startswith(clean[i])
    )
    total_pairs = n * (n - 1) / 2

    if prefix_pairs / total_pairs > 0.20:
        return "prefix"

    lengths = [len(s) for s in clean]
    if max(lengths) - min(lengths) >= 4:
        return "prefix"

    return "exact"


# ──────────────────────────────────────────────────────────────
# Layer 3 – Validazione entry registry
# ──────────────────────────────────────────────────────────────

def validate_registry_entry(
    client: Client,
    entry: dict,
    all_table_names: set[str],
) -> ScanResult:
    """
    Esegue 6 check su una entry del registry contro il DB reale.
    Si ferma al primo errore bloccante (tabella mancante, campi mancanti).
    """
    result = ScanResult(
        entry_id=entry["id"],
        table=entry["table"],
        row_estimate=0,
    )

    # ── 1. Tabella esiste ────────────────────────────────────
    if entry["table"] not in all_table_names:
        result.checks.append(Check(
            "table_exists", False,
            f"Tabella '{entry['table']}' non trovata nel DB",
        ))
        return result
    result.checks.append(Check("table_exists", True))

    # ── 2. Colonne presenti ──────────────────────────────────
    cols = get_columns(client, entry["table"])
    col_names = {c.name for c in cols}

    code_ok = entry["code_field"] in col_names
    text_ok = entry["text_field"] in col_names
    result.checks.append(Check(
        "code_field_exists", code_ok,
        "" if code_ok else f"Campo '{entry['code_field']}' non trovato",
    ))
    result.checks.append(Check(
        "text_field_exists", text_ok,
        "" if text_ok else f"Campo '{entry['text_field']}' non trovato",
    ))
    if not code_ok:
        return result

    # ── 3. Dati presenti ─────────────────────────────────────
    samples = sample_values(client, entry["table"], entry["code_field"], SAMPLE_SIZE_VALIDATION)
    result.checks.append(Check(
        "has_data", bool(samples),
        f"{len(samples)} campioni letti" if samples else "Nessun dato nel code_field",
    ))
    if not samples:
        return result

    # ── 4. Copertura pattern ─────────────────────────────────
    regex = re.compile(entry["pattern"], re.IGNORECASE)
    hits = sum(1 for s in samples if regex.search(s))
    coverage = hits / len(samples)
    coverage_ok = coverage >= PATTERN_COVERAGE_WARN
    result.checks.append(Check(
        "pattern_coverage", coverage_ok,
        f"{coverage:.0%} dei campioni matchano il pattern"
        + ("" if coverage_ok else f"  (soglia: {PATTERN_COVERAGE_WARN:.0%})"),
    ))

    # ── 5. Lookup di verifica ────────────────────────────────
    sample_code = samples[0].strip().upper().split()[0]
    try:
        q = client.table(entry["table"]).select(entry["code_field"])
        if entry["match_mode"] == "exact":
            q = q.eq(entry["code_field"], sample_code)
        else:
            q = q.like(entry["code_field"], f"{sample_code[:4]}%")
        resp = q.limit(5).execute()
        n_results = len(resp.data or [])
        result.checks.append(Check(
            "sample_lookup", n_results > 0,
            f"Lookup '{sample_code}' → {n_results} risultati",
        ))
    except Exception as e:
        result.checks.append(Check("sample_lookup", False, f"Errore: {e}"))

    # ── 6. Consistenza fonte ─────────────────────────────────
    src = entry.get("source", {})
    if src.get("type") == "celex_field":
        celex_ok = "celex_consolidated" in col_names
        result.checks.append(Check(
            "celex_field_present", celex_ok,
            "" if celex_ok
            else "Campo celex_consolidated mancante (richiesto da source.type=celex_field)",
        ))
    elif src.get("type") == "static_celex":
        static_ok = bool(src.get("celex") and src.get("url"))
        result.checks.append(Check(
            "static_celex_configured", static_ok,
            "" if static_ok else "source.celex o source.url mancante",
        ))

    return result


# ──────────────────────────────────────────────────────────────
# Layer 4 – Profiling tabelle non in registry
# ──────────────────────────────────────────────────────────────

def profile_unknown_table(
    client: Client, table: str, row_estimate: int
) -> DraftEntry:
    """
    Profila una tabella non in registry.
    Rileva code_field, text_field, pattern, match_mode e genera una DraftEntry.
    """
    draft = DraftEntry(
        table=table, row_estimate=row_estimate,
        code_field=None, text_field=None,
        pattern=None, match_mode="exact",
        has_celex_field=False, confidence=0.0,
    )

    cols = get_columns(client, table)
    if not cols:
        draft.notes.append("Impossibile leggere le colonne")
        return draft

    col_names = {c.name for c in cols}
    draft.has_celex_field = "celex_consolidated" in col_names

    # Campiona tutte le colonne utili
    samples_by_col: dict[str, list[str]] = {}
    for c in cols:
        if c.name in SKIP_COLS:
            continue
        if any(t in c.data_type for t in SKIP_TYPES):
            continue
        vals = sample_values(client, table, c.name, SAMPLE_SIZE)
        if vals:
            samples_by_col[c.name] = vals

    # Rileva code_field: colonna con confidence massima, con bonus per nome
    code_candidates: list[tuple[str, float]] = []
    for col, svals in samples_by_col.items():
        _, _, confidence, _ = detect_pattern(svals)
        if confidence >= CONFIDENCE_THRESHOLD:
            name_bonus = 0.10 if any(h in col.lower() for h in CODE_FIELD_HINTS) else 0.0
            code_candidates.append((col, confidence + name_bonus))

    if code_candidates:
        best_col = max(code_candidates, key=lambda x: x[1])[0]
        draft.code_field = best_col
        svals = samples_by_col[best_col]
        pattern, mode, confidence, notes = detect_pattern(svals)
        draft.pattern      = pattern
        draft.match_mode   = mode
        draft.confidence   = confidence
        draft.notes        = notes
        draft.sample_codes = svals[:5]

    # Rileva text_field: prima colonna con nome hint, poi quella con valori più lunghi
    for hint in TEXT_FIELD_HINTS:
        for col in col_names:
            if hint in col.lower() and col != draft.code_field and col not in SKIP_COLS:
                draft.text_field = col
                break
        if draft.text_field:
            break

    if not draft.text_field:
        non_code = [
            (col, sum(len(v) for v in svals) / len(svals))
            for col, svals in samples_by_col.items()
            if col != draft.code_field and svals
        ]
        if non_code:
            draft.text_field = max(non_code, key=lambda x: x[1])[0]

    if not draft.code_field:
        draft.notes.append(
            "Nessun campo codice rilevato – tabella di supporto o struttura non standard"
        )
    if not draft.text_field:
        draft.notes.append("Nessun campo testo rilevato")

    return draft


# ──────────────────────────────────────────────────────────────
# Layer 5 – Rendering report
# ──────────────────────────────────────────────────────────────

def _check_icon(passed: bool) -> str:
    return "✅" if passed else "❌"


def _draft_dict(d: DraftEntry) -> dict:
    """Genera il dict pronto da incollare in registry.py."""
    return {
        "id":         d.table,
        "table":      d.table,
        "code_field": d.code_field or "???",
        "text_field": d.text_field or "???",
        "pattern":    d.pattern    or "???",
        "label":      d.table.replace("_", " ").title(),
        "match_mode": d.match_mode,
        "source": (
            {"type": "celex_field"}
            if d.has_celex_field
            else {
                "type":  "static_celex",
                "celex": "???",  # ← da completare
                "url":   "???",  # ← da completare
                "label": "???",  # ← da completare
            }
        ),
    }


def _format_draft_entry(d: DraftEntry) -> list[str]:
    """Formatta una DraftEntry come blocco Python pronto da incollare."""
    e = _draft_dict(d)
    src = e["source"]
    lines = [
        "       {",
        f'           "id":         "{e["id"]}",',
        f'           "table":      "{e["table"]}",',
        f'           "code_field": "{e["code_field"]}",',
        f'           "text_field": "{e["text_field"]}",',
        f'           "pattern":     r"{e["pattern"]}",',
        f'           "label":      "{e["label"]}",',
        f'           "match_mode": "{e["match_mode"]}",',
    ]
    if src["type"] == "celex_field":
        lines.append('           "source":     {"type": "celex_field"},')
    else:
        lines += [
            '           "source": {',
            '               "type":  "static_celex",',
            '               "celex": "???",  # ← da completare',
            '               "url":   "???",  # ← da completare',
            '               "label": "???",  # ← da completare',
            '           },',
        ]
    lines.append("       }")
    return lines


def render_text_report(
    registry_results: list[ScanResult],
    drafts: list[DraftEntry],
) -> str:
    SEP = "─" * 57
    L: list[str] = []

    url_short = config.SUPABASE_URL[:55] + ("…" if len(config.SUPABASE_URL) > 55 else "")
    L += [
        "",
        "╔═════════════════════════════════════════════════════════╗",
        "║         CustomsAI – DB Registry Scan Report             ║",
        "╚═════════════════════════════════════════════════════════╝",
        f"  Data     : {date.today().isoformat()}",
        f"  Supabase : {url_short}",
    ]

    # ── Registry validation ──────────────────────────────────
    L += ["", SEP, f" REGISTRY VALIDATION  ({len(registry_results)} entries)", SEP]

    for r in registry_results:
        icon = "✅" if r.status == "ok" else "❌"
        L.append(f"\n  [{icon}]  {r.entry_id}  →  {r.table}")
        for c in r.checks:
            detail = f"  {c.detail}" if c.detail else ""
            L.append(f"        {_check_icon(c.passed)}  {c.name.replace('_', ' ')}{detail}")

    # ── Nuove tabelle ────────────────────────────────────────
    code_based   = [d for d in drafts if d.code_field]
    support_only = [d for d in drafts if not d.code_field]

    L += [
        "", SEP,
        f" TABELLE NON IN REGISTRY  "
        f"({len(drafts)} trovate · {len(code_based)} candidate · {len(support_only)} di supporto)",
        SEP,
    ]

    if not drafts:
        L.append("\n  Nessuna tabella nuova trovata.")

    for d in code_based:
        bar = "█" * int(d.confidence * 10) + "░" * (10 - int(d.confidence * 10))
        L += [
            f"\n  [🔍]  {d.table}   ({d.row_estimate} righe stimate)",
            f"        Confidence : [{bar}] {d.confidence:.0%}",
            f"        code_field : {d.code_field}",
            f"        pattern    : {d.pattern}",
            f"        match_mode : {d.match_mode}",
            f"        text_field : {d.text_field}",
            f"        celex      : {'sì → celex_field' if d.has_celex_field else 'no → static_celex necessario'}",
        ]
        if d.sample_codes:
            L.append(f"        esempi     : {d.sample_codes[:3]}")
        for note in d.notes:
            L.append(f"        ℹ️  {note}")
        L += ["", "        → Draft per registry.py:", ""] + _format_draft_entry(d)

    if support_only:
        L += ["", "  Tabelle di supporto (nessun campo codice rilevato):"]
        for d in support_only:
            notes_str = " – " + d.notes[0] if d.notes else ""
            L.append(f"    • {d.table}  ({d.row_estimate} righe){notes_str}")

    # ── Summary ──────────────────────────────────────────────
    ok_count = sum(1 for r in registry_results if r.status == "ok")
    L += [
        "", SEP, " RIEPILOGO", SEP,
        f"  Registry entries valide : {ok_count} / {len(registry_results)}",
        f"  Nuove tabelle candidate : {len(code_based)} / {len(drafts)}",
    ]
    if code_based:
        L.append("  → Aggiungi le entry in registry.py e riesegui per validarle")
    L.append("")

    return "\n".join(L)


def render_json_report(
    registry_results: list[ScanResult],
    drafts: list[DraftEntry],
) -> str:
    def scan_to_dict(r: ScanResult) -> dict:
        return {
            "id":     r.entry_id,
            "table":  r.table,
            "status": r.status,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in r.checks
            ],
        }

    def draft_to_dict(d: DraftEntry) -> dict:
        return {
            "table":        d.table,
            "row_estimate": d.row_estimate,
            "confidence":   round(d.confidence, 2),
            "draft_entry":  _draft_dict(d) if d.code_field else None,
            "notes":        d.notes,
            "sample_codes": d.sample_codes,
        }

    return json.dumps(
        {
            "scan_date":           date.today().isoformat(),
            "registry_validation": [scan_to_dict(r) for r in registry_results],
            "unregistered_tables": [draft_to_dict(d) for d in drafts],
        },
        indent=2,
        ensure_ascii=False,
    )


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CustomsAI – Automated DB scanner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Prerequisiti:\n"
            "  Deployare tools/catalog.sql su Supabase prima del primo utilizzo.\n\n"
            "Esempi:\n"
            "  python3 tools/scan_db.py\n"
            "  python3 tools/scan_db.py --check-only\n"
            "  python3 tools/scan_db.py --json --output report.json\n"
            "  python3 tools/scan_db.py --skip-tables log_table,temp\n"
        ),
    )
    p.add_argument("--json",         action="store_true", help="Output JSON")
    p.add_argument("--output",       metavar="FILE",      help="Salva output su file")
    p.add_argument("--skip-tables",  metavar="T1,T2",     help="Tabelle aggiuntive da escludere (CSV)")
    p.add_argument("--check-only",   action="store_true", help="Valida solo il registry esistente")
    p.add_argument("--verbose",      action="store_true", help="Stampa progressione su stderr")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    client = _get_client()

    # Verifica che le RPC catalog siano deployate
    try:
        _check_catalog_deployed(client)
    except CatalogNotDeployedError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    # Lista tutte le tabelle pubbliche
    all_tables = list_tables(client)
    table_name_set = {t for t, _ in all_tables}

    # Costruisci il set di tabelle da saltare
    skip = set(SYSTEM_TABLES_SKIP)
    if args.skip_tables:
        skip.update(t.strip() for t in args.skip_tables.split(","))

    # ── Validazione registry ─────────────────────────────────
    registry_results: list[ScanResult] = []
    for entry in REGISTRY:
        if args.verbose:
            print(f"[scan] validating '{entry['id']}'…", file=sys.stderr)
        registry_results.append(
            validate_registry_entry(client, entry, table_name_set)
        )

    # ── Profiling tabelle non in registry ────────────────────
    drafts: list[DraftEntry] = []
    if not args.check_only:
        registry_tables = {e["table"] for e in REGISTRY}
        unknown = [
            (t, r)
            for t, r in all_tables
            if t not in registry_tables and t not in skip
        ]
        for table, row_estimate in unknown:
            if args.verbose:
                print(f"[scan] profiling '{table}'…", file=sys.stderr)
            drafts.append(profile_unknown_table(client, table, row_estimate))

    # ── Rendering ────────────────────────────────────────────
    output = (
        render_json_report(registry_results, drafts)
        if args.json
        else render_text_report(registry_results, drafts)
    )

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"[scan_db] Report salvato in: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
