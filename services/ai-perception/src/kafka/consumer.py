"""
AI Perception Service - Kafka Consumer
Week 2: Professional Kafka Consumer for Camera Frames
"""
import asyncio
import json
from typing import Optional, Callable, Awaitable
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.base import SensorDataMessage

logger = get_logger(__name__)

try:
    from aiokafka import AIOKafkaConsumer
    from aiokafka.errors import KafkaError
except ImportError:
    AIOKafkaConsumer = None
    KafkaError = Exception
    logger.warning("aiokafka not available, using mock mode")


class KafkaFrameConsumer:
    """
    Professional Kafka Consumer for Camera Frames
    
    Features:
    - Async message consumption
    - Automatic deserialization
    - Error handling and retry logic
    - Message filtering
    - Performance monitoring
    """
    
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "ai-perception-group",
        topics: list = None,
        auto_offset_reset: str = "latest"
    ):
        """
        Initialize Kafka consumer
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
            group_id: Consumer group ID
            topics: List of topics to subscribe to
            auto_offset_reset: Where to start reading (earliest/latest)
        """
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.topics = topics or ["camera-frames"]
        self.auto_offset_reset = auto_offset_reset
        
        self.consumer: Optional[AIOKafkaConsumer] = None
        self.is_running = False
        self.message_count = 0
        self.error_count = 0
        
        self.logger = logger.bind(
            group_id=group_id,
            bootstrap_servers=bootstrap_servers
        )
    
    async def start(self):
        """Start Kafka consumer"""
        if AIOKafkaConsumer is None:
            self.logger.warning("Kafka not available, using mock mode")
            self.is_running = True
            return
        
        try:
            self.consumer = AIOKafkaConsumer(
                *self.topics,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                auto_offset_reset=self.auto_offset_reset,
                enable_auto_commit=True,
                value_deserializer=self._deserialize_message
            )
            
            await self.consumer.start()
            self.is_running = True
            self.logger.info("Kafka consumer started", topics=self.topics)
            
        except Exception as e:
            self.logger.error(f"Failed to start Kafka consumer: {e}")
            self.is_running = False
            raise
    
    async def stop(self):
        """Stop Kafka consumer"""
        self.is_running = False
        
        if self.consumer:
            try:
                await self.consumer.stop()
                self.logger.info("Kafka consumer stopped")
            except Exception as e:
                self.logger.error(f"Error stopping Kafka consumer: {e}")
    
    def _deserialize_message(self, value: bytes) -> dict:
        """
        Deserialize JSON message
        
        Args:
            value: Message bytes
            
        Returns:
            Deserialized message dict
        """
        try:
            return json.loads(value.decode('utf-8'))
        except Exception as e:
            self.logger.error(f"Deserialization error: {e}")
            return {}
    
    async def consume(
        self,
        callback: Callable[[SensorDataMessage], Awaitable[None]]
    ):
        """
        Consume messages and call callback
        
        Args:
            callback: Async callback function for each message
        """
        if not self.is_running:
            self.logger.warning("Consumer not running")
            return
        
        # Mock mode
        if self.consumer is None:
            self.logger.info("Running in mock mode, no messages to consume")
            # Keep running but don't process messages
            while self.is_running:
                await asyncio.sleep(1)
            return
        
        try:
            self.logger.info("Starting message consumption...")
            
            async for message in self.consumer:
                try:
                    # Parse message
                    data = message.value
                    
                    # Convert to SensorDataMessage
                    sensor_message = SensorDataMessage(**data)
                    
                    # Call callback
                    await callback(sensor_message)
                    
                    self.message_count += 1
                    
                    if self.message_count % 100 == 0:
                        self.logger.debug(
                            "Messages consumed",
                            count=self.message_count,
                            topic=message.topic
                        )
                    
                except Exception as e:
                    self.error_count += 1
                    self.logger.error(
                        "Error processing message",
                        error=str(e),
                        error_count=self.error_count
                    )
                    
        except asyncio.CancelledError:
            self.logger.info("Message consumption cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Consumption error: {e}", exc_info=True)
    
    async def get_stats(self) -> dict:
        """Get consumer statistics"""
        return {
            "is_running": self.is_running,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "topics": self.topics,
            "group_id": self.group_id
        }

