"""
Structured lookups for CustomsAI.

This module performs deterministic database queries
against structured tables (nomenclature, dual_use_items).

It does NOT use embeddings.
It does NOT call the LLM.
It does NOT modify database schema.
"""

from typing import Optional, Dict, Any
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY


supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def lookup_nomenclature(code: str) -> Optional[Dict[str, Any]]:
    """
    Lookup CN code (8–10 digits).
    """
    response = (
        supabase
        .table("nomenclature")
        .select("*")
        .eq("goods_code", code)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def lookup_dual_use(code: str) -> Optional[Dict[str, Any]]:
    """
    Lookup Dual Use code (e.g. 1A001).
    """
    response = (
        supabase
        .table("dual_use_items")
        .select("*")
        .eq("code", code)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]
