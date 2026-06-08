"""Embedding generation for ai-pm-skills.

Supports Ollama (local), OpenAI, and DashScope (Alibaba Cloud) as providers.
Default: try configured provider first, fall back through the chain.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from shared.config import Config

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 10


class EmbeddingError(Exception):
    pass


def get_embedding(text: str, config: "Config") -> list[float]:
    if config.embedding_provider == "dashscope":
        return _embed_dashscope(text, config)
    if config.embedding_provider == "openai":
        return _embed_openai(text, config)

    try:
        return _embed_ollama(text, config)
    except EmbeddingError:
        logger.warning("Ollama embedding failed, falling back to OpenAI")
        return _embed_openai(text, config)


def get_embeddings_batch(texts: list[str], config: "Config") -> list[list[float]]:
    """Batch embed texts. Uses native batch API when available."""
    if config.embedding_provider == "dashscope":
        return _embed_dashscope_batch(texts, config)
    if config.embedding_provider == "openai":
        return _embed_openai_batch(texts, config)
    return [get_embedding(t, config) for t in texts]


def _embed_ollama(text: str, config: "Config") -> list[float]:
    import requests

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
    except Exception as e:
        raise EmbeddingError(f"Ollama request failed: {e}") from e


def _embed_openai(text: str, config: "Config") -> list[float]:
    return _embed_openai_batch([text], config)[0]


def _embed_openai_batch(texts: list[str], config: "Config") -> list[list[float]]:
    try:
        import openai
    except ImportError as e:
        raise EmbeddingError("openai package not installed") from e

    client = openai.OpenAI(
        base_url=config.openai_base_url,
        api_key=config.openai_api_key,
    )

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        try:
            resp = client.embeddings.create(
                model=config.openai_embedding_model,
                input=batch,
            )
            all_embeddings.extend(e.embedding for e in resp.data)
        except Exception as e:
            raise EmbeddingError(f"OpenAI embedding failed: {e}") from e

    return all_embeddings


def _embed_dashscope(text: str, config: "Config") -> list[float]:
    return _embed_dashscope_batch([text], config)[0]


def _embed_dashscope_batch(texts: list[str], config: "Config") -> list[list[float]]:
    try:
        import openai
    except ImportError as e:
        raise EmbeddingError("openai package not installed") from e

    headers = {}
    if config.dashscope_workspace:
        headers["X-DashScope-WorkSpace"] = config.dashscope_workspace

    client = openai.OpenAI(
        base_url=config.dashscope_base_url,
        api_key=config.dashscope_api_key,
        default_headers=headers,
    )

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i:i + EMBEDDING_BATCH_SIZE]
        try:
            resp = client.embeddings.create(
                model=config.dashscope_embedding_model,
                input=batch,
            )
            all_embeddings.extend(e.embedding for e in resp.data)
        except Exception as e:
            raise EmbeddingError(f"DashScope embedding failed: {e}") from e

    return all_embeddings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a)
    vb = np.array(b)
    dot = np.dot(va, vb)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def cosine_similarity_matrix(embeddings: list[list[float]]) -> np.ndarray:
    """Compute full pairwise cosine similarity matrix."""
    mat = np.array(embeddings)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normalized = mat / norms
    return normalized @ normalized.T
