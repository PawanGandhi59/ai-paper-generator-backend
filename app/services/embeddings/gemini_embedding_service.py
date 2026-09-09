import logging
import random
import time
from typing import List, Optional, Union

from google import genai
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import settings
from app.core.rate_limiter import (
    LUA_RATE_LIMITER_SCRIPT,
    RedisGeminiRateLimiter,
    get_redis_client,
)
from app.services.ai.gemini_service import _extract_retry_delay
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

        try:
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            logger.warning(f"Failed to initialize google.genai Client for token counting: {exc}")

    def count_tokens(self, texts: Union[str, List[str]]) -> int:
        """
        Calculate exact token count for the embedding model using Google's countTokens API.
        Falls back to local character estimation (~4 chars/token) if offline or unavailable.
        """
        if not texts:
            return 0

        contents = [texts] if isinstance(texts, str) else texts
        if self.client and hasattr(self.client, "models"):
            try:
                res = self.client.models.count_tokens(
                    model=self.model_name,
                    contents=contents,
                )
                if res and hasattr(res, "total_tokens") and res.total_tokens:
                    return int(res.total_tokens)
            except Exception as exc:
                logger.debug(f"Google count_tokens API call failed ({exc}); falling back to local estimation.")

        total_chars = sum(len(t) for t in contents)
        return max(10, total_chars // 4)

    def generate_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            text = "empty text"

        embedder = self.embeddings or self.lc_embeddings
        if embedder:
            tokens = self.count_tokens(text)
            _rate_limiter.acquire(token_count=tokens, request_count=1)
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
                # Calculate exact token count using Google's token counting API
                batch_tokens = self.count_tokens(sub_batch)

                # Proactive distributed rate limiter acquire (accounting for every chunk as 1 Google request and exact tokens)
                _rate_limiter.acquire(token_count=batch_tokens, request_count=len(sub_batch))

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
                            # Extract Google's exact retry delay if present, with jitter fallback
                            jitter = random.uniform(1.0, 3.0)
                            sleep_time = _extract_retry_delay(exc_str, default_delay=backoff + jitter)
                            # Broadcast global cooldown to Redis so all workers pause during Google's cooldown
                            _rate_limiter.set_cooldown(sleep_time)
                            logger.warning(
                                f"Gemini embedding request received 429. Setting global cooldown of {sleep_time:.2f}s and retrying (attempt {attempt + 1}/{max_retries})..."
                            )
                            time.sleep(sleep_time)
                            backoff = min(60.0, backoff * 1.5)
                            # Re-acquire sliding window rate limit slot before attempting retry
                            _rate_limiter.acquire(token_count=batch_tokens, request_count=len(sub_batch))
                        else:
                            logger.error(f"Gemini embedding error on batch starting index {i}: {exc_str}")
                            raise RuntimeError(f"Gemini embedding API failure: {exc_str}")

                if not sub_embeddings:
                    raise RuntimeError(f"Failed to generate embeddings for batch starting index {i}")

                all_embeddings.extend(sub_embeddings)

                # Smooth pacing between batches to prevent triggering Google's burst-rate limiter
                pacing_delay = getattr(settings, "GEMINI_INTER_REQUEST_DELAY_SECONDS", 0.5)
                if pacing_delay > 0 and i + batch_size < len(clean_texts):
                    time.sleep(pacing_delay)

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
