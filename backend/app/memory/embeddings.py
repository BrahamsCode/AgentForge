"""Embedders pluggables: OpenAI, Ollama y un fallback determinista sin red."""

import hashlib
import logging
import math
from typing import Protocol

import httpx

from app.config import get_settings
from app.memory.models import EMBEDDING_DIMS

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    dimensions = EMBEDDING_DIMS

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=get_settings().openai_api_key)
        response = await client.embeddings.create(
            model=self.model, input=texts, dimensions=self.dimensions
        )
        return [item.embedding for item in response.data]


class OllamaEmbedder:
    dimensions = EMBEDDING_DIMS

    def __init__(self, model: str = "nomic-embed-text") -> None:
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        base = get_settings().ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base}/api/embed", json={"model": self.model, "input": texts}
            )
            response.raise_for_status()
            vectors = response.json().get("embeddings", [])
        return [self._fit(v) for v in vectors]

    def _fit(self, vector: list[float]) -> list[float]:
        if len(vector) == self.dimensions:
            return vector
        logger.warning(
            "Embedding de dimensión %d ajustado a %d", len(vector), self.dimensions
        )
        if len(vector) > self.dimensions:
            return vector[: self.dimensions]
        return vector + [0.0] * (self.dimensions - len(vector))


class HashEmbedder:
    """Determinista y sin red: hashing de n-gramas a buckets + normalización L2.

    Solo para desarrollo y tests; la calidad semántica es baja pero estable.
    """

    dimensions = EMBEDDING_DIMS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = text.lower().split()
        grams = tokens + [" ".join(p) for p in zip(tokens, tokens[1:])]
        for gram in grams:
            digest = hashlib.sha256(gram.encode()).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAIEmbedder()
    logger.warning("Sin OPENAI_API_KEY: usando HashEmbedder (solo dev/tests)")
    return HashEmbedder()
