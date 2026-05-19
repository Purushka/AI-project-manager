"""Embedding generation for ai-pm-skills.

Supports Ollama (local) and OpenAI as providers.
Default: try Ollama first, fall back to OpenAI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import requests

if TYPE_CHECKING:
    from shared.config import Config

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


def get_embedding(text: str, config: "Config") -> list[float]:
    if config.embedding_provider == "openai":
        return _embed_openai(text, config)

    try:
        return _embed_ollama(text, config)
    except EmbeddingError:
        logger.warning("Ollama embedding failed, falling back to OpenAI")
        return _embed_openai(text, config)


def get_embeddings_batch(texts: list[str], config: "Config") -> list[list[float]]:
    return [get_embedding(t, config) for t in texts]


def _embed_ollama(text: str, config: "Config") -> list[float]:
    url = f"{config.ollama_base_url}/api/embeddings"
    try:
        resp = requests.post(
            url,
            json={"model": config.ollama_model, "prompt": text},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        embedding = data.get("embedding")
        if not embedding:
            raise EmbeddingError(f"No embedding in Ollama response: {data}")
        return embedding
    except requests.RequestException as e:
        raise EmbeddingError(f"Ollama request failed: {e}") from e


def _embed_openai(text: str, config: "Config") -> list[float]:
    try:
        import openai
    except ImportError as e:
        raise EmbeddingError("openai package not installed") from e

    try:
        client = openai.OpenAI()
        resp = client.embeddings.create(
            model=config.openai_embedding_model,
            input=text,
        )
        return resp.data[0].embedding
    except Exception as e:
        raise EmbeddingError(f"OpenAI embedding failed: {e}") from e


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    dot = np.dot(va, vb)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))
