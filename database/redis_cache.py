#!/usr/bin/env python3
"""
Redis Cache Manager
==================

Provides caching layer for ATMS system using Redis.

Features:
- Key-value caching
- TTL (Time To Live) support
- JSON serialization
- Connection pooling
- Async operations
"""

import asyncio
import json
import logging
from typing import Any, Optional
from datetime import timedelta

try:
    import aioredis
    AIOREDIS_AVAILABLE = True
except ImportError:
    try:
        import redis.asyncio as aioredis
        AIOREDIS_AVAILABLE = True
    except ImportError:
        AIOREDIS_AVAILABLE = False
        logging.warning("redis not available - install with: pip install redis[hiredis]")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RedisCache:
    """Async Redis cache manager"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: Optional[str] = None,  # No password by default for local dev
        db: int = 0,
        default_ttl: int = 60  # seconds
    ):
        """Initialize Redis cache"""
        self.host = host
        self.port = port
        self.password = password
        self.db = db
        self.default_ttl = default_ttl
        self.redis: Optional[aioredis.Redis] = None
        
    async def connect(self):
        """Connect to Redis"""
        if not AIOREDIS_AVAILABLE:
            raise RuntimeError("redis not installed")
        
        try:
            # Build Redis URL with optional password
            if self.password:
                redis_url = f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
            else:
                redis_url = f"redis://{self.host}:{self.port}/{self.db}"
            
            self.redis = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            # Test connection
            await self.redis.ping()
            logger.info(f"✅ Redis connected: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            logger.info("Redis connection closed")
    
    # ============================================
    # Basic Operations
    # ============================================
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key"""
        if not self.redis:
            await self.connect()
        
        try:
            value = await self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Error getting key {key}: {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value with optional TTL"""
        if not self.redis:
            await self.connect()
        
        try:
            serialized = json.dumps(value)
            ttl = ttl or self.default_ttl
            
            if ttl:
                await self.redis.setex(key, ttl, serialized)
            else:
                await self.redis.set(key, serialized)
            
            return True
        except Exception as e:
            logger.error(f"Error setting key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key"""
        if not self.redis:
            await self.connect()
        
        try:
            await self.redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error deleting key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self.redis:
            await self.connect()
        
        try:
            return await self.redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Error checking key {key}: {e}")
            return False
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Set TTL for key"""
        if not self.redis:
            await self.connect()
        
        try:
            return await self.redis.expire(key, ttl)
        except Exception as e:
            logger.error(f"Error setting TTL for key {key}: {e}")
            return False
    
    # ============================================
    # ATMS-Specific Caching
    # ============================================
    
    async def cache_detection(
        self,
        detection_id: str,
        detection_data: dict,
        ttl: int = 60
    ):
        """Cache detection data"""
        key = f"detection:{detection_id}"
        await self.set(key, detection_data, ttl)
    
    async def get_detection(self, detection_id: str) -> Optional[dict]:
        """Get cached detection"""
        key = f"detection:{detection_id}"
        return await self.get(key)
    
    async def cache_trajectory(
        self,
        track_id: int,
        trajectory_data: dict,
        ttl: int = 300  # 5 minutes
    ):
        """Cache trajectory data"""
        key = f"trajectory:{track_id}"
        await self.set(key, trajectory_data, ttl)
    
    async def get_trajectory(self, track_id: int) -> Optional[dict]:
        """Get cached trajectory"""
        key = f"trajectory:{track_id}"
        return await self.get(key)
    
    async def cache_traffic_metrics(
        self,
        intersection_id: int,
        metrics: dict,
        ttl: int = 30  # 30 seconds
    ):
        """Cache traffic metrics"""
        key = f"metrics:{intersection_id}"
        await self.set(key, metrics, ttl)
    
    async def get_traffic_metrics(
        self,
        intersection_id: int
    ) -> Optional[dict]:
        """Get cached traffic metrics"""
        key = f"metrics:{intersection_id}"
        return await self.get(key)
    
    async def cache_decision(
        self,
        decision_id: str,
        decision_data: dict,
        ttl: int = 120  # 2 minutes
    ):
        """Cache decision data"""
        key = f"decision:{decision_id}"
        await self.set(key, decision_data, ttl)
    
    async def get_decision(self, decision_id: str) -> Optional[dict]:
        """Get cached decision"""
        key = f"decision:{decision_id}"
        return await self.get(key)
    
    # ============================================
    # Rate Limiting
    # ============================================
    
    async def check_rate_limit(
        self,
        identifier: str,
        max_requests: int = 100,
        window_seconds: int = 60
    ) -> tuple[bool, int]:
        """
        Check rate limit for identifier
        
        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        if not self.redis:
            await self.connect()
        
        key = f"ratelimit:{identifier}"
        
        try:
            # Increment counter
            count = await self.redis.incr(key)
            
            # Set expiry on first request
            if count == 1:
                await self.redis.expire(key, window_seconds)
            
            remaining = max(0, max_requests - count)
            is_allowed = count <= max_requests
            
            return is_allowed, remaining
            
        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return True, max_requests  # Allow on error
    
    # ============================================
    # Session Management
    # ============================================
    
    async def create_session(
        self,
        session_id: str,
        session_data: dict,
        ttl: int = 3600  # 1 hour
    ):
        """Create session"""
        key = f"session:{session_id}"
        await self.set(key, session_data, ttl)
    
    async def get_session(self, session_id: str) -> Optional[dict]:
        """Get session data"""
        key = f"session:{session_id}"
        return await self.get(key)
    
    async def delete_session(self, session_id: str):
        """Delete session"""
        key = f"session:{session_id}"
        await self.delete(key)
    
    # ============================================
    # Statistics
    # ============================================
    
    async def increment_counter(self, counter_name: str, amount: int = 1) -> int:
        """Increment counter"""
        if not self.redis:
            await self.connect()
        
        try:
            key = f"counter:{counter_name}"
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Error incrementing counter {counter_name}: {e}")
            return 0
    
    async def get_counter(self, counter_name: str) -> int:
        """Get counter value"""
        if not self.redis:
            await self.connect()
        
        try:
            key = f"counter:{counter_name}"
            value = await self.redis.get(key)
            return int(value) if value else 0
        except Exception as e:
            logger.error(f"Error getting counter {counter_name}: {e}")
            return 0
    
    # ============================================
    # Cache Warming
    # ============================================
    
    async def warm_cache(self, data: dict[str, Any]):
        """Warm cache with initial data"""
        logger.info("Warming cache...")
        
        for key, value in data.items():
            await self.set(key, value)
        
        logger.info(f"Cache warmed with {len(data)} keys")
    
    # ============================================
    # Cache Invalidation
    # ============================================
    
    async def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern"""
        if not self.redis:
            await self.connect()
        
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                await self.redis.delete(*keys)
                logger.info(f"Invalidated {len(keys)} keys matching {pattern}")
        except Exception as e:
            logger.error(f"Error invalidating pattern {pattern}: {e}")

# Global cache instance
cache = RedisCache()

async def test_cache():
    """Test Redis cache"""
    print("🧪 Testing Redis Cache...")
    
    try:
        await cache.connect()
        print("✅ Redis connected successfully")
        
        # Test basic operations
        await cache.set("test_key", {"value": "test_data"}, ttl=10)
        print("✅ Set test key")
        
        value = await cache.get("test_key")
        print(f"✅ Got test key: {value}")
        
        exists = await cache.exists("test_key")
        print(f"✅ Key exists: {exists}")
        
        # Test ATMS-specific caching
        await cache.cache_traffic_metrics(
            intersection_id=1,
            metrics={"total_vehicles": 10, "average_speed": 45.5}
        )
        print("✅ Cached traffic metrics")
        
        metrics = await cache.get_traffic_metrics(intersection_id=1)
        print(f"✅ Retrieved metrics: {metrics}")
        
        # Test rate limiting
        is_allowed, remaining = await cache.check_rate_limit(
            "test_user",
            max_requests=10,
            window_seconds=60
        )
        print(f"✅ Rate limit check: allowed={is_allowed}, remaining={remaining}")
        
        await cache.close()
        print("✅ Redis connection closed")
        
    except Exception as e:
        print(f"❌ Cache test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_cache())
