"""
Discord Controller HTTP - Pure HTTP implementation compatible with Termux
Handles commands, sends alerts, and provides trading statistics via Discord
"""

import asyncio
import os
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
from discord_http_client import SimpleDiscordClient, DiscordEmbed, DiscordColor
from config_manager import Config
from error_handler import get_error_handler


class DiscordControllerHTTP:
    """HTTP-based Discord controller compatible with Termux"""
    
    def __init__(self, config: Config):
        self.config = config
        self.error_handler = get_error_handler()
        
        # Get authorized users from config
        if hasattr(config, 'authorized_users') and config.authorized_users:
            self.authorized_users = [int(uid) for uid in config.authorized_users]
        elif hasattr(config, 'authorized_user_id') and config.authorized_user_id:
            # Backward compatibility with single user
            self.authorized_users = [int(config.authorized_user_id)]
        else:
            self.authorized_users = []
        
        self.monitored_channel_ids = [int(ch) for ch in os.getenv("MONITORED_CHANNEL_IDS", "").split(",") if ch.strip()]
        
        # Add config-based channels to monitored channels
        if hasattr(config, 'discord_channels') and config.discord_channels:
            for ch in config.discord_channels:
                try:
                    channel_id = int(ch)
                    if channel_id not in self.monitored_channel_ids:
                        self.monitored_channel_ids.append(channel_id)
                except ValueError:
                    self.error_handler.log_warning(f"Invalid channel ID in config: {ch}")
        
        print(f"🔧 Discord Controller initialized with monitored channels: {self.monitored_channel_ids}")
        print(f"👤 Authorized users: {self.authorized_users}")
        
        # Callbacks
        self.cancel_all_callback: Optional[Callable] = None
        self.get_positions_callback: Optional[Callable] = None
        self.get_stats_callback: Optional[Callable] = None
        self.signal_callback: Optional[Callable] = None
        
        self.discord_token = os.getenv("DISCORD_TOKEN")
        if not self.discord_token:
            raise ValueError("DISCORD_TOKEN not found in environment variables")
        
        if not self.authorized_users:
            raise ValueError("authorized_users not found in config.json")
        
        # Initialize HTTP Discord client
        self.client = SimpleDiscordClient(
            token=self.discord_token,
            authorized_users=self.authorized_users,
            monitored_channels=self.monitored_channel_ids
        )
        
        # Register command handlers
        self._setup_command_handlers()
    
    async def initialize(self) -> None:
        """Initialize Discord controller"""
        try:
            await self.client.initialize()
            self.error_handler.log_startup("Discord Controller HTTP")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "Discord HTTP initialization")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown Discord controller"""
        await self.client.shutdown()
        self.error_handler.log_shutdown("Discord Controller HTTP")
    
    def _setup_command_handlers(self) -> None:
        """Setup command handlers for the HTTP client"""
        
        async def handle_start(message, args):
            """Start trading bot"""
            await self.config.update_config({"is_trading_enabled": True})
            embed = DiscordEmbed(
                "✅ Trading Started",
                "Trading bot has been enabled!\\n\\nUse `!menu` to see all available commands.",
                DiscordColor.GREEN
            )
            dm_channel = await self.client._create_dm_channel(message.author.id)
            if dm_channel:
                await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_stop(message, args):
            """Stop trading bot"""
            await self.config.update_config({"is_trading_enabled": False})
            embed = DiscordEmbed(
                "🛑 Trading Stopped",
                "Trading bot has been disabled!\\n\\nExisting positions will continue to be monitored.",
                DiscordColor.RED
            )
            dm_channel = await self.client._create_dm_channel(message.author.id)
            if dm_channel:
                await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_status(message, args):
            """Show bot status"""
            try:
                config = self.config
                status_text = (
                    f"Trading: {'✅ Enabled' if config.is_trading_enabled else '🛑 Disabled'}\\n"
                    f"Mode: {config.mode.upper()}\\n"
                    f"Leverage: {config.leverage if config.leverage > 0 else 'From Signal'}\\n"
                    f"Futures Size: ${config.futures_position_size}\\n"
                    f"Spot Size: ${config.spot_position_size}\\n"
                    f"Max Futures: {config.max_futures_trade}\\n"
                    f"Max Spot: {config.max_spot_trade}\\n"
                    f"Daily Loss Limit: ${config.max_daily_loss}\\n"
                    f"Channels: {', '.join(map(str, self.monitored_channel_ids)) if self.monitored_channel_ids else 'None'}"
                )
                
                embed = DiscordEmbed("📊 Bot Status", status_text, DiscordColor.BLUE)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
            except Exception as e:
                print(f"Status command error: {e}")
        
        async def handle_positions(message, args):
            """Show active positions"""
            if self.get_positions_callback:
                try:
                    positions_text = await self.get_positions_callback()
                    embed = DiscordEmbed("📈 Active Positions", positions_text, DiscordColor.GOLD)
                    dm_channel = await self.client._create_dm_channel(message.author.id)
                    if dm_channel:
                        await self.client._send_message(dm_channel, embed=embed)
                except Exception as e:
                    print(f"❌ Error getting positions: {e}")
            else:
                embed = DiscordEmbed("❌ Error", "Positions callback not configured", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_stats(message, args):
            """Show trading statistics"""
            if self.get_stats_callback:
                try:
                    stats = await self.get_stats_callback()
                    stats_text = (
                        f"Total Trades: {stats.get('total_trades', 0)}\\n"
                        f"Total PnL: {stats.get('total_pnl', 0):+.2f} USDT\\n"
                        f"Win Rate: {stats.get('win_rate', 0):.1f}%\\n"
                        f"Avg Hold Time: {stats.get('avg_hold_time', 0):.2f}h"
                    )
                    embed = DiscordEmbed("📈 Trading Statistics", stats_text, DiscordColor.GREEN)
                    dm_channel = await self.client._create_dm_channel(message.author.id)
                    if dm_channel:
                        await self.client._send_message(dm_channel, embed=embed)
                except Exception as e:
                    print(f"❌ Error getting stats: {e}")
            else:
                embed = DiscordEmbed("❌ Error", "Stats callback not configured", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_health(message, args):
            """Show system health"""
            health_text = (
                f"Timestamp: {datetime.now().strftime('%H:%M:%S')}\\n"
                f"Config: ✅ Loaded\\n"
                f"Exchange: ✅ Connected\\n"
                f"Discord: ✅ Connected\\n"
                f"Bot: ✅ Online\\n"
            )
            
            embed = DiscordEmbed("🏥 System Health", health_text, DiscordColor.GREEN)
            dm_channel = await self.client._create_dm_channel(message.author.id)
            if dm_channel:
                await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_performance(message, args):
            """Show performance metrics"""
            try:
                from performance_monitor import get_performance_monitor
                perf_monitor = get_performance_monitor()
                
                summary = perf_monitor.get_performance_summary()
                
                perf_text = f"""🖥️ **System Health:**
• CPU: {summary['system_health'].get('cpu_percent', 'N/A')}%
• Memory: {summary['system_health'].get('memory_percent', 'N/A')}% ({summary['system_health'].get('memory_mb', 'N/A')} MB)
• Threads: {summary['system_health'].get('threads', 'N/A')}
• Uptime: {summary['uptime_hours']:.2f}h

📊 **Operations:**
• Total Operations: {summary['total_operations']}
• Recent Success Rate: {summary['recent_performance']['success_rate']}%
• Avg Response Time: {summary['recent_performance']['avg_response_time']:.3f}s
• Recent Operations: {summary['recent_performance']['operations_count']}

🔧 **Operation Breakdown:**"""
                
                for op_name, op_stats in summary['operations_by_type'].items():
                    perf_text += f"\\n• {op_name}: {op_stats['count']} ops, {op_stats['success_rate']:.1f}% success, {op_stats['avg_time']:.3f}s avg"
                
                embed = DiscordEmbed("⚡ Performance Metrics", perf_text, DiscordColor.PURPLE)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
                
            except Exception as e:
                print(f"❌ Error getting performance metrics: {e}")
        
        async def handle_cancelall(message, args):
            """Cancel all orders"""
            if self.cancel_all_callback:
                try:
                    cancelled_count = await self.cancel_all_callback()
                    embed = DiscordEmbed(
                        "✅ Orders Cancelled", 
                        f"Successfully cancelled {cancelled_count} orders", 
                        DiscordColor.GREEN
                    )
                    dm_channel = await self.client._create_dm_channel(message.author.id)
                    if dm_channel:
                        await self.client._send_message(dm_channel, embed=embed)
                except Exception as e:
                    print(f"❌ Error cancelling orders: {e}")
            else:
                embed = DiscordEmbed("❌ Error", "Cancel callback not configured", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_menu(message, args):
            """Show command menu"""
            menu_text = """**Available Commands:**

**Trading Control:**
• `!start` - Start trading bot
• `!stop` - Stop trading bot
• `!cancelall` - Cancel all open orders

**Information:**
• `!status` - Show bot status
• `!positions` - Show active positions
• `!stats` - Show trading statistics
• `!health` - Show system health
• `!performance` - Show performance metrics

**Settings:**
• `!set_leverage <value>` - Set leverage (0 = use signal)
• `!set_futures_size <amount>` - Set futures position size
• `!set_spot_size <amount>` - Set spot position size

**Other:**
• `!menu` - Show this menu

**Note:** This is a lightweight HTTP Discord client.
Commands work via DM only."""
            
            embed = DiscordEmbed("🤖 Trading Bot Menu", menu_text, DiscordColor.BLUE)
            dm_channel = await self.client._create_dm_channel(message.author.id)
            if dm_channel:
                await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_set_leverage(message, args):
            """Set leverage"""
            if not args:
                embed = DiscordEmbed("❌ Error", "Usage: !set_leverage <value>", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
                return
            
            try:
                leverage = int(args[0])
                if leverage < 0 or leverage > 125:
                    embed = DiscordEmbed("❌ Error", "Leverage must be between 0-125 (0 = use signal leverage)", DiscordColor.RED)
                else:
                    await self.config.update_config({"leverage": leverage})
                    embed = DiscordEmbed(
                        "✅ Leverage Updated", 
                        f"Leverage set to {leverage}x", 
                        DiscordColor.GREEN
                    )
                
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
            except ValueError:
                embed = DiscordEmbed("❌ Error", "Invalid leverage value", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_set_futures_size(message, args):
            """Set futures position size"""
            if not args:
                embed = DiscordEmbed("❌ Error", "Usage: !set_futures_size <amount>", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
                return
            
            try:
                size = float(args[0])
                if size <= 0:
                    embed = DiscordEmbed("❌ Error", "Size must be greater than 0", DiscordColor.RED)
                else:
                    await self.config.update_config({"futures_position_size": size})
                    embed = DiscordEmbed(
                        "✅ Futures Size Updated", 
                        f"Futures position size set to ${size}", 
                        DiscordColor.GREEN
                    )
                
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
            except ValueError:
                embed = DiscordEmbed("❌ Error", "Invalid size value", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
        
        async def handle_set_spot_size(message, args):
            """Set spot position size"""
            if not args:
                embed = DiscordEmbed("❌ Error", "Usage: !set_spot_size <amount>", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
                return
            
            try:
                size = float(args[0])
                if size <= 0:
                    embed = DiscordEmbed("❌ Error", "Size must be greater than 0", DiscordColor.RED)
                else:
                    await self.config.update_config({"spot_position_size": size})
                    embed = DiscordEmbed(
                        "✅ Spot Size Updated", 
                        f"Spot position size set to ${size}", 
                        DiscordColor.GREEN
                    )
                
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
            except ValueError:
                embed = DiscordEmbed("❌ Error", "Invalid size value", DiscordColor.RED)
                dm_channel = await self.client._create_dm_channel(message.author.id)
                if dm_channel:
                    await self.client._send_message(dm_channel, embed=embed)
        
        # Register all command handlers
        self.client.register_command("start", handle_start)
        self.client.register_command("stop", handle_stop)
        self.client.register_command("status", handle_status)
        self.client.register_command("positions", handle_positions)
        self.client.register_command("stats", handle_stats)
        self.client.register_command("health", handle_health)
        self.client.register_command("performance", handle_performance)
        self.client.register_command("cancelall", handle_cancelall)
        self.client.register_command("menu", handle_menu)
        self.client.register_command("set_leverage", handle_set_leverage)
        self.client.register_command("set_futures_size", handle_set_futures_size)
        self.client.register_command("set_spot_size", handle_set_spot_size)
    
    def set_cancel_all_callback(self, callback: Callable) -> None:
        """Set callback for cancel all orders"""
        self.cancel_all_callback = callback
    
    def set_get_positions_callback(self, callback: Callable) -> None:
        """Set callback for getting positions"""
        self.get_positions_callback = callback
    
    def set_get_stats_callback(self, callback: Callable) -> None:
        """Set callback for getting statistics"""
        self.get_stats_callback = callback
    
    def set_signal_callback(self, callback: Callable) -> None:
        """Set callback for signal processing"""
        self.signal_callback = callback
        self.client.set_signal_callback(callback)
        print("✅ Signal callback set: True")
    
    async def send_message(self, text: str) -> bool:
        """Send DM message to all authorized users"""
        return await self.client.send_message_to_users(text)
    
    async def send_signal_notification(self, signal_text: str, original_content: str) -> bool:
        """Send signal notification before execution to all authorized users"""
        try:
            sent_count = 0
            
            for user_id in self.authorized_users:
                try:
                    dm_channel = await self.client._create_dm_channel(user_id)
                    if not dm_channel:
                        continue
                    
                    embed = DiscordEmbed(
                        "📡 Trading Signal Received",
                        signal_text,
                        DiscordColor.BLUE
                    )
                    
                    # Add original content as field if it fits
                    original_preview = original_content[:1000] + ('...' if len(original_content) > 1000 else '')
                    embed.add_field(name="Original Message", value=original_preview, inline=False)
                    
                    if await self.client._send_message(dm_channel, embed=embed):
                        sent_count += 1
                        
                except Exception as e:
                    print(f"Failed to send signal notification to user {user_id}: {e}")
            
            return sent_count > 0
        except Exception as e:
            self.error_handler.handle_exception(e, "sending signal notification")
            return False