"""
Performance Monitor - Tracks system performance and provides metrics
Monitors execution times, memory usage, and API call statistics
"""

import asyncio
import time
try:
    import psutil
except ImportError:
    # Use lightweight replacement for Termux compatibility
    from system_info import cpu_percent, virtual_memory, boot_time
    
    class psutil:
        @staticmethod
        def cpu_percent():
            return cpu_percent()
        
        @staticmethod
        def virtual_memory():
            return virtual_memory()
        
        @staticmethod
        def boot_time():
            return boot_time()
import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from error_handler import get_error_handler


@dataclass
class PerformanceMetric:
    timestamp: float
    operation: str
    duration: float
    success: bool
    error_type: Optional[str] = None


@dataclass
class SystemMetrics:
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    open_files: int
    network_connections: int
    uptime_hours: float


class PerformanceMonitor:
    def __init__(self, max_history: int = 1000):
        self.error_handler = get_error_handler()
        self.max_history = max_history
        self.metrics: deque = deque(maxlen=max_history)
        self.operation_stats: Dict[str, Dict] = defaultdict(lambda: {
            'count': 0,
            'total_time': 0,
            'success_count': 0,
            'error_count': 0,
            'avg_time': 0,
            'last_error': None
        })
        self.start_time = time.time()
        self._monitoring_task: Optional[asyncio.Task] = None
    
    async def initialize(self) -> None:
        """Initialize performance monitoring"""
        self._monitoring_task = asyncio.create_task(self._monitor_system())
        self.error_handler.log_startup("Performance Monitor")
    
    async def shutdown(self) -> None:
        """Shutdown performance monitoring"""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
        self.error_handler.log_shutdown("Performance Monitor")
    
    async def _monitor_system(self) -> None:
        """Continuous system monitoring"""
        while True:
            try:
                await asyncio.sleep(60)  # Monitor every minute
                await self._collect_system_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_handler.handle_exception(e, "system monitoring")
                await asyncio.sleep(60)
    
    async def _collect_system_metrics(self) -> None:
        """Collect system performance metrics"""
        try:
            process = psutil.Process()
            
            # CPU and memory
            cpu_percent = process.cpu_percent()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            # File handles and connections
            try:
                open_files = len(process.open_files())
            except:
                open_files = 0
            
            try:
                connections = len(process.connections())
            except:
                connections = 0
            
            uptime_hours = (time.time() - self.start_time) / 3600
            
            system_metrics = SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_info.rss / 1024 / 1024,
                open_files=open_files,
                network_connections=connections,
                uptime_hours=uptime_hours
            )
            
            # Log warnings for high resource usage
            if cpu_percent > 80:
                self.error_handler.log_warning(f"High CPU usage: {cpu_percent:.1f}%")
            
            if memory_percent > 80:
                self.error_handler.log_warning(f"High memory usage: {memory_percent:.1f}%")
            
            if open_files > 100:
                self.error_handler.log_warning(f"High file handle count: {open_files}")
                
        except Exception as e:
            self.error_handler.handle_exception(e, "collecting system metrics")
    
    def time_operation(self, operation_name: str):
        """Context manager for timing operations"""
        return OperationTimer(self, operation_name)
    
    def record_metric(self, operation: str, duration: float, success: bool, error_type: str = None) -> None:
        """Record a performance metric"""
        metric = PerformanceMetric(
            timestamp=time.time(),
            operation=operation,
            duration=duration,
            success=success,
            error_type=error_type
        )
        
        self.metrics.append(metric)
        
        # Update operation statistics
        stats = self.operation_stats[operation]
        stats['count'] += 1
        stats['total_time'] += duration
        
        if success:
            stats['success_count'] += 1
        else:
            stats['error_count'] += 1
            stats['last_error'] = error_type
        
        stats['avg_time'] = stats['total_time'] / stats['count']
        
        # Log slow operations
        if duration > 5.0:  # Log operations slower than 5 seconds
            self.error_handler.log_warning(f"Slow operation: {operation} took {duration:.2f}s")
    
    def get_operation_stats(self, operation: str = None) -> Dict[str, Any]:
        """Get statistics for specific operation or all operations"""
        if operation:
            return dict(self.operation_stats.get(operation, {}))
        else:
            return {op: dict(stats) for op, stats in self.operation_stats.items()}
    
    def get_recent_metrics(self, minutes: int = 60) -> List[PerformanceMetric]:
        """Get metrics from the last N minutes"""
        cutoff_time = time.time() - (minutes * 60)
        return [m for m in self.metrics if m.timestamp >= cutoff_time]
    
    def get_success_rate(self, operation: str = None, minutes: int = 60) -> float:
        """Get success rate for operations"""
        recent_metrics = self.get_recent_metrics(minutes)
        
        if operation:
            relevant_metrics = [m for m in recent_metrics if m.operation == operation]
        else:
            relevant_metrics = recent_metrics
        
        if not relevant_metrics:
            return 0.0
        
        success_count = sum(1 for m in relevant_metrics if m.success)
        return (success_count / len(relevant_metrics)) * 100
    
    def get_average_response_time(self, operation: str = None, minutes: int = 60) -> float:
        """Get average response time for operations"""
        recent_metrics = self.get_recent_metrics(minutes)
        
        if operation:
            relevant_metrics = [m for m in recent_metrics if m.operation == operation]
        else:
            relevant_metrics = recent_metrics
        
        if not relevant_metrics:
            return 0.0
        
        total_time = sum(m.duration for m in relevant_metrics)
        return total_time / len(relevant_metrics)
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary"""
        uptime_hours = (time.time() - self.start_time) / 3600
        
        summary = {
            'uptime_hours': round(uptime_hours, 2),
            'total_operations': len(self.metrics),
            'operations_by_type': {},
            'recent_performance': {},
            'system_health': {}
        }
        
        # Operations by type
        for operation, stats in self.operation_stats.items():
            summary['operations_by_type'][operation] = {
                'count': stats['count'],
                'success_rate': (stats['success_count'] / stats['count'] * 100) if stats['count'] > 0 else 0,
                'avg_time': round(stats['avg_time'], 3),
                'last_error': stats['last_error']
            }
        
        # Recent performance (last hour)
        summary['recent_performance'] = {
            'success_rate': round(self.get_success_rate(minutes=60), 2),
            'avg_response_time': round(self.get_average_response_time(minutes=60), 3),
            'operations_count': len(self.get_recent_metrics(60))
        }
        
        # System health indicators
        try:
            process = psutil.Process()
            summary['system_health'] = {
                'cpu_percent': round(process.cpu_percent(), 1),
                'memory_percent': round(process.memory_percent(), 1),
                'memory_mb': round(process.memory_info().rss / 1024 / 1024, 1),
                'threads': process.num_threads()
            }
        except:
            summary['system_health'] = {'error': 'Unable to collect system metrics'}
        
        return summary
    
    def export_metrics(self, filepath: str = None) -> str:
        """Export metrics to JSON file"""
        if filepath is None:
            filepath = f"performance_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'uptime_hours': (time.time() - self.start_time) / 3600,
            'summary': self.get_performance_summary(),
            'recent_metrics': [asdict(m) for m in self.get_recent_metrics(1440)]  # Last 24 hours
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            self.error_handler.log_success(f"Performance metrics exported to {filepath}")
            return filepath
        except Exception as e:
            self.error_handler.handle_exception(e, "exporting performance metrics")
            return ""


class OperationTimer:
    """Context manager for timing operations"""
    
    def __init__(self, monitor: PerformanceMonitor, operation_name: str):
        self.monitor = monitor
        self.operation_name = operation_name
        self.start_time = None
        self.success = True
        self.error_type = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        
        if exc_type is not None:
            self.success = False
            self.error_type = exc_type.__name__
        
        self.monitor.record_metric(
            self.operation_name,
            duration,
            self.success,
            self.error_type
        )
        
        return False  # Don't suppress exceptions


# Global performance monitor instance
_performance_monitor = PerformanceMonitor()


def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor instance"""
    return _performance_monitor