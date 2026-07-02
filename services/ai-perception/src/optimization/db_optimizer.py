"""
Database Query Optimization
Week 11: Performance Optimization

Optimizations:
- Connection pooling
- Query batching
- Prepared statements
- Index optimization
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
import asyncio
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None


class DatabaseConnectionPool:
    """
    Optimized connection pool for PostgreSQL
    """
    
    def __init__(
        self,
        dsn: str,
        min_size: int = 5,
        max_size: int = 20,
        max_queries: int = 50000,
        max_inactive_connection_lifetime: float = 300.0
    ):
        """
        Initialize connection pool
        
        Args:
            dsn: Database connection string
            min_size: Minimum pool size
            max_size: Maximum pool size
            max_queries: Max queries per connection before recycling
            max_inactive_connection_lifetime: Max idle time before closing
        """
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.pool: Optional[asyncpg.Pool] = None
        
        self.pool_config = {
            'min_size': min_size,
            'max_size': max_size,
            'max_queries': max_queries,
            'max_inactive_connection_lifetime': max_inactive_connection_lifetime,
            'command_timeout': 30.0,
            'server_settings': {
                'application_name': 'atms-ai-perception',
                'jit': 'off'  # Disable JIT for faster queries
            }
        }
        
        logger.info(
            f"DatabaseConnectionPool initialized: "
            f"min_size={min_size}, max_size={max_size}"
        )
    
    async def initialize(self):
        """Initialize connection pool"""
        if not ASYNCPG_AVAILABLE:
            logger.error("asyncpg not available")
            return False
        
        try:
            self.pool = await asyncpg.create_pool(
                self.dsn,
                **self.pool_config
            )
            logger.info("Database connection pool initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            return False
    
    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire connection from pool"""
        if not self.pool:
            raise RuntimeError("Pool not initialized")
        
        async with self.pool.acquire() as connection:
            yield connection
    
    async def execute(self, query: str, *args):
        """Execute query using pool"""
        async with self.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args):
        """Fetch rows using pool"""
        async with self.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args):
        """Fetch single row using pool"""
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args):
        """Fetch single value using pool"""
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args)


class QueryOptimizer:
    """
    Query optimization utilities
    """
    
    def __init__(self, pool: DatabaseConnectionPool):
        """
        Initialize query optimizer
        
        Args:
            pool: Database connection pool
        """
        self.pool = pool
        self.prepared_statements: Dict[str, Any] = {}
    
    async def prepare_statement(self, name: str, query: str):
        """
        Prepare statement for reuse
        
        Args:
            name: Statement name
            query: SQL query
        """
        async with self.pool.acquire() as conn:
            stmt = await conn.prepare(query)
            self.prepared_statements[name] = stmt
            logger.debug(f"Prepared statement: {name}")
    
    async def execute_prepared(self, name: str, *args):
        """
        Execute prepared statement
        
        Args:
            name: Statement name
            *args: Query parameters
            
        Returns:
            Query result
        """
        if name not in self.prepared_statements:
            raise ValueError(f"Prepared statement '{name}' not found")
        
        stmt = self.prepared_statements[name]
        async with self.pool.acquire() as conn:
            return await conn.fetch(stmt, *args)
    
    async def batch_insert(
        self,
        table: str,
        columns: List[str],
        values: List[List[Any]],
        batch_size: int = 1000
    ):
        """
        Batch insert for better performance
        
        Args:
            table: Table name
            columns: Column names
            values: List of value lists
            batch_size: Number of rows per batch
        """
        if not values:
            return
        
        columns_str = ', '.join(columns)
        placeholders = ', '.join([f'${i+1}' for i in range(len(columns))])
        
        query = f"""
            INSERT INTO {table} ({columns_str})
            VALUES ({placeholders})
        """
        
        # Process in batches
        for i in range(0, len(values), batch_size):
            batch = values[i:i+batch_size]
            
            async with self.pool.acquire() as conn:
                await conn.executemany(query, batch)
            
            logger.debug(f"Inserted batch {i//batch_size + 1}: {len(batch)} rows")
    
    async def create_indexes(self):
        """
        Create optimized indexes for common queries
        """
        indexes = [
            # Detection indexes
            "CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_detections_frame_id ON detections(frame_id)",
            "CREATE INDEX IF NOT EXISTS idx_detections_sensor_id ON detections(sensor_id)",
            "CREATE INDEX IF NOT EXISTS idx_detections_object_class ON detections(object_class)",
            "CREATE INDEX IF NOT EXISTS idx_detections_timestamp_class ON detections(timestamp, object_class)",
            
            # Traffic metrics indexes
            "CREATE INDEX IF NOT EXISTS idx_traffic_metrics_timestamp ON traffic_metrics(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_traffic_metrics_intersection_id ON traffic_metrics(intersection_id)",
            
            # Trajectory indexes
            "CREATE INDEX IF NOT EXISTS idx_trajectories_track_id ON trajectories(track_id)",
            "CREATE INDEX IF NOT EXISTS idx_trajectories_timestamp ON trajectories(timestamp)",
        ]
        
        for index_query in indexes:
            try:
                await self.pool.execute(index_query)
                logger.debug(f"Created index: {index_query.split()[-1]}")
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")
        
        logger.info("Database indexes created/verified")


class AsyncQueryExecutor:
    """
    Execute queries asynchronously with batching
    """
    
    def __init__(self, pool: DatabaseConnectionPool, max_concurrent: int = 10):
        """
        Initialize async query executor
        
        Args:
            pool: Database connection pool
            max_concurrent: Maximum concurrent queries
        """
        self.pool = pool
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_async(self, query: str, *args):
        """
        Execute query asynchronously with concurrency limit
        
        Args:
            query: SQL query
            *args: Query parameters
        """
        async with self.semaphore:
            return await self.pool.execute(query, *args)
    
    async def fetch_async(self, query: str, *args):
        """
        Fetch rows asynchronously
        
        Args:
            query: SQL query
            *args: Query parameters
        """
        async with self.semaphore:
            return await self.pool.fetch(query, *args)
    
    async def execute_batch(self, queries: List[Tuple[str, Tuple]]):
        """
        Execute batch of queries in parallel
        
        Args:
            queries: List of (query, args) tuples
        """
        tasks = [self.execute_async(query, *args) for query, args in queries]
        return await asyncio.gather(*tasks, return_exceptions=True)

