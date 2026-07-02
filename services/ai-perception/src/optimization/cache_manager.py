"""
Caching Strategies for Performance Optimization
Week 11: Performance Optimization

Implements multi-level caching:
- In-memory LRU cache for recent detections
- Redis cache for distributed caching
- Model result caching
"""

import time
import hashlib
import logging
from typing import Optional, Dict, Any, List
from functools import lru_cache
from collections import OrderedDict

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None


class LRUCache:
    """
    Simple LRU cache implementation
    """
    
    def __init__(self, max_size: int = 100, ttl: Optional[float] = None):
        """
        Initialize LRU cache
        
        Args:
            max_size: Maximum number of items
            ttl: Time-to-live in seconds (None = no expiration)
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: Dict[str, float] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        if key not in self._cache:
            return None
        
        # Check TTL
        if self.ttl and time.time() - self._timestamps[key] > self.ttl:
            del self._cache[key]
            del self._timestamps[key]
            return None
        
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return self._cache[key]
    
    def set(self, key: str, value: Any):
        """Set value in cache"""
        # Remove oldest if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            del self._timestamps[oldest_key]
        
        self._cache[key] = value
        self._timestamps[key] = time.time()
    
    def clear(self):
        """Clear cache"""
        self._cache.clear()
        self._timestamps.clear()
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        return {
            'size': len(self._cache),
            'max_size': self.max_size,
            'ttl': self.ttl
        }


class CacheManager:
    """
    Multi-level cache manager for performance optimization
    """
    
    def __init__(
        self,
        enable_memory_cache: bool = True,
        enable_redis_cache: bool = False,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        memory_cache_size: int = 1000,
        memory_cache_ttl: Optional[float] = 300.0,  # 5 minutes
        redis_cache_ttl: Optional[float] = 3600.0  # 1 hour
    ):
        """
        Initialize cache manager
        
        Args:
            enable_memory_cache: Enable in-memory LRU cache
            enable_redis_cache: Enable Redis cache
            redis_host: Redis host
            redis_port: Redis port
            memory_cache_size: Memory cache size
            memory_cache_ttl: Memory cache TTL in seconds
            redis_cache_ttl: Redis cache TTL in seconds
        """
        self.enable_memory_cache = enable_memory_cache
        self.enable_redis_cache = enable_redis_cache and REDIS_AVAILABLE
        
        # Initialize memory cache
        if self.enable_memory_cache:
            self.memory_cache = LRUCache(max_size=memory_cache_size, ttl=memory_cache_ttl)
        else:
            self.memory_cache = None
        
        # Initialize Redis cache
        self.redis_client = None
        if self.enable_redis_cache:
            try:
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    decode_responses=False,  # Binary data
                    socket_connect_timeout=5
                )
                # Test connection
                self.redis_client.ping()
                logger.info(f"Redis cache connected: {redis_host}:{redis_port}")
            except Exception as e:
                logger.warning(f"Redis cache unavailable: {e}")
                self.enable_redis_cache = False
                self.redis_client = None
        
        self.redis_cache_ttl = redis_cache_ttl
        
        logger.info(
            f"CacheManager initialized: memory={enable_memory_cache}, "
            f"redis={self.enable_redis_cache}"
        )
    
    def _generate_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from arguments"""
        # Create hash from arguments
        key_data = f"{prefix}:{str(args)}:{str(sorted(kwargs.items()))}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"{prefix}:{key_hash}"
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache (checks memory first, then Redis)
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None
        """
        # Try memory cache first
        if self.memory_cache:
            value = self.memory_cache.get(key)
            if value is not None:
                return value
        
        # Try Redis cache
        if self.redis_client:
            try:
                value = self.redis_client.get(key)
                if value is not None:
                    # Deserialize (assuming pickle)
                    import pickle
                    value = pickle.loads(value)
                    
                    # Also store in memory cache for faster access
                    if self.memory_cache:
                        self.memory_cache.set(key, value)
                    
                    return value
            except Exception as e:
                logger.warning(f"Redis get error: {e}")
        
        return None
    
    def set(self, key: str, value: Any):
        """
        Set value in cache (stores in both memory and Redis)
        
        Args:
            key: Cache key
            value: Value to cache
        """
        # Store in memory cache
        if self.memory_cache:
            self.memory_cache.set(key, value)
        
        # Store in Redis cache
        if self.redis_client:
            try:
                import pickle
                serialized = pickle.dumps(value)
                self.redis_client.setex(key, int(self.redis_cache_ttl), serialized)
            except Exception as e:
                logger.warning(f"Redis set error: {e}")
    
    def get_detection_cache_key(self, frame_id: str, sensor_id: str) -> str:
        """Generate cache key for detection results"""
        return self._generate_key("detection", frame_id, sensor_id)
    
    def cache_detections(self, frame_id: str, sensor_id: str, detections: List[Any]):
        """Cache detection results"""
        key = self.get_detection_cache_key(frame_id, sensor_id)
        self.set(key, detections)
    
    def get_cached_detections(self, frame_id: str, sensor_id: str) -> Optional[List[Any]]:
        """Get cached detection results"""
        key = self.get_detection_cache_key(frame_id, sensor_id)
        return self.get(key)
    
    def clear(self):
        """Clear all caches"""
        if self.memory_cache:
            self.memory_cache.clear()
        
        if self.redis_client:
            try:
                # Clear only our keys (prefix-based)
                keys = self.redis_client.keys("detection:*")
                if keys:
                    self.redis_client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis clear error: {e}")
    
    def get_stats(self) -> dict:
        """Get cache statistics"""
        stats = {
            'memory_cache_enabled': self.enable_memory_cache,
            'redis_cache_enabled': self.enable_redis_cache
        }
        
        if self.memory_cache:
            stats['memory_cache'] = self.memory_cache.get_stats()
        
        if self.redis_client:
            try:
                info = self.redis_client.info('memory')
                stats['redis_cache'] = {
                    'used_memory': info.get('used_memory', 0),
                    'used_memory_human': info.get('used_memory_human', '0B')
                }
            except Exception as e:
                stats['redis_cache'] = {'error': str(e)}
        
        return stats

