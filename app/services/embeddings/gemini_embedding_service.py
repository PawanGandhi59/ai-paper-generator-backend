import logging
import random
import threading
import time
import uuid
from typing import List, Optional, Tuple

from google import genai
from google.genai import types

from app.core.config import settings
from app.core.rate_limiter import get_redis_client
from app.services.embeddings.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ImportError:
    GoogleGenerativeAIEmbeddings = None


LUA_RATE_LIMITER_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_rpm = tonumber(ARGV[3])
local max_tpm = tonumber(ARGV[4])
local tokens = tonumber(ARGV[5])
local req_id = ARGV[6]
local cutoff = now - window

-- 1. Purge expired entries older than window
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', cutoff)

-- 2. Calculate current RPM
local current_rpm = redis.call('ZCARD', KEYS[1])

-- 3. Calculate current TPM
local tpm_members = redis.call('ZRANGE', KEYS[2], 0, -1)
local current_tpm = 0
for i = 1, #tpm_members do
    local entry = tpm_members[i]
    local colon_pos = string.find(entry, ":")
    if colon_pos then
        local t_val = tonumber(string.sub(entry, colon_pos + 1))
        if t_val then
            current_tpm = current_tpm + t_val
        end
    end
end

-- 4. Check limits
if current_rpm >= max_rpm or (current_tpm + tokens) > max_tpm then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local oldest_time = now
    if #oldest > 1 then
        oldest_time = tonumber(oldest[2])
    end
    local wait_sec = math.max(0.5, window - (now - oldest_time) + 0.5)
    return {0, tostring(wait_sec), current_rpm, current_tpm}
end

-- 5. Record request
redis.call('ZADD', KEYS[1], now, req_id)
redis.call('ZADD', KEYS[2], now, req_id .. ":" .. tostring(tokens))
redis.call('EXPIRE', KEYS[1], math.ceil(window * 2))
redis.call('EXPIRE', KEYS[2], math.ceil(window * 2))

return {1, "0", current_rpm + 1, current_tpm + tokens}
"""


class RedisGeminiRateLimiter:
    """
    Distributed Redis-backed sliding-window rate limiter enforcing
    RPM (Requests Per Minute) and TPM (Tokens Per Minute) across all Celery workers.
    Falls back gracefully to process-local in-memory sliding window if Redis is unavailable.
    """

    def __init__(
        self,
        max_rpm: int = 90,
        max_tpm: int = 55_000,
        window_seconds: float = 60.0,
        redis_client=None,
    ):
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.window_seconds = window_seconds
        self._custom_redis = redis_client
        self._lua_sha = None
        # In-memory fallback structures
        self._fallback_history: List[Tuple[float, int]] = []
        self._fallback_lock = threading.Lock()

    def _get_r(self):
        if self._custom_redis is not None:
            return self._custom_redis
        try:
            return get_redis_client()
        except Exception:
            return None

    def acquire(self, token_count: int):
        """
        Proactively acquire capacity for `token_count` tokens.
        If limits are reached, sleeps until capacity becomes available.
        """
        r = self._get_r()
        if r is not None:
            try:
                self._acquire_redis(r, token_count)
                return
            except Exception as exc:
                logger.warning(f"Redis rate limiter exception ({exc}), falling back to in-memory rate limiter.")

        self._acquire_in_memory(token_count)

    def _acquire_redis(self, r, token_count: int):
        rpm_key = "gemini:embedding:rpm_zset"
        tpm_key = "gemini:embedding:tpm_zset"

        while True:
            now = time.time()
            req_id = uuid.uuid4().hex

            try:
                res = r.eval(
                    LUA_RATE_LIMITER_SCRIPT,
                    2,
                    rpm_key,
                    tpm_key,
                    str(now),
                    str(self.window_seconds),
                    str(self.max_rpm),
                    str(self.max_tpm),
                    str(token_count),
                    req_id,
                )
            except Exception as eval_exc:
                logger.warning(f"Failed to execute Redis Lua rate limit script: {eval_exc}")
                raise

            allowed = res[0]
            wait_sec = float(res[1])
            req_in_window = res[2]
            tok_in_window = res[3]

            if allowed == 1:
                break

            logger.info(
                f"Gemini embedding quota capacity reached. "
                f"requests_in_window={req_in_window}, tokens_in_window={tok_in_window}, "
                f"rpm_limit={self.max_rpm}, tpm_limit={self.max_tpm}. "
                f"Waiting {wait_sec:.2f} seconds before next request."
            )
            time.sleep(wait_sec)

    def _acquire_in_memory(self, token_count: int):
        with self._fallback_lock:
            while True:
                now = time.time()
                self._fallback_history = [(t, count) for (t, count) in self._fallback_history if now - t < self.window_seconds]

                current_rpm = len(self._fallback_history)
                current_tpm = sum(count for _, count in self._fallback_history)

                rpm_exceeded = current_rpm >= self.max_rpm
                tpm_exceeded = (current_tpm + token_count) > self.max_tpm

                if not rpm_exceeded and not tpm_exceeded:
                    self._fallback_history.append((now, token_count))
                    break

                oldest_time = self._fallback_history[0][0] if self._fallback_history else now
                sleep_needed = max(0.5, self.window_seconds - (now - oldest_time) + 0.5)

                logger.info(
                    f"Gemini embedding quota capacity reached (in-memory). "
                    f"requests_in_window={current_rpm}, tokens_in_window={current_tpm}, "
                    f"rpm_limit={self.max_rpm}, tpm_limit={self.max_tpm}. "
                    f"Waiting {sleep_needed:.2f} seconds before next request."
                )
                time.sleep(sleep_needed)


# Global rate-limiter instance shared across threads and worker calls
_rate_limiter = RedisGeminiRateLimiter(
    max_rpm=settings.GEMINI_EMBEDDING_MAX_RPM,
    max_tpm=settings.GEMINI_EMBEDDING_MAX_TPM,
    window_seconds=60.0,
)


class GeminiEmbeddingService(EmbeddingService):
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.client = None
        self.lc_embeddings = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not configured.")
            raise ValueError("GEMINI_API_KEY is missing. Gemini embedding service requires a valid API key.")

        try:
            if GoogleGenerativeAIEmbeddings:
                self.lc_embeddings = GoogleGenerativeAIEmbeddings(
                    model=self.model_name,
                    google_api_key=self.api_key,
                    output_dimensionality=self.dimension,
                )
            self.client = genai.Client(api_key=self.api_key)
        except Exception as exc:
            logger.error(f"Failed to initialize Gemini SDK/LangChain client: {exc}")
            raise RuntimeError(f"Failed to initialize Gemini Client: {exc}")

    def generate_embedding(self, text: str) -> List[float]:
        if not text or not text.strip():
            text = "empty text"

        res = self.generate_embeddings_batch([text])
        return res[0]

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if not self.api_key or (not self.client and not self.lc_embeddings):
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
                        if self.lc_embeddings:
                            sub_embeddings = self.lc_embeddings.embed_documents(sub_batch)
                        else:
                            contents = [{"parts": [{"text": t}]} for t in sub_batch]
                            res = self.client.models.embed_content(
                                model=self.model_name,
                                contents=contents,
                                config=types.EmbedContentConfig(output_dimensionality=self.dimension),
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
