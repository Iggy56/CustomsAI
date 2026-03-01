"""
CustomsAI – Deterministic Query Normalization Layer

Purpose:
Translate user operational language into normative legal language
before generating embeddings.

This improves semantic alignment between user questions
and formal regulatory text.

Fully deterministic.
No LLM involved.
"""

import re
from retrieval import Intent


# ------------------------------------------------------------
# Public normalization function
# ------------------------------------------------------------

def normalize_query(query: str, intent: Intent) -> str:
    """
    Deterministic transformation of the query
    depending on detected intent.
    """

    if not query:
        return query

    original_query = query.strip()

    # --------------------------------------------------------
    # PROCEDURAL → translate into normative register
    # --------------------------------------------------------

    if intent == Intent.PROCEDURAL:

        cleaned = _remove_procedural_phrases(original_query)

        # Transform into legal-style phrasing
        return f"obblighi e autorizzazioni relativi a {cleaned}"

    # --------------------------------------------------------
    # CLASSIFICATION → focus on normative classification
    # --------------------------------------------------------

    if intent == Intent.CLASSIFICATION:
        return f"classificazione normativa e allegati relativi a {original_query}"

    # --------------------------------------------------------
    # Default → no transformation
    # --------------------------------------------------------

    return original_query


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _remove_procedural_phrases(query: str) -> str:
    """
    Removes conversational fragments that
    reduce embedding alignment with legal text.
    Deterministic rule-based cleaning.
    """

    patterns = [
        r"cosa devo fare per",
        r"cosa devo fare",
        r"come devo",
        r"devo",
        r"come posso",
        r"posso",
        r"\?",
    ]

    cleaned = query.lower()

    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)

    return cleaned.strip()