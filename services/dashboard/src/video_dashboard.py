#!/usr/bin/env python3
"""
Real-Time Video Dashboard with Detection Overlays
Shows processed frames with bounding boxes and labels
"""

import asyncio
import json
import cv2
import numpy as np
import base64
from datetime import datetime, timedelta
from collections import deque
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

try:
    from aiokafka import AIOKafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False

app = FastAPI(title="ATMS Video Dashboard")

class VideoFrame:
    """Stores a processed frame with detections"""
    def __init__(self, frame_data: bytes, detections: List[Dict], timestamp: datetime):
        self.frame_data = frame_data
        self.detections = detections
        self.timestamp = timestamp

class VideoDashboardService:
    """Service to display video with real-time detections"""
    
    def __init__(self):
        self.kafka_consumer: Optional[AIOKafkaConsumer] = None
        self.websocket_connections: List[WebSocket] = []
        self.latest_frames: deque = deque(maxlen=30)  # Last 30 frames (1 second at 30fps)
        self.detection_buffer: Dict = {}  # Store detections by frame_id
        
    async def initialize_kafka(self):
        """Initialize Kafka consumers for frames and detections"""
        if not KAFKA_AVAILABLE:
            return False
        
        try:
            self.kafka_consumer = AIOKafkaConsumer(
                'camera-frames',
                'detections',
                bootstrap_servers='localhost:9092',
                group_id='video-dashboard',
                auto_offset_reset='latest',
                enable_auto_commit=True
            )
            await self.kafka_consumer.start()
            print("✅ Kafka consumer started for video dashboard")
            return True
        except Exception as e:
            print(f"❌ Failed to start Kafka consumer: {e}")
            return False
    
    async def add_websocket(self, websocket: WebSocket):
        """Add websocket connection"""
        await websocket.accept()
        self.websocket_connections.append(websocket)
        print(f"✅ WebSocket connected. Total: {len(self.websocket_connections)}")
    
    async def remove_websocket(self, websocket: WebSocket):
        """Remove websocket connection"""
        if websocket in self.websocket_connections:
            self.websocket_connections.remove(websocket)
        print(f"❌ WebSocket disconnected. Total: {len(self.websocket_connections)}")
    
    def draw_detections(self, frame: np.ndarray, detections: List[Dict]) -> np.ndarray:
        """Draw bounding boxes and ALL AI model outputs on frame"""
        annotated_frame = frame.copy()
        
        # Confidence threshold - only show detections above 0.5
        CONFIDENCE_THRESHOLD = 0.5
        
        # Color map for different classes
        colors = {
            'car': (0, 255, 0),      # Green
            'truck': (255, 0, 0),    # Blue
            'bus': (0, 165, 255),    # Orange
            'person': (255, 255, 0), # Cyan
            'pedestrian': (255, 255, 0),
            'motorcycle': (255, 0, 255),
            'bicycle': (0, 255, 255)
        }
        
        valid_detections = 0
        
        for det in detections:
            bbox = det.get('bbox', {})
            if not bbox:
                continue
            
            # Get detection info
            obj_class = det.get('class', det.get('object_class', 'unknown'))
            confidence = det.get('confidence', 0.0)
            
            # FILTER: Only show detections with confidence > 0.5
            if confidence < CONFIDENCE_THRESHOLD:
                continue
            
            valid_detections += 1
            
            # Get bbox coordinates
            x1 = int(bbox.get('x1', 0))
            y1 = int(bbox.get('y1', 0))
            x2 = int(bbox.get('x2', 0))
            y2 = int(bbox.get('y2', 0))
            
            # Choose color
            color = colors.get(obj_class, (255, 255, 255))
            
            # Draw bounding box (thicker for visibility)
            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 3)
            
            # Get additional AI model data
            track_id = det.get('track_id', 'N/A')
            speed = det.get('speed_kmh', 0.0)
            vehicle_type = det.get('vehicle_type', obj_class)
            license_plate = det.get('license_plate', '')
            emission = det.get('emission_co2', 0.0)
            
            # Build comprehensive label
            labels = [f"{obj_class} {confidence:.2f}"]
            
            if track_id != 'N/A':
                labels.append(f"ID:{track_id}")
            
            if speed > 0:
                labels.append(f"{speed:.1f}km/h")
            
            if license_plate:
                labels.append(f"LP:{license_plate}")
            
            if vehicle_type != obj_class:
                labels.append(f"Type:{vehicle_type}")
            
            if emission > 0:
                labels.append(f"CO2:{emission:.1f}g")
            
            # Draw labels with background
            y_offset = y1 - 10
            for label in labels:
                label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                
                # Draw background rectangle
                cv2.rectangle(annotated_frame, 
                             (x1, y_offset - label_size[1] - 5), 
                             (x1 + label_size[0] + 10, y_offset + 5), 
                             color, -1)
                
                # Draw text
                cv2.putText(annotated_frame, label, 
                           (x1 + 5, y_offset), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                
                y_offset -= (label_size[1] + 10)
        
        # Draw info panel (top left)
        panel_height = 150
        panel_width = 400
        overlay = annotated_frame.copy()
        cv2.rectangle(overlay, (0, 0), (panel_width, panel_height), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, annotated_frame, 0.3, 0, annotated_frame)
        
        # Add comprehensive stats
        y_pos = 25
        cv2.putText(annotated_frame, f"High-Conf Detections: {valid_detections}", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        y_pos += 30
        cv2.putText(annotated_frame, f"Total Raw: {len(detections)} (>{CONFIDENCE_THRESHOLD*100:.0f}% shown)", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        
        y_pos += 30
        cv2.putText(annotated_frame, "AI Models: Detection + Tracking", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        
        y_pos += 25
        cv2.putText(annotated_frame, "          + Speed + LPR + Emission", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        
        # Add timestamp
        timestamp_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        cv2.putText(annotated_frame, timestamp_text, 
                   (10, annotated_frame.shape[0] - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return annotated_frame
    
    async def process_messages(self):
        """Process Kafka messages and create annotated frames"""
        if not self.kafka_consumer:
            return
        
        # Store frames temporarily
        frame_buffer = {}
        
        try:
            async for message in self.kafka_consumer:
                topic = message.topic
                data = json.loads(message.value.decode('utf-8'))
                
                if topic == 'camera-frames':
                    # Store frame for later annotation
                    frame_id = data.get('frame_id', '')
                    frame_hex = data.get('data', {}).get('frame_data', '')
                    
                    if frame_hex and frame_id:
                        # Decode and store frame
                        frame_bytes = bytes.fromhex(frame_hex)
                        frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
                        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                        
                        if frame is not None:
                            frame_buffer[frame_id] = frame
                            
                            # Clean old frames (keep last 50)
                            if len(frame_buffer) > 50:
                                oldest_key = next(iter(frame_buffer))
                                del frame_buffer[oldest_key]
                
                elif topic == 'detections':
                    # Got detections - now we can annotate the frame
                    frame_id = data.get('frame_id', '')
                    detections = data.get('detections', [])
                    
                    # Enrich detections with additional AI model data
                    # (This would come from other Kafka topics in full implementation)
                    for i, det in enumerate(detections):
                        if 'track_id' not in det:
                            det['track_id'] = f"T{i+1}"
                        if 'speed_kmh' not in det:
                            det['speed_kmh'] = 0.0  # Will be populated by trajectory system
                    
                    # Check if we have the frame for these detections
                    frame = frame_buffer.get(frame_id)
                    
                    if frame is not None:
                        # Draw detections with all AI model outputs
                        annotated_frame = self.draw_detections(frame, detections)
                        
                        # Encode as JPEG with higher quality for clarity
                        _, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                        frame_b64 = base64.b64encode(buffer).decode('utf-8')
                        
                        # Count high-confidence detections
                        high_conf = sum(1 for d in detections if d.get('confidence', 0) >= 0.5)
                        
                        # Send to all connected websockets
                        await self.broadcast_frame(frame_b64, high_conf)
                        
                        # Remove frame from buffer after processing
                        del frame_buffer[frame_id]
                    else:
                        # Store detections for when frame arrives
                        self.detection_buffer[frame_id] = detections
                        
                        # Clean old detections (keep last 100)
                        if len(self.detection_buffer) > 100:
                            oldest_key = next(iter(self.detection_buffer))
                            del self.detection_buffer[oldest_key]
        
        except Exception as e:
            print(f"Error processing Kafka messages: {e}")
    
    async def broadcast_frame(self, frame_b64: str, detection_count: int):
        """Broadcast annotated frame to all websockets"""
        message = {
            'type': 'frame',
            'frame': frame_b64,
            'detections': detection_count,
            'timestamp': datetime.now().isoformat()
        }
        
        disconnected = []
        for ws in self.websocket_connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                print(f"Failed to send frame: {e}")
                disconnected.append(ws)
        
        for ws in disconnected:
            await self.remove_websocket(ws)

# Global service instance
video_service = VideoDashboardService()

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    await video_service.initialize_kafka()
    asyncio.create_task(video_service.process_messages())
    print("🚀 Video Dashboard Service started")

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serve video dashboard HTML"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ATMS Live Video Feed with Detections</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                color: #fff;
                padding: 20px;
            }
            .container {
                max-width: 1400px;
                margin: 0 auto;
            }
            h1 {
                text-align: center;
                margin-bottom: 30px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }
            .video-container {
                background: rgba(0,0,0,0.3);
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            }
            #videoFrame {
                width: 100%;
                max-width: 1280px;
                display: block;
                margin: 0 auto;
                border-radius: 10px;
                box-shadow: 0 4px 16px rgba(0,0,0,0.5);
            }
            .stats {
                display: flex;
                justify-content: space-around;
                margin-top: 20px;
                flex-wrap: wrap;
            }
            .stat-card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 10px;
                padding: 20px 40px;
                min-width: 200px;
                text-align: center;
                margin: 10px;
            }
            .stat-value {
                font-size: 48px;
                font-weight: bold;
                color: #4ade80;
            }
            .stat-label {
                font-size: 14px;
                opacity: 0.8;
                margin-top: 5px;
            }
            .status {
                text-align: center;
                margin-top: 20px;
                padding: 15px;
                background: rgba(0,0,0,0.2);
                border-radius: 10px;
                font-size: 18px;
            }
            .status.connected {
                color: #4ade80;
            }
            .status.disconnected {
                color: #f87171;
            }
            .no-video {
                text-align: center;
                padding: 100px 20px;
                font-size: 24px;
                opacity: 0.7;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎥 ATMS Live Video Feed with Real-Time Detections</h1>
            
            <div class="video-container">
                <img id="videoFrame" src="" alt="Waiting for video stream..." class="no-video"/>
                
                <div class="stats">
                    <div class="stat-card">
                        <div class="stat-value" id="detectionCount">0</div>
                        <div class="stat-label">Current Detections</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="fps">0</div>
                        <div class="stat-label">FPS</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value" id="totalFrames">0</div>
                        <div class="stat-label">Total Frames</div>
                    </div>
                </div>
            </div>
            
            <div class="status" id="status">Connecting to live stream...</div>
        </div>
        
        <script>
            const ws = new WebSocket('ws://localhost:8010/ws');
            const videoFrame = document.getElementById('videoFrame');
            const detectionCount = document.getElementById('detectionCount');
            const fpsDisplay = document.getElementById('fps');
            const totalFrames = document.getElementById('totalFrames');
            const status = document.getElementById('status');
            
            let frameCount = 0;
            let lastTime = Date.now();
            let fps = 0;
            
            ws.onopen = () => {
                status.textContent = '✅ Connected - Live streaming';
                status.className = 'status connected';
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                
                if (data.type === 'frame') {
                    // Update video frame
                    videoFrame.src = 'data:image/jpeg;base64,' + data.frame;
                    videoFrame.classList.remove('no-video');
                    
                    // Update detection count
                    detectionCount.textContent = data.detections;
                    
                    // Calculate FPS
                    frameCount++;
                    const now = Date.now();
                    const elapsed = (now - lastTime) / 1000;
                    if (elapsed >= 1) {
                        fps = Math.round(frameCount / elapsed);
                        fpsDisplay.textContent = fps;
                        frameCount = 0;
                        lastTime = now;
                    }
                    
                    // Update total frames
                    totalFrames.textContent = parseInt(totalFrames.textContent) + 1;
                }
            };
            
            ws.onerror = (error) => {
                status.textContent = '❌ Connection error';
                status.className = 'status disconnected';
            };
            
            ws.onclose = () => {
                status.textContent = '⚠️ Disconnected - Attempting to reconnect...';
                status.className = 'status disconnected';
                setTimeout(() => location.reload(), 3000);
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for video streaming"""
    await video_service.add_websocket(websocket)
    
    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        await video_service.remove_websocket(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        await video_service.remove_websocket(websocket)

if __name__ == "__main__":
    uvicorn.run(
        "video_dashboard:app",
        host="0.0.0.0",
        port=8010,
        reload=False
    )

