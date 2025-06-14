"""
Discord Listener - Captures trading signals from Discord channels
Listens via WebSocket for text and image content, forwards to signal parser
"""

import asyncio
import aiohttp
import os
import io
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime
import discord
from discord.ext import tasks
from config_manager import Config
from error_handler import get_error_handler


class DiscordListener:
    def __init__(self, config: Config):
        self.config = config
        self.error_handler = get_error_handler()
        self.signal_callback: Optional[Callable] = None
        self.client: Optional[discord.Client] = None
        self.target_channels: List[str] = []
        self._is_running = False
        
        self.discord_token = os.getenv("DISCORD_TOKEN")
        if not self.discord_token:
            raise ValueError("DISCORD_TOKEN not found in environment variables")
    
    async def initialize(self) -> None:
        """Initialize Discord client and connection"""
        try:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.guilds = True
            intents.guild_messages = True
            
            self.client = discord.Client(intents=intents)
            self._setup_event_handlers()
            
            self.target_channels = self.config.discord_channels.copy()
            
            await self.client.start(self.discord_token)
            
        except Exception as e:
            self.error_handler.handle_exception(e, "Discord initialization")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown Discord connection"""
        self._is_running = False
        if self.client and not self.client.is_closed():
            await self.client.close()
        self.error_handler.log_shutdown("Discord Listener")
    
    def set_signal_callback(self, callback: Callable) -> None:
        """Set callback for processing signals"""
        self.signal_callback = callback
    
    def _setup_event_handlers(self) -> None:
        """Setup Discord client event handlers"""
        
        @self.client.event
        async def on_ready():
            self._is_running = True
            self.error_handler.log_startup(f"Discord Listener (User: {self.client.user})")
            
            guild_count = len(self.client.guilds)
            self.error_handler.log_success(f"Connected to {guild_count} Discord servers")
            
            if self.target_channels:
                found_channels = []
                for guild in self.client.guilds:
                    for channel in guild.text_channels:
                        # Support both channel names and IDs
                        if (channel.name in self.target_channels or 
                            str(channel.id) in self.target_channels or
                            f"<#{channel.id}>" in self.target_channels):
                            found_channels.append(f"{guild.name}#{channel.name} (ID: {channel.id})")
                
                if found_channels:
                    self.error_handler.log_success(f"Monitoring channels: {', '.join(found_channels)}")
                else:
                    # Show available channels for debugging
                    available_channels = []
                    for guild in self.client.guilds:
                        for channel in guild.text_channels:
                            available_channels.append(f"{guild.name}#{channel.name} (ID: {channel.id})")
                    
                    self.error_handler.log_warning(f"No matching channels found for monitoring. Available channels: {', '.join(available_channels[:10])}")
                    if len(available_channels) > 10:
                        self.error_handler.log_info(f"... and {len(available_channels) - 10} more channels")
        
        @self.client.event
        async def on_disconnect():
            self.error_handler.log_warning("Discord connection lost")
        
        @self.client.event
        async def on_resumed():
            self.error_handler.log_success("Discord connection resumed")
        
        @self.client.event
        async def on_message(message):
            if not self._is_running:
                return
                
            try:
                await self._handle_message(message)
            except Exception as e:
                self.error_handler.handle_exception(e, "handling Discord message")
    
    async def _handle_message(self, message: discord.Message) -> None:
        """Handle incoming Discord message"""
        try:
            if message.author.bot:
                return
            
            if not self._is_target_channel(message.channel):
                return
            
            content = message.content.strip()
            attachments = message.attachments
            
            if not content and not attachments:
                return
            
            images = []
            if attachments:
                for attachment in attachments:
                    if self._is_image_attachment(attachment):
                        image_data = await self._download_image(attachment)
                        if image_data:
                            images.append(image_data)
            
            if content or images:
                source = f"{message.guild.name}#{message.channel.name}" if message.guild else "DM"
                
                self.error_handler.log_info(f"Signal received from {source}")
                
                if self.signal_callback:
                    if asyncio.iscoroutinefunction(self.signal_callback):
                        await self.signal_callback(content, images, source)
                    else:
                        self.signal_callback(content, images, source)
                        
        except Exception as e:
            self.error_handler.handle_exception(e, "processing Discord message")
    
    def _is_target_channel(self, channel) -> bool:
        """Check if channel is in target list"""
        if not self.target_channels:
            return True
        
        # Support channel names, IDs, and Discord mentions
        return (channel.name in self.target_channels or 
                str(channel.id) in self.target_channels or
                f"<#{channel.id}>" in self.target_channels)
    
    def _is_image_attachment(self, attachment: discord.Attachment) -> bool:
        """Check if attachment is an image"""
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        return any(attachment.filename.lower().endswith(ext) for ext in image_extensions)
    
    async def _download_image(self, attachment: discord.Attachment) -> Optional[bytes]:
        """Download image attachment"""
        try:
            if attachment.size > 10 * 1024 * 1024:  # 10MB limit
                self.error_handler.log_warning(f"Image too large: {attachment.size} bytes")
                return None
            
            image_data = await attachment.read()
            return image_data
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"downloading image {attachment.filename}")
            return None
    
    async def update_target_channels(self, channels: List[str]) -> None:
        """Update target channels list"""
        self.target_channels = channels.copy()
        self.error_handler.log_success(f"Updated target channels: {', '.join(channels)}")
    
    def is_connected(self) -> bool:
        """Check if Discord client is connected"""
        return self.client is not None and not self.client.is_closed()
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status info"""
        if not self.client:
            return {"connected": False, "user": None, "guilds": 0}
        
        return {
            "connected": not self.client.is_closed(),
            "user": str(self.client.user) if self.client.user else None,
            "guilds": len(self.client.guilds) if self.client.guilds else 0,
            "target_channels": self.target_channels
        }
    
    async def send_test_message(self, channel_name: str, message: str) -> bool:
        """Send test message to channel (for debugging)"""
        try:
            if not self.client or self.client.is_closed():
                return False
            
            for guild in self.client.guilds:
                for channel in guild.text_channels:
                    if channel.name == channel_name:
                        await channel.send(message)
                        self.error_handler.log_success(f"Test message sent to {channel_name}")
                        return True
            
            self.error_handler.log_warning(f"Channel {channel_name} not found")
            return False
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"sending test message to {channel_name}")
            return False


class DiscordListenerManager:
    """Manager for Discord listener with reconnection logic"""
    
    def __init__(self, config: Config):
        self.config = config
        self.error_handler = get_error_handler()
        self.listener: Optional[DiscordListener] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._should_run = False
        
    async def start(self) -> None:
        """Start Discord listener with auto-reconnect"""
        self._should_run = True
        self._reconnect_task = asyncio.create_task(self._manage_connection())
    
    async def stop(self) -> None:
        """Stop Discord listener"""
        self._should_run = False
        
        if self.listener:
            await self.listener.shutdown()
            
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
    
    async def _manage_connection(self) -> None:
        """Manage Discord connection with auto-reconnect"""
        reconnect_delay = 5
        max_delay = 300
        
        while self._should_run:
            try:
                self.listener = DiscordListener(self.config)
                await self.listener.initialize()
                
                reconnect_delay = 5
                
                while self._should_run and self.listener.is_connected():
                    await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_handler.handle_exception(e, "Discord connection")
                
                if self.listener:
                    try:
                        await self.listener.shutdown()
                    except:
                        pass
                
                if self._should_run:
                    self.error_handler.log_warning(f"Reconnecting in {reconnect_delay}s...")
                    await asyncio.sleep(reconnect_delay)
                    
                    reconnect_delay = min(reconnect_delay * 2, max_delay)
    
    def set_signal_callback(self, callback: Callable) -> None:
        """Set signal callback for current listener"""
        if self.listener:
            self.listener.set_signal_callback(callback)
    
    def get_status(self) -> Dict[str, Any]:
        """Get listener status"""
        if self.listener:
            return self.listener.get_connection_status()
        return {"connected": False, "user": None, "guilds": 0}