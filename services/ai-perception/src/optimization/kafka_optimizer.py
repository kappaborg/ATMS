"""
Kafka Consumer Optimization
Week 11: Performance Optimization

Optimizations:
- Batch processing
- Connection pooling
- Consumer group optimization
- Message prefetching
"""

import logging
from typing import List, Optional, Dict, Any
import asyncio
from collections import deque

logger = logging.getLogger(__name__)

try:
    from aiokafka import AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    AIOKafkaConsumer = None


class OptimizedKafkaConsumer:
    """
    Optimized Kafka consumer with batch processing and connection pooling
    """
    
    def __init__(
        self,
        bootstrap_servers: str,
        topics: List[str],
        group_id: str,
        batch_size: int = 10,
        batch_timeout_ms: int = 100,
        max_poll_records: int = 50,
        fetch_min_bytes: int = 1024,
        fetch_max_wait_ms: int = 500
    ):
        """
        Initialize optimized Kafka consumer
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
            topics: List of topics to consume
            group_id: Consumer group ID
            batch_size: Number of messages to batch
            batch_timeout_ms: Max time to wait for batch
            max_poll_records: Max records per poll
            fetch_min_bytes: Min bytes to fetch
            fetch_max_wait_ms: Max wait time for fetch
        """
        self.bootstrap_servers = bootstrap_servers
        self.topics = topics
        self.group_id = group_id
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms / 1000.0  # Convert to seconds
        self.max_poll_records = max_poll_records
        
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.message_buffer: deque = deque(maxlen=batch_size * 2)
        self.batch_lock = asyncio.Lock()
        self.is_running = False
        
        # Consumer configuration
        self.consumer_config = {
            'bootstrap_servers': bootstrap_servers,
            'group_id': group_id,
            'auto_offset_reset': 'latest',
            'enable_auto_commit': True,
            'auto_commit_interval_ms': 1000,
            'max_poll_records': max_poll_records,
            'fetch_min_bytes': fetch_min_bytes,
            'fetch_max_wait_ms': fetch_max_wait_ms,
            'session_timeout_ms': 30000,
            'heartbeat_interval_ms': 10000,
            'max_poll_interval_ms': 300000,
            'value_deserializer': lambda m: m  # Keep raw bytes for performance
        }
        
        logger.info(
            f"OptimizedKafkaConsumer initialized: "
            f"topics={topics}, batch_size={batch_size}, "
            f"max_poll_records={max_poll_records}"
        )
    
    async def start(self):
        """Start consumer"""
        if not KAFKA_AVAILABLE:
            logger.error("aiokafka not available")
            return False
        
        try:
            self.consumer = AIOKafkaConsumer(
                *self.topics,
                **self.consumer_config
            )
            await self.consumer.start()
            self.is_running = True
            logger.info("Optimized Kafka consumer started")
            return True
        except Exception as e:
            logger.error(f"Failed to start Kafka consumer: {e}")
            return False
    
    async def stop(self):
        """Stop consumer"""
        self.is_running = False
        if self.consumer:
            try:
                await self.consumer.stop()
                logger.info("Kafka consumer stopped")
            except Exception as e:
                logger.error(f"Error stopping consumer: {e}")
    
    async def get_messages_batch(self) -> List[Any]:
        """
        Get batch of messages (optimized)
        
        Returns:
            List of messages
        """
        if not self.consumer or not self.is_running:
            return []
        
        messages = []
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Poll for messages with timeout
            while len(messages) < self.batch_size:
                elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
                
                if elapsed >= self.batch_timeout_ms * 1000 and messages:
                    # Return partial batch if timeout reached
                    break
                
                # Poll with timeout
                poll_timeout = max(0.1, (self.batch_timeout_ms * 1000 - elapsed) / 1000.0)
                msg_pack = await self.consumer.getmany(
                    timeout_ms=int(poll_timeout * 1000),
                    max_records=self.max_poll_records
                )
                
                if not msg_pack:
                    if messages:
                        break  # Return what we have
                    await asyncio.sleep(0.01)  # Small delay if no messages
                    continue
                
                # Extract messages from partitions
                for topic_partition, partition_messages in msg_pack.items():
                    messages.extend(partition_messages)
                    
                    if len(messages) >= self.batch_size:
                        break
                
                # If we have enough messages, return
                if len(messages) >= self.batch_size:
                    break
            
            logger.debug(f"Fetched {len(messages)} messages in batch")
            return messages[:self.batch_size]  # Limit to batch size
            
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            return messages
    
    async def process_batch(
        self,
        processor_func,
        messages: List[Any]
    ) -> List[Any]:
        """
        Process batch of messages in parallel
        
        Args:
            processor_func: Async function to process messages
            messages: List of messages to process
            
        Returns:
            List of processed results
        """
        if not messages:
            return []
        
        # Process messages in parallel (with limit to avoid overwhelming)
        max_concurrent = min(10, len(messages))
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_limit(msg):
            async with semaphore:
                try:
                    return await processor_func(msg)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    return None
        
        # Create tasks for all messages
        tasks = [process_with_limit(msg) for msg in messages]
        
        # Wait for all to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out errors
        successful = [r for r in results if r is not None and not isinstance(r, Exception)]
        
        logger.debug(f"Processed {len(successful)}/{len(messages)} messages successfully")
        return successful
    
    async def consume_batch_loop(
        self,
        processor_func,
        max_messages: Optional[int] = None
    ):
        """
        Consume and process messages in batches (optimized loop)
        
        Args:
            processor_func: Async function to process messages
            max_messages: Maximum messages to process (None = unlimited)
        """
        messages_processed = 0
        
        logger.info("Starting optimized batch consumption loop")
        
        while self.is_running:
            try:
                # Get batch of messages
                messages = await self.get_messages_batch()
                
                if not messages:
                    await asyncio.sleep(0.1)  # Small delay if no messages
                    continue
                
                # Process batch in parallel
                results = await self.process_batch(processor_func, messages)
                
                messages_processed += len(results)
                
                # Check limit
                if max_messages and messages_processed >= max_messages:
                    logger.info(f"Reached message limit: {max_messages}")
                    break
                
                # Log progress
                if messages_processed % 100 == 0:
                    logger.info(f"Processed {messages_processed} messages")
                
            except asyncio.CancelledError:
                logger.info("Consumption loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in consumption loop: {e}", exc_info=True)
                await asyncio.sleep(1)  # Wait before retrying
        
        logger.info(f"Consumption loop ended. Total processed: {messages_processed}")


class KafkaConnectionPool:
    """
    Connection pool for Kafka producers/consumers
    """
    
    def __init__(self, max_connections: int = 5):
        """
        Initialize connection pool
        
        Args:
            max_connections: Maximum number of connections
        """
        self.max_connections = max_connections
        self.connections: deque = deque(maxlen=max_connections)
        self.active_connections = 0
        self.lock = asyncio.Lock()
    
    async def get_connection(self, connection_factory):
        """
        Get connection from pool or create new one
        
        Args:
            connection_factory: Function to create new connection
            
        Returns:
            Connection object
        """
        async with self.lock:
            if self.connections:
                return self.connections.popleft()
            
            if self.active_connections < self.max_connections:
                self.active_connections += 1
                return await connection_factory()
            
            # Wait for connection to be available
            # In practice, you might want to implement a queue here
            return await connection_factory()
    
    async def return_connection(self, connection):
        """
        Return connection to pool
        
        Args:
            connection: Connection object to return
        """
        async with self.lock:
            if len(self.connections) < self.max_connections:
                self.connections.append(connection)
            else:
                # Pool full, close connection
                if hasattr(connection, 'close'):
                    await connection.close()
                self.active_connections -= 1

