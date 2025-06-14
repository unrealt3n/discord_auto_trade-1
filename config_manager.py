"""
Config Manager - Hot-reloading configuration system with file watching
Manages config.json with live updates and dependency injection to other modules
"""

import json
import asyncio
import aiofiles
from pathlib import Path
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass, field
import time


@dataclass
class Config:
    mode: str = "demo"
    leverage: int = 0
    max_futures_trade: int = 2
    max_spot_trade: int = 1
    max_daily_loss: float = 300.0
    futures_position_size: float = 150.0
    spot_position_size: float = 100.0
    blacklist: list = field(default_factory=list)
    discord_channels: list = field(default_factory=list)
    is_trading_enabled: bool = True
    authorized_users: list = field(default_factory=list)
    performance_monitoring: bool = True
    cache_signals: bool = True
    min_confidence_threshold: float = 0.7
    max_risk_reward_ratio: float = 3.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "leverage": self.leverage,
            "max_futures_trade": self.max_futures_trade,
            "max_spot_trade": self.max_spot_trade,
            "max_daily_loss": self.max_daily_loss,
            "futures_position_size": self.futures_position_size,
            "spot_position_size": self.spot_position_size,
            "blacklist": self.blacklist,
            "discord_channels": self.discord_channels,
            "is_trading_enabled": self.is_trading_enabled,
            "authorized_users": self.authorized_users,
            "performance_monitoring": self.performance_monitoring,
            "cache_signals": self.cache_signals,
            "min_confidence_threshold": self.min_confidence_threshold,
            "max_risk_reward_ratio": self.max_risk_reward_ratio
        }
    
    def is_symbol_blacklisted(self, symbol: str) -> bool:
        """Check if symbol is blacklisted"""
        return symbol in self.blacklist


class ConfigManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config = Config()
        self.subscribers: list[Callable[[Config], None]] = []
        self.last_modified = 0
        self._lock = asyncio.Lock()
        self._watch_task: Optional[asyncio.Task] = None
        
    async def initialize(self) -> None:
        """Initialize config manager and start file watching"""
        await self._load_config()
        self._watch_task = asyncio.create_task(self._watch_config_file())
        
    async def shutdown(self) -> None:
        """Gracefully shutdown the config manager"""
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
    
    async def _load_config(self) -> None:
        """Load configuration from file"""
        try:
            if not self.config_path.exists():
                await self._create_default_config()
                return
                
            async with aiofiles.open(self.config_path, 'r') as f:
                content = await f.read()
                data = json.loads(content)
                
            self.config = Config(
                mode=data.get("mode", "demo"),
                leverage=data.get("leverage", 0),
                max_futures_trade=data.get("max_futures_trade", 2),
                max_spot_trade=data.get("max_spot_trade", 1),
                max_daily_loss=data.get("max_daily_loss", 300.0),
                futures_position_size=data.get("futures_position_size", 150.0),
                spot_position_size=data.get("spot_position_size", 100.0),
                blacklist=data.get("blacklist", []),
                discord_channels=data.get("discord_channels", []),
                is_trading_enabled=data.get("is_trading_enabled", True),
                authorized_users=data.get("authorized_users", []),
                performance_monitoring=data.get("performance_monitoring", True),
                cache_signals=data.get("cache_signals", True),
                min_confidence_threshold=data.get("min_confidence_threshold", 0.7),
                max_risk_reward_ratio=data.get("max_risk_reward_ratio", 3.0)
            )
            
            self.last_modified = self.config_path.stat().st_mtime
            await self._notify_subscribers()
            
        except Exception as e:
            raise RuntimeError(f"Failed to load config: {e}")
    
    async def _create_default_config(self) -> None:
        """Create default configuration file"""
        default_config = {
            "mode": "demo",
            "leverage": 0,
            "max_futures_trade": 2,
            "max_spot_trade": 1,
            "max_daily_loss": 300,
            "futures_position_size": 150,
            "spot_position_size": 100,
            "blacklist": ["PEPEUSDT"],
            "discord_channels": ["signals-1", "signals-2"],
            "is_trading_enabled": True
        }
        
        async with aiofiles.open(self.config_path, 'w') as f:
            await f.write(json.dumps(default_config, indent=2))
        
        self.config = Config(**default_config)
        await self._notify_subscribers()
    
    async def _watch_config_file(self) -> None:
        """Watch config file for changes"""
        while True:
            try:
                await asyncio.sleep(1)
                
                if not self.config_path.exists():
                    continue
                    
                current_mtime = self.config_path.stat().st_mtime
                if current_mtime != self.last_modified:
                    async with self._lock:
                        start_time = time.time()
                        await self._load_config()
                        load_time = (time.time() - start_time) * 1000
                        
                        if load_time > 100:
                            print(f"⚠️ Config reload took {load_time:.1f}ms (target: <100ms)")
                        else:
                            print(f"✅ Config reloaded in {load_time:.1f}ms")
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Error watching config file: {e}")
                await asyncio.sleep(5)
    
    async def _notify_subscribers(self) -> None:
        """Notify all subscribers of config changes"""
        for callback in self.subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(self.config)
                else:
                    callback(self.config)
            except Exception as e:
                print(f"❌ Error notifying config subscriber: {e}")
    
    def subscribe(self, callback: Callable[[Config], None]) -> None:
        """Subscribe to config changes"""
        self.subscribers.append(callback)
    
    def get_config(self) -> Config:
        """Get current configuration"""
        return self.config
    
    async def update_config(self, updates: Dict[str, Any]) -> None:
        """Update configuration programmatically"""
        async with self._lock:
            current_data = self.config.to_dict()
            current_data.update(updates)
            
            async with aiofiles.open(self.config_path, 'w') as f:
                await f.write(json.dumps(current_data, indent=2))
            
            await self._load_config()
    
    def is_live_mode(self) -> bool:
        """Check if running in live mode"""
        return self.config.mode == "live"
    
    def is_trading_enabled(self) -> bool:
        """Check if trading is enabled"""
        return self.config.is_trading_enabled
    
    def is_symbol_blacklisted(self, symbol: str) -> bool:
        """Check if symbol is blacklisted"""
        return symbol in self.config.blacklist