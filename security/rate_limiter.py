"""
Rate Limiter
============
Redis-based rate limiting for API endpoints.
Falls back to in-memory limiting if Redis is not available.
"""

import time
from typing import Optional, Dict, Tuple
from collections import defaultdict, deque
import logging

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("Redis not available - using in-memory rate limiting")

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter using sliding window algorithm.
    Supports both Redis (distributed) and in-memory (local) modes.
    """
    
    def __init__(
        self,
        redis_client: Optional[Any] = None,
        default_limit: int = 100,
        default_window: int = 60
    ):
        """
        Initialize rate limiter.
        
        Args:
            redis_client: Redis client instance (optional)
            default_limit: Default requests per window
            default_window: Default window size in seconds
        """
        self.redis_client = redis_client
        self.use_redis = redis_client is not None and REDIS_AVAILABLE
        self.default_limit = default_limit
        self.default_window = default_window
        
        # In-memory storage (fallback)
        self.memory_store: Dict[str, deque] = defaultdict(lambda: deque())
        
        if self.use_redis:
            logger.info("Rate limiter using Redis (distributed)")
        else:
            logger.info("Rate limiter using in-memory storage (local only)")
    
    def is_allowed(
        self,
        key: str,
        limit: Optional[int] = None,
        window: Optional[int] = None
    ) -> Tuple[bool, int, int]:
        """
        Check if request is allowed.
        
        Args:
            key: Rate limit key (e.g., user_id, IP address)
            limit: Requests allowed per window (uses default if None)
            window: Window size in seconds (uses default if None)
            
        Returns:
            Tuple of (is_allowed, remaining_requests, reset_time)
        """
        limit = limit or self.default_limit
        window = window or self.default_window
        
        if self.use_redis:
            return self._check_redis(key, limit, window)
        else:
            return self._check_memory(key, limit, window)
    
    def _check_redis(self, key: str, limit: int, window: int) -> Tuple[bool, int, int]:
        """Check rate limit using Redis"""
        try:
            current_time = time.time()
            redis_key = f"ratelimit:{key}"
            
            # Use sliding window with sorted set
            pipe = self.redis_client.pipeline()
            
            # Remove expired entries
            pipe.zremrangebyscore(redis_key, 0, current_time - window)
            
            # Count current requests
            pipe.zcard(redis_key)
            
            # Add current request
            pipe.zadd(redis_key, {str(current_time): current_time})
            
            # Set expiration
            pipe.expire(redis_key, window)
            
            results = pipe.execute()
            count = results[1]
            
            # Check if limit exceeded
            is_allowed = count < limit
            
            if not is_allowed:
                # Remove the request we just added
                self.redis_client.zrem(redis_key, str(current_time))
            
            remaining = max(0, limit - count - (1 if is_allowed else 0))
            reset_time = int(current_time + window)
            
            return is_allowed, remaining, reset_time
            
        except Exception as e:
            logger.error(f"Redis rate limit check failed: {e}, falling back to memory")
            return self._check_memory(key, limit, window)
    
    def _check_memory(self, key: str, limit: int, window: int) -> Tuple[bool, int, int]:
        """Check rate limit using in-memory storage"""
        current_time = time.time()
        window_start = current_time - window
        
        # Get request history for this key
        requests = self.memory_store[key]
        
        # Remove expired requests
        while requests and requests[0] < window_start:
            requests.popleft()
        
        # Check limit
        count = len(requests)
        is_allowed = count < limit
        
        if is_allowed:
            # Add current request
            requests.append(current_time)
        
        remaining = max(0, limit - count - (1 if is_allowed else 0))
        reset_time = int(current_time + window)
        
        return is_allowed, remaining, reset_time
    
    def reset(self, key: str):
        """Reset rate limit for a key"""
        if self.use_redis:
            try:
                redis_key = f"ratelimit:{key}"
                self.redis_client.delete(redis_key)
            except Exception as e:
                logger.error(f"Failed to reset Redis key: {e}")
        else:
            self.memory_store.pop(key, None)
    
    def get_remaining(self, key: str, limit: Optional[int] = None, 
                     window: Optional[int] = None) -> int:
        """Get remaining requests for a key"""
        _, remaining, _ = self.is_allowed(key, limit, window)
        return remaining


def create_rate_limiter(
    redis_client: Optional[Any] = None,
    default_limit: int = 100,
    default_window: int = 60
) -> RateLimiter:
    """Create rate limiter instance"""
    return RateLimiter(
        redis_client=redis_client,
        default_limit=default_limit,
        default_window=default_window
    )

