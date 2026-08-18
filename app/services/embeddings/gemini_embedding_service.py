import hashlib
import logging
import math
from typing import List, Optional

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.embeddings.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


def generate_deterministic_mock_vector(text: str, dimension: int = 768) -> List[float]:
    """Generate a deterministic 768-dim unit vector for testing when API key is missing."""
    seed_hash = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for i in range(dimension):
        byte_val = seed_hash[i % len(seed_hash)]
        val = (byte_val / 255.0) - 0.5 + math.sin(i + len(text))
        values.append(val)

    # Normalize to unit length
    magnitude = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / magnitude for v in values]


class GeminiEmbeddingService(EmbeddingService):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.client = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not configured. GeminiEmbeddingService running in deterministic mock mode.")
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            logger.error(f"Failed to initialize Gemini SDK client: {exc}")
            # Raise exception if real API key is provided but initialization fails
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def generate_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            text = "empty text"

        res = self.generate_embeddings_batch([text])
        return res[0]

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # Mock mode when API key is missing
        if not self.api_key or not self.client:
            return [generate_deterministic_mock_vector(t, self.dimension) for t in texts]

        # Real API mode when GEMINI_API_KEY is present
        try:
            # Format contents array for google.genai batch embed
            contents = [{"parts": [{"text": t if t and t.strip() else "empty text"}]} for t in texts]
            res = self.client.models.embed_content(
                model=self.model_name,
                contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=self.dimension),
            )

            if not res or not hasattr(res, "embeddings") or not res.embeddings:
                raise RuntimeError("Gemini embedding API returned empty response.")

            embeddings = [emb.values for emb in res.embeddings]

            # Validate batch count and dimensions
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"Gemini embedding batch count mismatch: expected {len(texts)}, got {len(embeddings)}"
                )

            for idx, vec in enumerate(embeddings):
                if len(vec) != self.dimension:
                    raise RuntimeError(
                        f"Gemini embedding dimension mismatch at index {idx}: expected {self.dimension}, got {len(vec)}"
                    )

            return embeddings

        except Exception as exc:
            logger.error(f"Gemini embedding API error: {str(exc)}")
            # Do NOT swallow exception in real mode! Re-raise for Celery retries.
            raise RuntimeError(f"Gemini embedding API failure: {str(exc)}")
