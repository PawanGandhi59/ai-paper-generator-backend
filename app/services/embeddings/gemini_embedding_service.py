import logging
import random
import time
from typing import List, Optional

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import settings
from app.core.rate_limiter import (
    LUA_RATE_LIMITER_SCRIPT,
    RedisGeminiRateLimiter,
    get_redis_client,
)
from app.services.embeddings.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# Global rate-limiter instance for document embeddings
_rate_limiter = RedisGeminiRateLimiter(
    max_rpm=settings.GEMINI_EMBEDDING_MAX_RPM,
    max_tpm=settings.GEMINI_EMBEDDING_MAX_TPM,
    window_seconds=60.0,
    key_prefix="gemini:embedding",
)


class GeminiEmbeddingService(EmbeddingService):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.embeddings = None
        self.lc_embeddings = None
        self.client = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not configured.")
            raise ValueError("GEMINI_API_KEY is missing. Gemini embedding service requires a valid API key.")

        try:
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model=self.model_name,
                google_api_key=self.api_key,
                output_dimensionality=self.dimension,
            )
            self.lc_embeddings = self.embeddings
            logger.info(f"GeminiEmbeddingService (LangChain) initialized with model: {self.model_name}")
        except Exception as exc:
            logger.error(f"Failed to initialize LangChain GoogleGenerativeAIEmbeddings: {exc}")
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def generate_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            text = "empty text"

        embedder = self.embeddings or self.lc_embeddings
        if embedder:
            _rate_limiter.acquire(max(10, len(text) // 4))
            try:
                return embedder.embed_query(text)
            except Exception as exc:
                logger.error(f"Gemini embedding error: {exc}")
                raise RuntimeError(f"Gemini embedding API failure: {str(exc)}") from exc

        res = self.generate_embeddings_batch([text])
        return res[0]

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        embedder = self.embeddings or self.lc_embeddings
        if not self.api_key or (not embedder and not self.client):
            raise ValueError("GEMINI_API_KEY is missing. Gemini embedding service requires a valid API key.")

        try:
            clean_texts = [t if t and t.strip() else "empty text" for t in texts]
            batch_size = 25
            all_embeddings = []

            for i in range(0, len(clean_texts), batch_size):
                sub_batch = clean_texts[i : i + batch_size]
                # Conservative token estimation: ~4 characters per token
                estimated_tokens = max(10, sum(len(t) // 4 for t in sub_batch))

                # Proactive distributed rate limiter acquire
                _rate_limiter.acquire(estimated_tokens)

                max_retries = 8
                backoff = 10.0
                sub_embeddings = None

                for attempt in range(max_retries):
                    try:
                        if embedder:
                            sub_embeddings = embedder.embed_documents(sub_batch)
                        elif hasattr(self, "client") and self.client is not None and hasattr(self.client, "models"):
                            contents = [{"parts": [{"text": t}]} for t in sub_batch]
                            res = self.client.models.embed_content(
                                model=self.model_name,
                                contents=contents,
                            )
                            if not res or not hasattr(res, "embeddings") or not res.embeddings:
                                raise RuntimeError("Gemini embedding API returned empty response.")
                            sub_embeddings = [emb.values for emb in res.embeddings]
                        break
                    except Exception as exc:
                        exc_str = str(exc)
                        if ("429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower()) and attempt < max_retries - 1:
                            # Parse Retry-After if present in exception
                            jitter = random.uniform(1.0, 3.0)
                            sleep_time = backoff + jitter
                            logger.warning(
                                f"Gemini embedding request received 429. Retrying in {sleep_time:.2f} seconds (attempt {attempt + 1}/{max_retries})..."
                            )
                            time.sleep(sleep_time)
                            backoff = min(60.0, backoff * 1.5)
                        else:
                            logger.error(f"Gemini embedding error on batch starting index {i}: {exc_str}")
                            raise RuntimeError(f"Gemini embedding API failure: {exc_str}")

                if not sub_embeddings:
                    raise RuntimeError(f"Failed to generate embeddings for batch starting index {i}")

                all_embeddings.extend(sub_embeddings)

            if len(all_embeddings) != len(texts):
                raise RuntimeError(
                    f"Gemini embedding batch count mismatch: expected {len(texts)}, got {len(all_embeddings)}"
                )

            for idx, vec in enumerate(all_embeddings):
                if len(vec) != self.dimension:
                    raise RuntimeError(
                        f"Gemini embedding dimension mismatch at index {idx}: expected {self.dimension}, got {len(vec)}"
                    )

            return all_embeddings

        except Exception as exc:
            logger.error(f"Gemini embedding API error: {str(exc)}")
            raise RuntimeError(f"Gemini embedding API failure: {str(exc)}")
