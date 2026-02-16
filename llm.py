"""
Call the LLM with the retrieved context to produce a cited answer.
Handles API errors and enforces max context length to avoid token overflow.
"""

from openai import OpenAI, APIError, APIConnectionError

import config
import prompt as prompt_module


def generate_answer(question: str, context: str) -> str:
    """
    Generate the answer using only the provided context.
    Raises on API/network errors or if context is too long.
    """
    if len(context) > config.MAX_CONTEXT_CHARS:
        raise ValueError(
            f"Contesto troppo lungo ({len(context)} caratteri). "
            f"Limite: {config.MAX_CONTEXT_CHARS}. Ridurre TOP_K o MAX_CONTEXT_CHARS."
        )
    messages = prompt_module.build_messages(question, context)
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=0.0,
    )
    return (response.choices[0].message.content or "").strip()
