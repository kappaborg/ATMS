"""
Python Interface Dashboard
==========================
Real-time dashboard using matplotlib and tkinter.
Updates every 1-2 seconds to avoid blocking main processing.
"""

import tkinter as tk
from tkinter import ttk
import matplotlib
matplotlib.use('TkAgg')  # Use TkAgg backend
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import time
import logging
from typing import Optional, Dict
from collections import deque

try:
    from .collector import PerformanceCollector
    from .metrics import get_metrics_collector
    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False

logger = logging.getLogger(__name__)


class PythonDashboard:
    """
    Real-time Python dashboard for traffic management system.
    Uses matplotlib for charts and tkinter for GUI.
    Updates in separate thread to avoid blocking.
    """
    
    def __init__(self, performance_collector: Optional[PerformanceCollector] = None, 
                 update_interval: float = 1.0):
        """
        Initialize Python dashboard.
        
        Args:
            performance_collector: Performance collector instance
            update_interval: Update interval in seconds
        """
        if not MONITORING_AVAILABLE:
            logger.warning("Monitoring not available - dashboard disabled")
            self.enabled = False
            return
        
        self.enabled = True
        self.performance_collector = performance_collector
        self.update_interval = update_interval
        self.running = False
        self.update_thread: Optional[threading.Thread] = None
        
        # Data storage for charts
        self.fps_history = deque(maxlen=100)
        self.detection_history = deque(maxlen=100)
        self.processing_time_history = deque(maxlen=100)
        self.timestamps = deque(maxlen=100)
        
        # Tkinter root
        self.root = tk.Tk()
        self.root.title("Traffic Management System - Real-Time Dashboard")
        self.root.geometry("1200x800")
        
        # Create UI
        self._create_ui()
        
        # Start update thread
        self.running = True
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start()
    
    def _create_ui(self):
        """Create dashboard UI"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Title
        title_label = ttk.Label(
            main_frame,
            text="Traffic Management System - Real-Time Dashboard",
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, pady=10)
        
        # Stats frame
        stats_frame = ttk.Frame(main_frame)
        stats_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        stats_frame.columnconfigure(0, weight=1)
        stats_frame.columnconfigure(1, weight=1)
        stats_frame.columnconfigure(2, weight=1)
        stats_frame.columnconfigure(3, weight=1)
        
        # Stats labels
        self.fps_label = ttk.Label(stats_frame, text="FPS: --", font=("Arial", 12))
        self.fps_label.grid(row=0, column=0, padx=10, pady=5)
        
        self.detections_label = ttk.Label(stats_frame, text="Detections: --", font=("Arial", 12))
        self.detections_label.grid(row=0, column=1, padx=10, pady=5)
        
        self.vehicles_label = ttk.Label(stats_frame, text="Vehicles: --", font=("Arial", 12))
        self.vehicles_label.grid(row=0, column=2, padx=10, pady=5)
        
        self.memory_label = ttk.Label(stats_frame, text="Memory: -- MB", font=("Arial", 12))
        self.memory_label.grid(row=0, column=3, padx=10, pady=5)
        
        # Charts frame
        charts_frame = ttk.Frame(main_frame)
        charts_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        charts_frame.columnconfigure(0, weight=1)
        charts_frame.columnconfigure(1, weight=1)
        charts_frame.rowconfigure(0, weight=1)
        charts_frame.rowconfigure(1, weight=1)
        
        # FPS Chart
        self.fps_fig = Figure(figsize=(6, 4), dpi=100)
        self.fps_ax = self.fps_fig.add_subplot(111)
        self.fps_ax.set_title("FPS Over Time")
        self.fps_ax.set_xlabel("Time")
        self.fps_ax.set_ylabel("FPS")
        self.fps_ax.grid(True)
        self.fps_canvas = FigureCanvasTkAgg(self.fps_fig, charts_frame)
        self.fps_canvas.get_tk_widget().grid(row=0, column=0, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Detection Chart
        self.detection_fig = Figure(figsize=(6, 4), dpi=100)
        self.detection_ax = self.detection_fig.add_subplot(111)
        self.detection_ax.set_title("Detections Over Time")
        self.detection_ax.set_xlabel("Time")
        self.detection_ax.set_ylabel("Count")
        self.detection_ax.grid(True)
        self.detection_canvas = FigureCanvasTkAgg(self.detection_fig, charts_frame)
        self.detection_canvas.get_tk_widget().grid(row=0, column=1, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Processing Time Chart
        self.processing_fig = Figure(figsize=(6, 4), dpi=100)
        self.processing_ax = self.processing_fig.add_subplot(111)
        self.processing_ax.set_title("Frame Processing Time")
        self.processing_ax.set_xlabel("Time")
        self.processing_ax.set_ylabel("Time (ms)")
        self.processing_ax.grid(True)
        self.processing_canvas = FigureCanvasTkAgg(self.processing_fig, charts_frame)
        self.processing_canvas.get_tk_widget().grid(row=1, column=0, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Trajectory Chart (replaces System Resources)
        self.trajectory_fig = Figure(figsize=(6, 4), dpi=100)
        self.trajectory_ax = self.trajectory_fig.add_subplot(111)
        self.trajectory_ax.set_title("Object Trajectories")
        self.trajectory_ax.set_xlabel("X Position")
        self.trajectory_ax.set_ylabel("Y Position")
        self.trajectory_ax.grid(True)
        self.trajectory_ax.set_aspect('equal', adjustable='box')
        self.trajectory_canvas = FigureCanvasTkAgg(self.trajectory_fig, charts_frame)
        self.trajectory_canvas.get_tk_widget().grid(row=1, column=1, padx=5, pady=5, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="Status: Running", font=("Arial", 10))
        self.status_label.grid(row=3, column=0, pady=5)
    
    def _update_loop(self):
        """Background thread for updating dashboard"""
        while self.running:
            try:
                self._update_data()
                time.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error updating dashboard: {e}")
                time.sleep(self.update_interval)
    
    def _update_data(self):
        """Update dashboard data"""
        if not self.performance_collector:
            return
        
        # Get stats from performance collector
        stats = self.performance_collector.get_stats()
        
        # Update labels
        current_time = time.time()
        self.timestamps.append(current_time)
        
        fps = stats['fps']['current']
        self.fps_history.append(fps)
        
        detections = stats['detections']['current']
        self.detection_history.append(detections)
        
        avg_processing = stats['processing_times_ms']['average']
        self.processing_time_history.append(avg_processing)
        
        # Update UI in main thread
        self.root.after(0, self._update_ui, stats)
    
    def _update_ui(self, stats: Dict):
        """Update UI elements (called in main thread)"""
        try:
            # Update labels
            self.fps_label.config(text=f"FPS: {stats['fps']['current']:.1f} (Avg: {stats['fps']['average']:.1f})")
            self.detections_label.config(text=f"Detections: {stats['detections']['current']}")
            self.vehicles_label.config(text=f"Vehicles: {stats['detections']['vehicles']} | Pedestrians: {stats['detections']['pedestrians']}")
            
            # Get memory from metrics if available
            if self.performance_collector and self.performance_collector.metrics:
                try:
                    import psutil
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    self.memory_label.config(text=f"Memory: {memory_mb:.1f} MB")
                except:
                    self.memory_label.config(text="Memory: N/A")
            
            # Update charts
            if len(self.timestamps) > 1:
                # FPS chart
                self.fps_ax.clear()
                self.fps_ax.plot(list(self.timestamps), list(self.fps_history), 'b-', linewidth=2)
                self.fps_ax.set_title("FPS Over Time")
                self.fps_ax.set_xlabel("Time")
                self.fps_ax.set_ylabel("FPS")
                self.fps_ax.grid(True)
                self.fps_ax.set_ylim(0, max(30, max(self.fps_history) * 1.1) if self.fps_history else 30)
                self.fps_canvas.draw()
                
                # Detection chart
                self.detection_ax.clear()
                self.detection_ax.plot(list(self.timestamps), list(self.detection_history), 'g-', linewidth=2)
                self.detection_ax.set_title("Detections Over Time")
                self.detection_ax.set_xlabel("Time")
                self.detection_ax.set_ylabel("Count")
                self.detection_ax.grid(True)
                self.detection_canvas.draw()
                
                # Processing time chart
                self.processing_ax.clear()
                self.processing_ax.plot(list(self.timestamps), list(self.processing_time_history), 'r-', linewidth=2)
                self.processing_ax.set_title("Frame Processing Time")
                self.processing_ax.set_xlabel("Time")
                self.processing_ax.set_ylabel("Time (ms)")
                self.processing_ax.grid(True)
                self.processing_canvas.draw()
                
                # Trajectory chart
                self.trajectory_ax.clear()
                self.trajectory_ax.set_title("Object Trajectories")
                self.trajectory_ax.set_xlabel("X Position")
                self.trajectory_ax.set_ylabel("Y Position")
                self.trajectory_ax.grid(True)
                
                # Draw trajectories for each tracked object
                colors = ['b', 'g', 'r', 'c', 'm', 'y', 'k']
                color_idx = 0
                for track_id, trajectory in self.trajectory_data.items():
                    if len(trajectory) > 1:
                        x_coords = [p[0] for p in trajectory]
                        y_coords = [p[1] for p in trajectory]
                        color = colors[color_idx % len(colors)]
                        self.trajectory_ax.plot(x_coords, y_coords, color=color, linewidth=2, alpha=0.7, label=f'ID:{track_id}')
                        # Mark current position
                        if trajectory:
                            self.trajectory_ax.plot(x_coords[-1], y_coords[-1], 'o', color=color, markersize=8)
                        color_idx += 1
                
                if self.trajectory_data:
                    self.trajectory_ax.legend(loc='upper right', fontsize=8, ncol=2)
                
                self.trajectory_canvas.draw()
        except Exception as e:
            logger.error(f"Error updating UI: {e}")
    
    def show(self):
        """Show dashboard window"""
        if not self.enabled:
            logger.warning("Dashboard not enabled")
            return
        
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.stop()
    
    def update_trajectories(self, trajectory_data: Dict[int, List[Tuple[float, float]]]):
        """
        Update trajectory data from processor.
        
        Args:
            trajectory_data: Dictionary mapping track_id to list of (x, y) coordinates
        """
        # Update trajectory data (keep only recent points)
        for track_id, trajectory in trajectory_data.items():
            if track_id not in self.trajectory_data:
                self.trajectory_data[track_id] = []
            
            # Add new points
            self.trajectory_data[track_id].extend(trajectory)
            
            # Keep only last N points
            if len(self.trajectory_data[track_id]) > self.trajectory_history_length:
                self.trajectory_data[track_id] = self.trajectory_data[track_id][-self.trajectory_history_length:]
        
        # Remove old tracks (not seen in recent update)
        current_tracks = set(trajectory_data.keys())
        tracks_to_remove = [tid for tid in self.trajectory_data.keys() if tid not in current_tracks]
        for tid in tracks_to_remove:
            # Keep for a bit longer, then remove
            if len(self.trajectory_data[tid]) > 0:
                self.trajectory_data[tid] = []
    
    def stop(self):
        """Stop dashboard"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=2.0)
        if self.root:
            self.root.quit()
        logger.info("Dashboard stopped")


def create_dashboard(performance_collector: Optional[PerformanceCollector] = None) -> Optional[PythonDashboard]:
    """
    Create and return dashboard instance.
    
    Args:
        performance_collector: Performance collector instance
        
    Returns:
        Dashboard instance or None if not available
    """
    if not MONITORING_AVAILABLE:
        logger.warning("Monitoring not available - dashboard disabled")
        return None
    
    try:
        return PythonDashboard(performance_collector=performance_collector)
    except Exception as e:
        logger.error(f"Could not create dashboard: {e}")
        return None

