#!/usr/bin/env python3
"""
Database Access Layer
====================

Provides easy access to PostgreSQL database for ATMS system.

Features:
- Connection pooling
- Async operations
- CRUD operations for all tables
- Transaction management
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logging.warning("asyncpg not available - install with: pip install asyncpg")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseManager:
    """Async PostgreSQL database manager"""
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "atms",
        user: str = "atms_user",
        password: str = "atms_password",
        min_size: int = 10,
        max_size: int = 20
    ):
        """Initialize database manager"""
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.min_size = min_size
        self.max_size = max_size
        self.pool: Optional[asyncpg.Pool] = None
        
    async def connect(self):
        """Create connection pool"""
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError("asyncpg not installed")
        
        try:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self.min_size,
                max_size=self.max_size,
                command_timeout=60
            )
            logger.info(f"Database pool created: {self.database}@{self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise
    
    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database pool closed")
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire connection from pool"""
        if not self.pool:
            await self.connect()
        
        async with self.pool.acquire() as connection:
            yield connection
    
    # ============================================
    # Detections
    # ============================================
    
    async def insert_detection(
        self,
        intersection_id: int,
        camera_id: int,
        frame_id: str,
        object_class: str,
        confidence: float,
        bbox: Dict[str, float]
    ) -> str:
        """Insert detection record"""
        query = """
            INSERT INTO detections (
                intersection_id, camera_id, frame_id, object_class, confidence,
                bbox_x1, bbox_y1, bbox_x2, bbox_y2
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                intersection_id, camera_id, frame_id, object_class, confidence,
                bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2']
            )
            return str(result)
    
    async def get_recent_detections(
        self,
        intersection_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get recent detections"""
        if intersection_id:
            query = """
                SELECT * FROM detections
                WHERE intersection_id = $1
                ORDER BY detection_timestamp DESC
                LIMIT $2
            """
            args = (intersection_id, limit)
        else:
            query = """
                SELECT * FROM detections
                ORDER BY detection_timestamp DESC
                LIMIT $1
            """
            args = (limit,)
        
        async with self.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    # ============================================
    # Trajectories
    # ============================================
    
    async def insert_trajectory(
        self,
        track_id: int,
        intersection_id: int,
        vehicle_class: str,
        start_timestamp: datetime,
        end_timestamp: datetime,
        total_frames: int,
        average_velocity: float,
        trajectory_path: List[Dict]
    ) -> str:
        """Insert trajectory record"""
        import json
        
        query = """
            INSERT INTO trajectories (
                track_id, intersection_id, vehicle_class, start_timestamp,
                end_timestamp, total_frames, average_velocity, trajectory_path
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                track_id, intersection_id, vehicle_class, start_timestamp,
                end_timestamp, total_frames, average_velocity,
                json.dumps(trajectory_path)
            )
            return str(result)
    
    # ============================================
    # Emissions
    # ============================================
    
    async def insert_emission(
        self,
        trajectory_id: str,
        intersection_id: int,
        vehicle_class: str,
        emissions: Dict[str, float]
    ) -> str:
        """Insert emission record"""
        query = """
            INSERT INTO emissions (
                trajectory_id, intersection_id, vehicle_class,
                co2_grams, nox_grams, pm_grams, co_grams, hc_grams,
                distance_meters, average_speed_kmh, idle_time_seconds,
                environmental_impact_score
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                trajectory_id, intersection_id, vehicle_class,
                emissions['co2'], emissions['nox'], emissions['pm'],
                emissions['co'], emissions['hc'], emissions['distance'],
                emissions['speed'], emissions['idle_time'],
                emissions['impact_score']
            )
            return str(result)
    
    # ============================================
    # Traffic Metrics
    # ============================================
    
    async def insert_traffic_metrics(
        self,
        intersection_id: int,
        metrics: Dict
    ) -> str:
        """Insert traffic metrics"""
        import json
        
        query = """
            INSERT INTO traffic_metrics (
                intersection_id, total_vehicles, vehicles_by_class,
                average_speed_kmh, average_waiting_time_seconds,
                total_emissions_co2, traffic_density
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                intersection_id,
                metrics['total_vehicles'],
                json.dumps(metrics['vehicles_by_class']),
                metrics.get('average_speed', 0),
                metrics.get('average_waiting_time', 0),
                metrics.get('total_emissions_co2', 0),
                metrics.get('traffic_density', 'medium')
            )
            return str(result)
    
    # ============================================
    # Decisions
    # ============================================
    
    async def insert_decision(
        self,
        intersection_id: int,
        decision: Dict
    ) -> str:
        """Insert decision record"""
        import json
        
        query = """
            INSERT INTO decisions (
                intersection_id, current_phase, recommended_phase,
                priority, reason, confidence, expected_impact, was_executed
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                intersection_id,
                decision['current_phase'],
                decision['recommended_phase'],
                decision['priority'],
                decision['reason'],
                decision['confidence'],
                json.dumps(decision['expected_impact']),
                False
            )
            return str(result)
    
    async def update_decision_execution(
        self,
        decision_id: str,
        executed: bool = True
    ):
        """Update decision execution status"""
        query = """
            UPDATE decisions
            SET was_executed = $1, execution_timestamp = CURRENT_TIMESTAMP
            WHERE id = $2
        """
        
        async with self.acquire() as conn:
            await conn.execute(query, executed, decision_id)
    
    # ============================================
    # Signal Events
    # ============================================
    
    async def insert_signal_event(
        self,
        intersection_id: int,
        direction: str,
        previous_state: str,
        new_state: str,
        duration_seconds: int,
        is_manual: bool = False
    ) -> str:
        """Insert signal event"""
        query = """
            INSERT INTO signal_events (
                intersection_id, direction, previous_state, new_state,
                duration_seconds, is_manual
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                intersection_id, direction, previous_state, new_state,
                duration_seconds, is_manual
            )
            return str(result)
    
    # ============================================
    # Alerts
    # ============================================
    
    async def insert_alert(
        self,
        intersection_id: int,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        metadata: Optional[Dict] = None
    ) -> str:
        """Insert alert"""
        import json
        
        query = """
            INSERT INTO alerts (
                intersection_id, alert_type, severity, title, message, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """
        
        async with self.acquire() as conn:
            result = await conn.fetchval(
                query,
                intersection_id, alert_type, severity, title, message,
                json.dumps(metadata) if metadata else None
            )
            return str(result)
    
    async def get_active_alerts(
        self,
        intersection_id: Optional[int] = None
    ) -> List[Dict]:
        """Get active alerts"""
        if intersection_id:
            query = "SELECT * FROM active_alerts WHERE intersection_id = $1"
            args = (intersection_id,)
        else:
            query = "SELECT * FROM active_alerts"
            args = ()
        
        async with self.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    # ============================================
    # Analytics
    # ============================================
    
    async def get_hourly_traffic_summary(
        self,
        intersection_id: int,
        hours: int = 24
    ) -> List[Dict]:
        """Get hourly traffic summary"""
        query = """
            SELECT * FROM hourly_traffic_summary
            WHERE intersection_id = $1
            AND hour > NOW() - INTERVAL '1 hour' * $2
            ORDER BY hour DESC
        """
        
        async with self.acquire() as conn:
            rows = await conn.fetch(query, intersection_id, hours)
            return [dict(row) for row in rows]
    
    async def get_detection_summary(
        self,
        intersection_id: int
    ) -> List[Dict]:
        """Get recent detection summary"""
        query = """
            SELECT * FROM recent_detections_summary
            WHERE intersection_id = $1
        """
        
        async with self.acquire() as conn:
            rows = await conn.fetch(query, intersection_id)
            return [dict(row) for row in rows]

# Global database instance
db = DatabaseManager()

async def test_database():
    """Test database connection and operations"""
    print("🧪 Testing Database Connection...")
    
    try:
        await db.connect()
        print("✅ Database connected successfully")
        
        # Test detection insert
        detection_id = await db.insert_detection(
            intersection_id=1,
            camera_id=1,
            frame_id="test_001",
            object_class="sedan",
            confidence=0.95,
            bbox={'x1': 100, 'y1': 100, 'x2': 200, 'y2': 200}
        )
        print(f"✅ Detection inserted: {detection_id}")
        
        # Test getting recent detections
        detections = await db.get_recent_detections(intersection_id=1, limit=5)
        print(f"✅ Retrieved {len(detections)} recent detections")
        
        await db.close()
        print("✅ Database connection closed")
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_database())
