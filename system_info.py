"""
System Info - Lightweight replacement for psutil compatible with Termux
Provides basic system monitoring without external dependencies
"""

import os
import time
import threading
from typing import Dict, Optional


class SystemInfo:
    """Lightweight system information provider"""
    
    def __init__(self):
        self._start_time = time.time()
    
    def cpu_percent(self) -> float:
        """Get CPU usage percentage (simplified)"""
        try:
            # Read /proc/loadavg on Linux systems
            if os.path.exists('/proc/loadavg'):
                with open('/proc/loadavg', 'r') as f:
                    load_avg = float(f.read().split()[0])
                # Convert load average to approximate percentage (simplified)
                return min(load_avg * 25, 100.0)  # Rough approximation
            return 0.0
        except:
            return 0.0
    
    def memory_info(self) -> Dict[str, float]:
        """Get memory information"""
        try:
            # Read /proc/meminfo on Linux systems
            if os.path.exists('/proc/meminfo'):
                meminfo = {}
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if ':' in line:
                            key, value = line.split(':', 1)
                            meminfo[key.strip()] = int(value.strip().split()[0]) * 1024  # Convert KB to bytes
                
                total = meminfo.get('MemTotal', 0)
                available = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
                used = total - available
                
                return {
                    'total': total,
                    'available': available,
                    'used': used,
                    'percent': (used / total * 100) if total > 0 else 0.0
                }
            
            # Fallback for systems without /proc/meminfo
            return {
                'total': 0,
                'available': 0,
                'used': 0,
                'percent': 0.0
            }
        except:
            return {
                'total': 0,
                'available': 0,
                'used': 0,
                'percent': 0.0
            }
    
    def boot_time(self) -> float:
        """Get system boot time"""
        try:
            # Read /proc/stat on Linux systems
            if os.path.exists('/proc/stat'):
                with open('/proc/stat', 'r') as f:
                    for line in f:
                        if line.startswith('btime'):
                            return float(line.split()[1])
            return self._start_time
        except:
            return self._start_time
    
    def process_count(self) -> int:
        """Get number of running processes"""
        try:
            # Count directories in /proc that are numeric (PIDs)
            if os.path.exists('/proc'):
                count = 0
                for item in os.listdir('/proc'):
                    if item.isdigit():
                        count += 1
                return count
            return 0
        except:
            return 0
    
    def thread_count(self) -> int:
        """Get number of threads in current process"""
        try:
            return threading.active_count()
        except:
            return 1
    
    def uptime(self) -> float:
        """Get system uptime in seconds"""
        try:
            if os.path.exists('/proc/uptime'):
                with open('/proc/uptime', 'r') as f:
                    return float(f.read().split()[0])
            return time.time() - self._start_time
        except:
            return time.time() - self._start_time
    
    def get_system_info(self) -> Dict:
        """Get comprehensive system information"""
        memory = self.memory_info()
        
        return {
            'cpu_percent': self.cpu_percent(),
            'memory_percent': memory['percent'],
            'memory_mb': memory['used'] / (1024 * 1024),
            'memory_total_mb': memory['total'] / (1024 * 1024),
            'threads': self.thread_count(),
            'processes': self.process_count(),
            'uptime_hours': self.uptime() / 3600,
            'boot_time': self.boot_time()
        }


# Global instance
_system_info = SystemInfo()

# Compatibility functions to replace psutil
def cpu_percent():
    """psutil.cpu_percent() replacement"""
    return _system_info.cpu_percent()

def virtual_memory():
    """psutil.virtual_memory() replacement"""
    memory = _system_info.memory_info()
    
    class MemoryInfo:
        def __init__(self, data):
            self.total = data['total']
            self.available = data['available']
            self.used = data['used']
            self.percent = data['percent']
    
    return MemoryInfo(memory)

def boot_time():
    """psutil.boot_time() replacement"""
    return _system_info.boot_time()

def pids():
    """psutil.pids() replacement"""
    return list(range(_system_info.process_count()))  # Simplified