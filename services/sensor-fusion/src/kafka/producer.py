"""
Sensor Fusion Service - Kafka Producer
Week 1: Professional Kafka Producer with Error Handling & Optimization
"""
import asyncio
import json
from typing import Optional, Dict, Any
from datetime import datetime
import sys
from pathlib import Path

try:
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaError
except ImportError:
    # Fallback for development without Kafka
    AIOKafkaProducer = None
    KafkaError = Exception

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.base import SensorDataMessage, CameraFrame

logger = get_logger(__name__)


class KafkaProducerManager:
    """
    Professional Kafka Producer Manager
    
    Features:
    - Async message production
    - Automatic serialization
    - Error handling and retry logic
    - Performance monitoring
    - Batch processing support
    """
    
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "sensor-fusion",
        compression_type: str = "gzip",
        max_batch_size: int = 16384,
        linger_ms: int = 10
    ):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self.compression_type = compression_type
        self.max_batch_size = max_batch_size
        self.linger_ms = linger_ms
        
        self.producer: Optional[AIOKafkaProducer] = None
        self.is_connected = False
        self.message_count = 0
        self.error_count = 0
        
        self.logger = logger.bind(
            client_id=client_id,
            bootstrap_servers=bootstrap_servers
        )
    
    async def start(self):
        """Start Kafka producer"""
        if AIOKafkaProducer is None:
            self.logger.warning("Kafka not available, using mock mode")
            self.is_connected = True
            return
        
        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                client_id=self.client_id,
                compression_type=self.compression_type,
                max_batch_size=self.max_batch_size,
                linger_ms=self.linger_ms,
                value_serializer=self._serialize_message,
                acks='all',  # Wait for all replicas
                enable_idempotence=True,  # Exactly-once semantics (includes automatic retries)
                request_timeout_ms=30000,  # 30 seconds
                metadata_max_age_ms=300000  # 5 minutes
            )
            
            await self.producer.start()
            self.is_connected = True
            self.logger.info("Kafka producer started successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to start Kafka producer: {e}")
            self.is_connected = False
            raise
    
    async def stop(self):
        """Stop Kafka producer"""
        if self.producer:
            try:
                await self.producer.stop()
                self.is_connected = False
                self.logger.info("Kafka producer stopped")
            except Exception as e:
                self.logger.error(f"Error stopping Kafka producer: {e}")
    
    def _serialize_message(self, message: Any) -> bytes:
        """
        Serialize message to JSON bytes
        
        Args:
            message: Message object (Pydantic model or dict)
            
        Returns:
            JSON bytes
        """
        try:
            if hasattr(message, 'model_dump'):
                # Pydantic v2 model
                data = message.model_dump(mode='json')
            elif hasattr(message, 'dict'):
                # Pydantic v1 model
                data = message.dict()
            else:
                # Regular dict
                data = message
            
            return json.dumps(data, default=str).encode('utf-8')
        
        except Exception as e:
            self.logger.error(f"Serialization error: {e}")
            raise
    
    async def send_message(
        self,
        topic: str,
        message: Any,
        key: Optional[str] = None,
        partition: Optional[int] = None
    ) -> bool:
        """
        Send message to Kafka topic
        
        Args:
            topic: Kafka topic name
            message: Message to send (Pydantic model or dict)
            key: Optional message key
            partition: Optional partition number
            
        Returns:
            bool: True if sent successfully
        """
        if not self.is_connected:
            self.logger.warning("Producer not connected, message not sent")
            return False
        
        try:
            # Mock mode (Kafka not available)
            if self.producer is None:
                self.message_count += 1
                self.logger.debug(
                    "Mock message sent",
                    topic=topic,
                    message_id=getattr(message, 'message_id', 'unknown')
                )
                return True
            
            # Prepare key
            key_bytes = key.encode('utf-8') if key else None
            
            # Send message
            future = await self.producer.send(
                topic=topic,
                value=message,
                key=key_bytes,
                partition=partition
            )
            
            # Get metadata
            metadata = await future
            
            self.message_count += 1
            self.logger.debug(
                "Message sent successfully",
                topic=topic,
                partition=metadata.partition,
                offset=metadata.offset,
                message_count=self.message_count
            )
            
            return True
            
        except KafkaError as e:
            self.error_count += 1
            self.logger.error(
                "Kafka error sending message",
                topic=topic,
                error=str(e),
                error_count=self.error_count
            )
            return False
            
        except Exception as e:
            self.error_count += 1
            self.logger.error(
                "Unexpected error sending message",
                topic=topic,
                error=str(e),
                error_count=self.error_count
            )
            return False
    
    async def send_camera_frame(
        self,
        topic: str,
        camera_frame: CameraFrame,
        intersection_id: int
    ) -> bool:
        """
        Send camera frame as sensor data message
        
        Args:
            topic: Kafka topic
            camera_frame: CameraFrame object
            intersection_id: Intersection ID
            
        Returns:
            bool: True if sent successfully
        """
        try:
            # Create sensor data message
            sensor_message = SensorDataMessage(
                service_name="sensor-fusion",
                intersection_id=intersection_id,
                sensor_type="camera",
                sensor_id=camera_frame.sensor_id,
                frame_id=camera_frame.frame_id,
                sequence_number=self.message_count,
                data={
                    "width": camera_frame.width,
                    "height": camera_frame.height,
                    "format": camera_frame.format,
                    "fps": camera_frame.fps,
                    "frame_data": camera_frame.frame_data.hex()  # Convert bytes to hex
                },
                metadata={
                    "timestamp": camera_frame.timestamp.isoformat(),
                    "sensor_id": camera_frame.sensor_id
                }
            )
            
            # Send to Kafka
            return await self.send_message(
                topic=topic,
                message=sensor_message,
                key=camera_frame.sensor_id
            )
            
        except Exception as e:
            self.logger.error(f"Error sending camera frame: {e}")
            return False
    
    async def send_batch(
        self,
        topic: str,
        messages: list,
        keys: Optional[list] = None
    ) -> int:
        """
        Send batch of messages
        
        Args:
            topic: Kafka topic
            messages: List of messages
            keys: Optional list of keys
            
        Returns:
            int: Number of messages sent successfully
        """
        sent_count = 0
        
        for i, message in enumerate(messages):
            key = keys[i] if keys and i < len(keys) else None
            if await self.send_message(topic, message, key):
                sent_count += 1
        
        return sent_count
    
    async def flush(self):
        """Flush all pending messages"""
        if self.producer:
            try:
                await self.producer.flush()
                self.logger.debug("Producer flushed")
            except Exception as e:
                self.logger.error(f"Error flushing producer: {e}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get producer statistics"""
        return {
            "is_connected": self.is_connected,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "bootstrap_servers": self.bootstrap_servers,
            "client_id": self.client_id
        }

