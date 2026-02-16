"""
Generate embedding for the user question.
This vector enables semantic search in the vector database.
"""

from openai import OpenAI

import config


def get_embedding(text: str) -> list[float]:
    """
    Return the embedding vector for the given text using the configured model.
    Raises on API or network errors; caller should handle exceptions.
    """
    if not text or not text.strip():
        raise ValueError("get_embedding requires non-empty text")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=text.strip(),
    )
    # Single input => single embedding.
    return response.data[0].embedding
