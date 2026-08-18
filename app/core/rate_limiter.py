import logging
import time
from uuid import UUID

from fastapi import HTTPException, status
import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Shared Redis client connection pool
_redis_client: redis.Redis = None


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    return _redis_client


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
