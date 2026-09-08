import logging
import threading
import time
import uuid
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Shared Redis client connection pool
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    return _redis_client


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
    RPM (Requests Per Minute) and TPM (Tokens Per Minute) across all processes and workers.
    Falls back gracefully to process-local in-memory sliding window if Redis is unavailable.
    """

    def __init__(
        self,
        max_rpm: int = 90,
        max_tpm: int = 55_000,
        window_seconds: float = 60.0,
        redis_client: Optional[redis.Redis] = None,
        key_prefix: str = "gemini:embedding",
    ):
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self._custom_redis = redis_client
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
        rpm_key = f"{self.key_prefix}:rpm_zset"
        tpm_key = f"{self.key_prefix}:tpm_zset"

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
                f"Gemini quota capacity reached ({self.key_prefix}). "
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
                    f"Gemini quota capacity reached ({self.key_prefix}, in-memory). "
                    f"requests_in_window={current_rpm}, tokens_in_window={current_tpm}, "
                    f"rpm_limit={self.max_rpm}, tpm_limit={self.max_tpm}. "
                    f"Waiting {sleep_needed:.2f} seconds before next request."
                )
                time.sleep(sleep_needed)


class RateLimiter:
    @staticmethod
    def check_rag_rate_limit(user_id: UUID) -> bool:
        """
        Enforce atomic Redis per-user sliding window rate limit for RAG queries.
        Returns True if within limit, raises HTTP 429 with Retry-After header if exceeded.
        """
        requests_limit = settings.RAG_RATE_LIMIT_REQUESTS
        window_seconds = settings.RAG_RATE_LIMIT_WINDOW_SECONDS

        current_time = int(time.time())
        window_bucket = current_time // window_seconds
        rate_limit_key = f"rag:query:{user_id}:{window_bucket}"
        retry_after_seconds = max(1, window_seconds - (current_time % window_seconds))

        try:
            r = get_redis_client()
            pipe = r.pipeline()
            pipe.incr(rate_limit_key)
            pipe.expire(rate_limit_key, window_seconds + 5)
            results = pipe.execute()
            current_count = results[0]

            if current_count > requests_limit:
                logger.warning(
                    f"RAG rate limit exceeded for user_id={user_id}: {current_count}/{requests_limit} in window {window_seconds}s"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {requests_limit} RAG queries per {window_seconds} seconds allowed. Please retry in {retry_after_seconds} seconds.",
                    headers={"Retry-After": str(retry_after_seconds)},
                )

            return True

        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Redis rate limiter connection error: {exc}. Permitting request (fail-open).")
            return True
