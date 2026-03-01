"""
CustomsAI – Registry dei DB collaterali (v3)

Questo è l'UNICO punto di configurazione per i DB collaterali.

Aggiungere un nuovo DB = aggiungere una entry in REGISTRY.
Nessun altro file deve essere modificato.

Struttura di ogni entry:
    id          – identificatore univoco
    table       – nome tabella Supabase
    code_field  – campo su cui fare il lookup
    text_field  – campo testo da restituire
    pattern     – regex per riconoscere il codice nell'input utente
    label       – etichetta human-readable
    match_mode  – "exact" | "prefix"
    source      – configurazione fonte:
                    {"type": "celex_field"}               → CELEX letto dalla riga
                    {"type": "static_celex", "celex": …}  → CELEX fisso
"""

import re

REGISTRY: list[dict] = [
    {
        "id": "dual_use",
        "table": "dual_use_items",
        "code_field": "code",
        "text_field": "description",
        "pattern": r"\b[0-9][A-Z][0-9]{3}\b",
        "label": "Bene a duplice uso",
        "match_mode": "exact",
        "source": {
            "type": "celex_field",
        },
    },
    {
        "id": "nomenclature",
        "table": "nomenclature",
        "code_field": "goods_code",
        "text_field": "description",
        "pattern": r"\b\d{4,10}\b",
        "label": "Nomenclatura Combinata",
        "match_mode": "prefix",
        # display_code_field: se presente, il chunk_text include il codice e l'indentazione
        # gerarchica (basata sul campo "indent": null=voce, "-"=livello 1, "- -"=livello 2, ecc.)
        # Il valore del campo ha formato "{10 cifre} {2 cifre}" → viene estratta solo la parte numerica.
        "display_code_field": "goods_code",
        "source": {
            "type": "static_celex",
            "celex": "31987R2658",
            "url": "https://eur-lex.europa.eu/legal-content/IT/ALL/?uri=celex:31987R2658",
            "label": "Nomenclatura Combinata (Reg. CEE 2658/87)",
        },
    },
    {
        "id": "dual_use_correlations",
        "table": "dual_use_correlations",
        "code_field": "cn_codes_2026",
        "text_field": "dual_use_codification",
        "pattern": r"\b\d{4,10}\b",
        "label": "Dual Use Correlations",
        "match_mode": "prefix",
        # display_code_field: il codice NC viene anteposto alla codifica DU
        # in modo da mostrare "8704229100  9A115b" invece del solo "9A115b"
        "display_code_field": "cn_codes_2026",
        "source": {
            "type": "static_celex",
            "celex": "32021R0821",
            "url": "https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:32021R0821",
            "label": "Regolamento UE 2021/821 (Beni a duplice uso)",
        },
    },
]

# Pre-compile patterns in registry order (IGNORECASE per tollerare input minuscolo).
_COMPILED: list[tuple[dict, re.Pattern]] = [
    (entry, re.compile(entry["pattern"], re.IGNORECASE))
    for entry in REGISTRY
]


def detect_code_from_registry(query: str) -> list[tuple[dict, str]]:
    """
    Scansiona tutti i pattern del registry nell'ordine in cui sono definiti.
    Restituisce lista di (entry, codice_normalizzato) per ogni match, oppure [].

    Il codice è normalizzato in uppercase per garantire consistenza nei lookup.
    """
    if not query:
        return []

    matches = []
    for entry, pattern in _COMPILED:
        match = pattern.search(query)
        if match:
            code = match.group(0).upper()
            matches.append((entry, code))
    return matches
