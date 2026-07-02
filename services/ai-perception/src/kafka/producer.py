"""
AI Perception Service - Kafka Producer
Week 2: Professional Kafka Producer for Detections
"""
import json
from typing import List, Optional, Dict
from datetime import datetime
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent))
from shared.utils.logger import get_logger
from shared.models.detection import Detection, DetectionMessage, TrafficMetrics

logger = get_logger(__name__)

try:
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaError
except ImportError:
    AIOKafkaProducer = None
    KafkaError = Exception


class KafkaDetectionProducer:
    """
    Professional Kafka Producer for Detections
    
    Features:
    - Async message production
    - Automatic serialization
    - Error handling and retry
    - Batching support
    - Performance monitoring
    """
    
    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "ai-perception",
        compression_type: str = "gzip"
    ):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self.compression_type = compression_type
        
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
                value_serializer=self._serialize_message,
                acks='all',
                enable_idempotence=True,  # Exactly-once semantics (includes automatic retries)
                request_timeout_ms=30000,  # 30 seconds
                metadata_max_age_ms=300000  # 5 minutes
            )
            
            await self.producer.start()
            self.is_connected = True
            self.logger.info("Kafka producer started")
            
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
    
    def _serialize_message(self, message) -> bytes:
        """Serialize message to JSON bytes"""
        try:
            if hasattr(message, 'model_dump'):
                data = message.model_dump(mode='json')
            elif hasattr(message, 'dict'):
                data = message.dict()
            else:
                data = message
            
            return json.dumps(data, default=str).encode('utf-8')
        except Exception as e:
            self.logger.error(f"Serialization error: {e}")
            raise
    
    async def send_detections(
        self,
        topic: str,
        detections: List[Detection],
        frame_id: str,
        sensor_id: str,
        frame_width: int,
        frame_height: int,
        processing_time_ms: float,
        model_name: str,
        model_version: str,
        intersection_id: int = 1
    ) -> bool:
        """
        Send detections to Kafka topic
        
        Args:
            topic: Kafka topic
            detections: List of Detection objects
            frame_id: Frame identifier
            sensor_id: Sensor identifier
            frame_width: Frame width
            frame_height: Frame height
            processing_time_ms: Processing time in milliseconds
            model_name: Model name
            model_version: Model version
            intersection_id: Intersection ID
            
        Returns:
            bool: True if sent successfully
        """
        if not self.is_connected:
            self.logger.warning("Producer not connected")
            return False
        
        try:
            # Count objects by class
            objects_by_class = {}
            for det in detections:
                # Handle both enum and string cases
                if hasattr(det.object_class, 'value'):
                    class_name = det.object_class.value
                else:
                    class_name = str(det.object_class)
                objects_by_class[class_name] = objects_by_class.get(class_name, 0) + 1
            
            # Create DetectionMessage
            message = DetectionMessage(
                service_name="ai-perception",
                intersection_id=intersection_id,
                frame_id=frame_id,
                sensor_id=sensor_id,
                sensor_type="camera",
                detections=detections,
                frame_width=frame_width,
                frame_height=frame_height,
                processing_time_ms=processing_time_ms,
                model_name=model_name,
                model_version=model_version,
                total_objects=len(detections),
                objects_by_class=objects_by_class
            )
            
            # Mock mode
            if self.producer is None:
                self.message_count += 1
                self.logger.debug(
                    "Mock message sent",
                    topic=topic,
                    message_id=message.message_id,
                    num_detections=len(detections)
                )
                return True
            
            # Log detection details before sending (for debugging)
            if self.message_count % 50 == 0 or len(detections) > 0:
                # Sample first detection to verify all fields
                if detections:
                    sample_det = detections[0]
                    self.logger.info(
                        "📤 Sending detections to Kafka",
                        topic=topic,
                        num_detections=len(detections),
                        sample_detection={
                            'class': sample_det.object_class.value if hasattr(sample_det.object_class, 'value') else str(sample_det.object_class),
                            'confidence': sample_det.confidence,
                            'has_brand': sample_det.vehicle_brand is not None,
                            'has_plate': sample_det.license_plate is not None,
                            'has_speed': sample_det.speed is not None and sample_det.speed > 0,
                            'has_emission': sample_det.emission_co2 is not None and sample_det.emission_co2 > 0,
                            'has_track_id': sample_det.track_id is not None,
                            'has_multiview': sample_det.multiview_confidence is not None and sample_det.multiview_confidence > 0
                        }
                    )
            
            # Serialize message to verify format
            try:
                serialized = message.model_dump(mode='json')
                detections_in_msg = serialized.get('detections', [])
                if detections_in_msg and self.message_count % 50 == 0:
                    first_det = detections_in_msg[0]
                    self.logger.debug(
                        "✅ Message serialized",
                        detection_keys=list(first_det.keys()),
                        has_bbox='bbox' in first_det,
                        bbox_keys=list(first_det.get('bbox', {}).keys()) if isinstance(first_det.get('bbox'), dict) else 'N/A'
                    )
            except Exception as ser_error:
                self.logger.warning(f"Serialization check error: {ser_error}")
            
            # Send message
            future = await self.producer.send(
                topic=topic,
                value=message,
                key=sensor_id.encode('utf-8')
            )
            
            metadata = await future
            
            self.message_count += 1
            self.logger.debug(
                "Detections sent",
                topic=topic,
                partition=metadata.partition,
                offset=metadata.offset,
                num_detections=len(detections)
            )
            
            return True
            
        except Exception as e:
            self.error_count += 1
            self.logger.error(
                "Error sending detections",
                topic=topic,
                error=str(e),
                error_count=self.error_count
            )
            return False
    
    async def send_traffic_metrics(
        self,
        topic: str,
        metrics: TrafficMetrics
    ) -> bool:
        """
        Send traffic metrics to Kafka
        
        Args:
            topic: Kafka topic
            metrics: TrafficMetrics object
            
        Returns:
            bool: True if sent successfully
        """
        if not self.is_connected:
            return False
        
        try:
            # Mock mode
            if self.producer is None:
                self.logger.debug("Mock metrics sent", topic=topic)
                return True
            
            # Send message
            await self.producer.send(
                topic=topic,
                value=metrics
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending metrics: {e}")
            return False
    
    async def send_emission_data(
        self,
        topic: str,
        emission_data: List[Dict],
        frame_id: str,
        sensor_id: str,
        intersection_id: int = 1
    ) -> bool:
        """Send emission data to Kafka"""
        if not self.is_connected:
            return False
        
        try:
            message = {
                'frame_id': frame_id,
                'sensor_id': sensor_id,
                'intersection_id': intersection_id,
                'timestamp': datetime.utcnow().isoformat(),
                'emissions': emission_data
            }
            
            if self.producer is None:
                self.logger.debug("Mock emission data sent", topic=topic, count=len(emission_data))
                return True
            
            await self.producer.send(topic=topic, value=message, key=sensor_id.encode('utf-8'))
            self.message_count += 1
            return True
        except Exception as e:
            self.logger.error(f"Error sending emission data: {e}")
            return False
    
    async def send_license_plates(
        self,
        topic: str,
        plate_data: List[Dict],
        frame_id: str,
        sensor_id: str,
        intersection_id: int = 1
    ) -> bool:
        """Send license plate data to Kafka"""
        if not self.is_connected:
            return False
        
        try:
            message = {
                'frame_id': frame_id,
                'sensor_id': sensor_id,
                'intersection_id': intersection_id,
                'timestamp': datetime.utcnow().isoformat(),
                'license_plates': plate_data
            }
            
            if self.producer is None:
                self.logger.debug("Mock license plate data sent", topic=topic, count=len(plate_data))
                return True
            
            await self.producer.send(topic=topic, value=message, key=sensor_id.encode('utf-8'))
            self.message_count += 1
            return True
        except Exception as e:
            self.logger.error(f"Error sending license plate data: {e}")
            return False
    
    async def send_trajectory_data(
        self,
        topic: str,
        trajectory_data: List[Dict],
        frame_id: str,
        sensor_id: str,
        intersection_id: int = 1
    ) -> bool:
        """Send trajectory data to Kafka"""
        if not self.is_connected:
            return False
        
        try:
            message = {
                'frame_id': frame_id,
                'sensor_id': sensor_id,
                'intersection_id': intersection_id,
                'timestamp': datetime.utcnow().isoformat(),
                'trajectories': trajectory_data
            }
            
            if self.producer is None:
                self.logger.debug("Mock trajectory data sent", topic=topic, count=len(trajectory_data))
                return True
            
            await self.producer.send(topic=topic, value=message, key=sensor_id.encode('utf-8'))
            self.message_count += 1
            return True
        except Exception as e:
            self.logger.error(f"Error sending trajectory data: {e}")
            return False
    
    async def send_trajectory_anomalies(
        self,
        topic: str,
        anomalies: List[Dict],
        frame_id: str,
        sensor_id: str,
        intersection_id: int = 1
    ) -> bool:
        """Send trajectory anomalies to Kafka"""
        if not self.is_connected:
            return False
        
        try:
            message = {
                'frame_id': frame_id,
                'sensor_id': sensor_id,
                'intersection_id': intersection_id,
                'timestamp': datetime.utcnow().isoformat(),
                'anomalies': anomalies
            }
            
            if self.producer is None:
                self.logger.debug("Mock anomaly data sent", topic=topic, count=len(anomalies))
                return True
            
            await self.producer.send(topic=topic, value=message, key=sensor_id.encode('utf-8'))
            self.message_count += 1
            return True
        except Exception as e:
            self.logger.error(f"Error sending trajectory anomalies: {e}")
            return False
    
    async def flush(self):
        """Flush pending messages"""
        if self.producer:
            try:
                await self.producer.flush()
            except Exception as e:
                self.logger.error(f"Error flushing producer: {e}")
    
    async def get_stats(self) -> dict:
        """Get producer statistics"""
        return {
            "is_connected": self.is_connected,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "bootstrap_servers": self.bootstrap_servers
        }

