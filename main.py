"""
CustomsAI v3 – Pipeline registry-first

Flusso:
  detect_intent (keyword) + detect_code_from_registry (pattern)
    → CODE_SPECIFIC  : lookup collaterale → testo diretto, nessun LLM
    → PROCEDURAL+code: lookup collaterale + vector_search → LLM interpretativo
    → CLASSIFICATION : vector_search (ANNEX_CODE) → LLM interpretativo
    → GENERIC        : vector_search globale → LLM interpretativo

Le fonti normative sono sempre stampate da Python, mai dall'LLM.
"""

import sys
from typing import TypedDict

from openai import APIError, APIConnectionError

import config
import embeddings
import retrieval
import prompt as prompt_module
import llm
from query_normalizer import normalize_query
from registry import detect_code_from_registry


# ---------------------------------------------------------------------------
# QueryResult – struttura dati restituita da query()
# ---------------------------------------------------------------------------

class QueryResult(TypedDict):
    mode:    str          # "direct" | "llm" | "empty"
    intent:  str          # valore dell'Intent enum (es. "code_specific")
    codes:   list[str]    # codici rilevati dalla query (es. ["8544"])
    dbs:     list[str]    # ID delle entry con ≥1 risultato (es. ["nomenclature"])
    chunks:  list[dict]   # raw chunks (per display diretto o context LLM)
    answer:  str | None   # risposta LLM (solo mode="llm")
    sources: list[dict]   # [{"label": str|None, "celex": str, "url": str}]
    log:     list[str]    # messaggi di routing/debug in ordine


# ---------------------------------------------------------------------------
# Source helpers (deterministico)
# ---------------------------------------------------------------------------

def _eurlex_link(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{celex}"


def _build_sources(chunks: list[dict], active_entries: list[dict]) -> list[dict]:
    """
    Costruisce la lista di fonti normative in modo puro (nessun print).

    Due tipi di fonte (non esclusivi):
      - static_celex : CELEX fisso letto dall'entry del registry (es. nomenclature)
      - celex_field  : CELEX dinamico letto dal campo celex_consolidated dei chunk
    """
    sources: list[dict] = []

    # 1. Fonti statiche dal registry (es. nomenclature, dual_use_correlations)
    for entry in active_entries:
        src = entry.get("source", {})
        if src.get("type") == "static_celex":
            sources.append({
                "label": src.get("label"),
                "celex": src["celex"],
                "url":   src["url"],
            })

    # 2. CELEX dinamici dai chunk (celex_field)
    seen: set[str] = set()
    for c in chunks:
        celex = c.get("celex_consolidated")
        if celex and celex not in seen:
            seen.add(celex)
            sources.append({
                "label": None,
                "celex": celex,
                "url":   _eurlex_link(celex),
            })

    return sources


def _render_sources(sources: list[dict]) -> None:
    """Stampa la lista di fonti già costruita nel formato testuale standard."""
    if not sources:
        return

    lines: list[str] = []
    for src in sources:
        if src.get("label"):
            lines.append(src["label"])
        lines.append(f"CELEX: {src['celex']}")
        lines.append(src["url"])
        lines.append("")

    print("\n---")
    print("FONTI NORMATIVE (deterministiche)\n")
    print("\n".join(lines))
    print("---")


def _print_normative_sources(
    chunks: list[dict],
    registry_entries: list[dict],
) -> None:
    """
    Stampa le fonti normative in modo deterministico.

    Due tipi di fonte (non esclusivi):
      - static_celex : CELEX fisso letto dall'entry del registry (es. nomenclature)
      - celex_field  : CELEX dinamico letto dal campo celex_consolidated dei chunk
    """
    _render_sources(_build_sources(chunks, registry_entries))


# ---------------------------------------------------------------------------
# EUR-Lex text formatter (best-effort, ~85% accuracy su strutture profonde)
# ---------------------------------------------------------------------------

import re as _re

_LETTER_RE  = _re.compile(r'^([a-z])\.$')
_NUMBER_RE  = _re.compile(r'^(\d+)\.$')
_EM_DASH    = '—'
_CONNECTORS = frozenset({'e', 'o'})
_NOTE_HDRS  = {'Note tecniche', 'Note tecniche:', 'N.B', 'N.B.', 'N.B.:'}


def _is_list_marker(line: str) -> bool:
    return bool(_LETTER_RE.match(line) or _NUMBER_RE.match(line) or line == _EM_DASH)


def _is_section_break(line: str) -> bool:
    """True se la riga è un marcatore di lista OPPURE un'intestazione di sezione nota."""
    return _is_list_marker(line) or line.rstrip(':') in {'Note tecniche', 'N.B', 'N.B.'}


def _format_eurlex_text(text: str) -> str:
    """
    Converte il plain text EUR-Lex (formato allegati dual-use) in markdown multilivello.

    Livelli gestiti:
      1  a. b. c.        →  - **a.** testo
      2  1. 2. 3.        →    - **1.** testo
      3  a. b. (sub)     →      - **a.** testo
      4  1. 2. (subsub)  →        - **1.** testo

    Limiti noti: su strutture >4 livelli con lettere riusate la gerarchia
    può essere imprecisa (~85% di accuratezza). Il testo originale è sempre
    disponibile nell'expander Streamlit.
    """
    lines = text.split('\n')
    out: list[str] = []

    depth          = 0
    next_d1        = 0   # prossima lettera attesa al livello 1 (a=0, b=1, …)
    next_d3        = 0   # prossima lettera attesa al livello 3 dentro il parent corrente
    last_text      = ''  # testo dell'ultimo item (per euristica ':')
    in_note        = False
    connector      = ''

    _INDENT = {1: '', 2: '  ', 3: '    ', 4: '      '}

    i = 0
    while i < len(lines):
        raw  = lines[i]
        line = raw.strip()
        i   += 1

        if not line:
            continue

        # ── Connettore (e / o da solo su riga) ───────────────────────────────
        if line in _CONNECTORS:
            connector = f' **{line}**'
            continue

        sfx       = connector
        connector = ''

        # ── Intestazione sezione Note / N.B. ─────────────────────────────────
        if line.rstrip(':') in {'Note tecniche', 'N.B', 'N.B.'}:
            out.append(f'\n*{line}*')
            in_note = True
            depth   = 0
            continue

        # ── Trattino em (—) ───────────────────────────────────────────────────
        if line == _EM_DASH:
            parts = []
            while i < len(lines):
                nl = lines[i].strip()
                if not nl or _is_section_break(nl):
                    break
                parts.append(nl)
                i += 1
            item = " ".join(parts)
            out.append(f'  - *{item}*' if in_note else f'  - {item}{sfx}')
            continue

        # ── Marcatore lettera ─────────────────────────────────────────────────
        m = _LETTER_RE.match(line)
        if m:
            in_note = False
            letter  = m.group(1)
            idx     = ord(letter) - ord('a')

            # Determina livello
            if depth <= 1:
                depth   = 1
                next_d1 = idx + 1
                next_d3 = 0
            elif depth == 2:
                depth   = 3
                next_d3 = idx + 1
            elif depth == 4:
                # Torna al livello 3 (sub-lettera dopo sub-numero)
                depth   = 3
                next_d3 = idx + 1
            else:  # depth == 3
                if idx == next_d3:
                    # Sibling al livello 3
                    next_d3 = idx + 1
                elif idx == next_d1:
                    # Torna al livello 1
                    depth   = 1
                    next_d1 = idx + 1
                    next_d3 = 0
                else:
                    # Ambiguo: best-effort → rimane livello 3
                    next_d3 = idx + 1

            # Raccoglie testo dell'item
            parts = []
            while i < len(lines):
                nl = lines[i].strip()
                if not nl or _is_section_break(nl) or nl in _CONNECTORS:
                    break
                parts.append(nl)
                i += 1
            last_text = ' '.join(parts)

            ind = _INDENT.get(depth, '')
            out.append(f'{ind}- **{letter}.** {last_text}{sfx}')
            continue

        # ── Marcatore numero ──────────────────────────────────────────────────
        m = _NUMBER_RE.match(line)
        if m:
            num = m.group(1)

            # Numeri nelle Note tecniche → corsivo
            if in_note:
                # Salta righe vuote prima del testo (nel DB le note hanno \n\n\n)
                while i < len(lines) and not lines[i].strip():
                    i += 1
                parts = []
                while i < len(lines):
                    nl = lines[i].strip()
                    if _is_section_break(nl):
                        break
                    if nl:
                        parts.append(nl)
                    i += 1
                out.append(f'  *{num}. {" ".join(parts)}*')
                continue

            # Determina livello
            if depth <= 1:
                depth = 2
            elif depth == 2:
                pass  # sibling
            elif depth == 3:
                depth = 4 if last_text.endswith(':') else 2
            elif depth == 4:
                pass  # sibling

            # Raccoglie testo
            parts = []
            while i < len(lines):
                nl = lines[i].strip()
                if not nl or _is_section_break(nl) or nl in _CONNECTORS:
                    break
                parts.append(nl)
                i += 1
            last_text = ' '.join(parts)

            ind = _INDENT.get(depth, '')
            out.append(f'{ind}- **{num}.** {last_text}{sfx}')
            continue

        # ── Testo normale ─────────────────────────────────────────────────────
        out.append(f'*{line}*' if in_note else line)

    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Correlation graph helpers (Fase 3 – deterministico, nessun LLM)
# ---------------------------------------------------------------------------

def _extract_linked_codes(
    registry_matches: list[tuple[dict, str]],
    collateral_results: list[dict],
) -> list[str]:
    """
    Estrae i codici "linked" dai risultati collaterali delle entry che hanno 'links_to'.
    Legge 'links_to' dal registry (nessun hardcoding di ID).

    Esempio: dual_use_correlations ha links_to="dual_use" → i text_value dei suoi
    risultati sono codici DU (es. "3E001") da usare per la Opzione A della Fase 3.
    """
    linking_ids = {
        entry["id"]
        for entry, _ in registry_matches
        if entry.get("links_to")
    }

    codes: list[str] = []
    seen: set[str] = set()
    for chunk in collateral_results:
        source_id = chunk.get("metadata", {}).get("source_id")
        if source_id in linking_ids:
            text_value = chunk.get("metadata", {}).get("text_value", "").strip()
            if text_value and text_value not in seen:
                seen.add(text_value)
                codes.append(text_value)
    return codes


def _build_correlation_preamble(
    registry_matches: list[tuple[dict, str]],
    collateral_results: list[dict],
) -> str:
    """
    Costruisce un riepilogo testuale delle correlazioni trovate tra DB collaterali.
    Incluso nel contesto LLM per rendere espliciti i collegamenti NC→DU.

    Esempio output:
        CORRELAZIONI RILEVATE NEL DATABASE:
        - NC 8544300000 → Dual Use Correlations: 3E001
    """
    lines: list[str] = []

    entry_by_id = {entry["id"]: entry for entry, _ in registry_matches}

    for chunk in collateral_results:
        meta = chunk.get("metadata", {})
        source_id = meta.get("source_id")
        entry = entry_by_id.get(source_id)
        if entry and entry.get("links_to"):
            nc_code = meta.get("code", "")
            du_code = meta.get("text_value", "").strip()
            if nc_code and du_code:
                lines.append(f"- NC {nc_code} → {entry['label']}: {du_code}")

    if not lines:
        return ""

    return "CORRELAZIONI RILEVATE NEL DATABASE:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_direct_text(chunks: list[dict]) -> None:
    print("\n=== TESTO NORMATIVO ===\n")
    for r in chunks:
        print(_format_eurlex_text(r.get("chunk_text", "")))
        print("\n---")


# ---------------------------------------------------------------------------
# Query – pura computazione, nessun print
# ---------------------------------------------------------------------------

def query(question: str) -> QueryResult:
    """
    Esegue la pipeline di retrieval e restituisce un QueryResult strutturato.
    Nessun print: i messaggi di routing vanno in result["log"].

    Raises:
        ValueError: se la domanda è vuota.
        APIError, APIConnectionError: errori OpenAI (embedding o LLM).
    """
    q = (question or "").strip()
    if not q:
        raise ValueError("Domanda vuota.")

    log: list[str] = []

    # ── 1. Intent (keyword) + codice (registry pattern scan) ──────────────
    base_intent      = retrieval.detect_intent(q)
    registry_matches = detect_code_from_registry(q)   # list[tuple[dict, str]]

    # ── 2. Intent finale ───────────────────────────────────────────────────
    if registry_matches:
        intent = (
            base_intent
            if base_intent == retrieval.Intent.PROCEDURAL
            else retrieval.Intent.CODE_SPECIFIC
        )
    else:
        intent = base_intent

    log.append(
        f"[routing] intent={intent.value} | "
        f"code={','.join(c for _,c in registry_matches) if registry_matches else '-'} | "
        f"db={','.join(e['id'] for e,_ in registry_matches) if registry_matches else '-'}"
    )

    # ── 3. CODE_SPECIFIC: lookup collaterale, nessun embedding, nessun LLM ─
    if intent == retrieval.Intent.CODE_SPECIFIC:
        chunks: list[dict] = []
        active_entries: list[dict] = []
        for entry, code in registry_matches:
            results = retrieval.lookup_collateral(entry, code)
            if results:
                chunks += results
                active_entries.append(entry)

        if not chunks:
            log.append("[routing] nessun risultato collaterale → fallback vector search")
            intent = retrieval.Intent.GENERIC  # ricade nel ramo vector
        else:
            return QueryResult(
                mode="direct",
                intent=intent.value,
                codes=[c for _, c in registry_matches],
                dbs=[e["id"] for e in active_entries],
                chunks=chunks,
                answer=None,
                sources=_build_sources(chunks, active_entries),
                log=log,
            )

    # ── 4. Embedding (necessario per tutti i rami rimanenti) ───────────────
    normalized_query = normalize_query(q, intent)
    log.append(f"[normalization] embedding query: {normalized_query}")
    query_embedding = embeddings.get_embedding(normalized_query)  # può raise

    # ── 5. PROCEDURAL + codice: collaterale + annex (A) + vector (B) → LLM ─
    if intent == retrieval.Intent.PROCEDURAL and registry_matches:
        collateral: list[dict] = []
        active_entries = []
        for entry, code in registry_matches:
            results = retrieval.lookup_collateral(entry, code)
            if results:
                collateral += results
                active_entries.append(entry)

        # Opzione A: definizioni annex per i codici DU collegati (links_to)
        linked_codes = _extract_linked_codes(registry_matches, collateral)
        annex_chunks = retrieval.get_annex_chunks_by_codes(linked_codes) if linked_codes else []
        if linked_codes:
            log.append(f"[routing] analytical mode: linked_codes={linked_codes}")

        # Opzione B: vector search
        # In analytical mode usa una query focalizzata sui DU codes trovati,
        # senza il codice NC che sposta l'embedding verso la nomenclatura.
        if linked_codes:
            du_query = f"obblighi autorizzazione esportazione {' '.join(linked_codes[:3])}"
            log.append(f"[routing] analytical vector query: {du_query}")
            analytical_embedding = embeddings.get_embedding(du_query)
            vec_chunks = retrieval.vector_search(analytical_embedding)
        else:
            vec_chunks = retrieval.vector_search(query_embedding)

        combined = collateral + annex_chunks + vec_chunks

        if not combined:
            return QueryResult(
                mode="empty",
                intent=intent.value,
                codes=[c for _, c in registry_matches],
                dbs=[],
                chunks=[],
                answer=None,
                sources=[],
                log=log,
            )

        preamble = _build_correlation_preamble(registry_matches, collateral)
        context  = prompt_module.format_context(combined, preamble=preamble)
        answer   = llm.generate_answer(q, context, analytical=bool(linked_codes))
        answer  += prompt_module.DISCLAIMER
        return QueryResult(
            mode="llm",
            intent=intent.value,
            codes=[c for _, c in registry_matches],
            dbs=[e["id"] for e in active_entries],
            chunks=combined,
            answer=answer,
            sources=_build_sources(combined, active_entries),
            log=log,
        )

    # ── 6. CLASSIFICATION / GENERIC: solo vector search → LLM ─────────────
    type_filters = (
        ["ANNEX_CODE"] if intent == retrieval.Intent.CLASSIFICATION else None
    )

    chunks = retrieval.vector_search(query_embedding, type_filters=type_filters)

    if not chunks and type_filters:
        log.append(f"[routing] nessun risultato con filtri={type_filters} → fallback global")
        chunks = retrieval.vector_search(query_embedding)

    if not chunks:
        return QueryResult(
            mode="empty",
            intent=intent.value,
            codes=[c for _, c in registry_matches],
            dbs=[],
            chunks=[],
            answer=None,
            sources=[],
            log=log,
        )

    context = prompt_module.format_context(chunks)
    answer  = llm.generate_answer(q, context, used_structured_by_code=False)
    answer += prompt_module.DISCLAIMER
    return QueryResult(
        mode="llm",
        intent=intent.value,
        codes=[c for _, c in registry_matches],
        dbs=[],
        chunks=chunks,
        answer=answer,
        sources=_build_sources(chunks, []),
        log=log,
    )


# ---------------------------------------------------------------------------
# Run – wrapper CLI (output identico all'attuale)
# ---------------------------------------------------------------------------

def run(question: str) -> None:
    q = (question or "").strip()
    if not q:
        print("Errore: domanda vuota.")
        sys.exit(1)

    try:
        result = query(q)
    except (APIError, APIConnectionError, ValueError) as e:
        print("Errore:", e)
        sys.exit(1)

    for msg in result["log"]:
        print(msg)

    if result["mode"] == "empty":
        print("Nessun risultato trovato.")
        sys.exit(0)
    elif result["mode"] == "direct":
        _display_direct_text(result["chunks"])
    else:
        print("\n=== RISPOSTA ===\n")
        print(result["answer"])

    _render_sources(result["sources"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python main.py "domanda"')
        sys.exit(1)

    run(" ".join(sys.argv[1:]))
