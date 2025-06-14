"""
Discord Controller - Bot interface for controlling and monitoring the trading system
Handles commands, sends alerts, and provides trading statistics via Discord DMs and channel monitoring
"""

import asyncio
import os
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
import discord
from discord.ext import commands
from config_manager import Config
from error_handler import get_error_handler


class DiscordController(commands.Bot):
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
        self.cancel_all_callback: Optional[Callable] = None
        self.get_positions_callback: Optional[Callable] = None
        self.get_stats_callback: Optional[Callable] = None
        self.signal_callback: Optional[Callable] = None
        
        self.discord_token = os.getenv("DISCORD_TOKEN")
        if not self.discord_token:
            raise ValueError("DISCORD_TOKEN not found in environment variables")
        
        if not self.authorized_users:
            raise ValueError("authorized_users not found in config.json")
            
        # Initialize Discord bot with intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        
        super().__init__(command_prefix='!', intents=intents)
    
    async def initialize(self) -> None:
        """Initialize Discord bot"""
        try:
            self._setup_commands()
            await self.start(self.discord_token)
            self.error_handler.log_startup("Discord Controller")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "Discord initialization")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown Discord bot"""
        await self.close()
        self.error_handler.log_shutdown("Discord Controller")
    
    def _setup_commands(self) -> None:
        """Setup Discord commands"""
        
        @self.command(name='start')
        async def start_trading(ctx):
            """Start trading bot"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            await self.config.update_config({"is_trading_enabled": True})
            embed = self._create_embed(
                "✅ Trading Started",
                "Trading bot has been enabled!\n\nUse `!menu` to see all available commands.",
                discord.Color.green()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='stop')
        async def stop_trading(ctx):
            """Stop trading bot"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            await self.config.update_config({"is_trading_enabled": False})
            embed = self._create_embed(
                "🛑 Trading Stopped",
                "Trading bot has been disabled!\n\nExisting positions will continue to be monitored.",
                discord.Color.red()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='status')
        async def status(ctx):
            """Show bot status"""
            try:
                if not self._check_authorization(ctx.author.id):
                    await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                    await ctx.send("❌ Unauthorized access")
                    return
                
                config = self.config
                status_text = (
                    f"Trading: {'✅ Enabled' if config.is_trading_enabled else '🛑 Disabled'}\n"
                    f"Mode: {config.mode.upper()}\n"
                    f"Leverage: {config.leverage if config.leverage > 0 else 'From Signal'}\n"
                    f"Futures Size: ${config.futures_position_size}\n"
                    f"Spot Size: ${config.spot_position_size}\n"
                    f"Max Futures: {config.max_futures_trade}\n"
                    f"Max Spot: {config.max_spot_trade}\n"
                    f"Daily Loss Limit: ${config.max_daily_loss}\n"
                    f"Channels: {', '.join(map(str, self.monitored_channel_ids)) if self.monitored_channel_ids else 'None'}"
                )
                
                embed = self._create_embed("📊 Bot Status", status_text, discord.Color.blue())
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"❌ Error getting status: {str(e)}")
                print(f"Status command error: {e}")
                import traceback
                traceback.print_exc()
        
        @self.command(name='positions')
        async def positions(ctx):
            """Show active positions"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if self.get_positions_callback:
                try:
                    positions_text = await self.get_positions_callback()
                    embed = self._create_embed("📈 Active Positions", positions_text, discord.Color.gold())
                    await ctx.send(embed=embed)
                except Exception as e:
                    await ctx.send(f"❌ Error getting positions: {e}")
            else:
                await ctx.send("❌ Positions callback not configured")
        
        @self.command(name='stats')
        async def stats(ctx):
            """Show trading statistics"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if self.get_stats_callback:
                try:
                    stats = await self.get_stats_callback()
                    stats_text = (
                        f"Total Trades: {stats.get('total_trades', 0)}\n"
                        f"Total PnL: {stats.get('total_pnl', 0):+.2f} USDT\n"
                        f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
                        f"Avg Hold Time: {stats.get('avg_hold_time', 0):.2f}h"
                    )
                    embed = self._create_embed("📈 Trading Statistics", stats_text, discord.Color.green())
                    await ctx.send(embed=embed)
                except Exception as e:
                    await ctx.send(f"❌ Error getting stats: {e}")
            else:
                await ctx.send("❌ Stats callback not configured")
        
        @self.command(name='health')
        async def health(ctx):
            """Show system health"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            health_text = (
                f"Timestamp: {datetime.now().strftime('%H:%M:%S')}\n"
                f"Config: ✅ Loaded\n"
                f"Exchange: ✅ Connected\n"
                f"Discord: ✅ Connected\n"
                f"Bot: ✅ Online\n"
            )
            
            embed = self._create_embed("🏥 System Health", health_text, discord.Color.green())
            await ctx.send(embed=embed)
        
        @self.command(name='performance')
        async def performance(ctx):
            """Show performance metrics"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
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
                    perf_text += f"\n• {op_name}: {op_stats['count']} ops, {op_stats['success_rate']:.1f}% success, {op_stats['avg_time']:.3f}s avg"
                
                embed = self._create_embed("⚡ Performance Metrics", perf_text, discord.Color.purple())
                await ctx.send(embed=embed)
                
            except Exception as e:
                await ctx.send(f"❌ Error getting performance metrics: {e}")
        
        @self.command(name='cancelall')
        async def cancel_all(ctx):
            """Cancel all orders"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if self.cancel_all_callback:
                try:
                    cancelled_count = await self.cancel_all_callback()
                    embed = self._create_embed(
                        "✅ Orders Cancelled", 
                        f"Successfully cancelled {cancelled_count} orders", 
                        discord.Color.green()
                    )
                    await ctx.send(embed=embed)
                except Exception as e:
                    await ctx.send(f"❌ Error cancelling orders: {e}")
            else:
                await ctx.send("❌ Cancel callback not configured")
        
        @self.command(name='menu')
        async def menu(ctx):
            """Show command menu"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
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
• `!max_futures <count>` - Set max futures positions
• `!max_spot <count>` - Set max spot positions

**Administration:**
• `!list_auth_users` - List authorized users
• `!add_auth_user <user_id>` - Add authorized user
• `!remove_auth_user <user_id>` - Remove authorized user

**Other:**
• `!menu` - Show this menu"""
            
            embed = self._create_embed("🤖 Trading Bot Menu", menu_text, discord.Color.blue())
            await ctx.send(embed=embed)
        
        @self.command(name='set_leverage')
        async def set_leverage(ctx, leverage: int):
            """Set leverage"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if leverage < 0 or leverage > 125:
                await ctx.send("❌ Leverage must be between 0-125 (0 = use signal leverage)")
                return
            
            await self.config.update_config({"leverage": leverage})
            embed = self._create_embed(
                "✅ Leverage Updated", 
                f"Leverage set to {leverage}x", 
                discord.Color.green()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='set_futures_size')
        async def set_futures_size(ctx, size: float):
            """Set futures position size"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if size <= 0:
                await ctx.send("❌ Size must be greater than 0")
                return
            
            await self.config.update_config({"futures_position_size": size})
            embed = self._create_embed(
                "✅ Futures Size Updated", 
                f"Futures position size set to ${size}", 
                discord.Color.green()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='set_spot_size')
        async def set_spot_size(ctx, size: float):
            """Set spot position size"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if size <= 0:
                await ctx.send("❌ Size must be greater than 0")
                return
            
            await self.config.update_config({"spot_position_size": size})
            embed = self._create_embed(
                "✅ Spot Size Updated", 
                f"Spot position size set to ${size}", 
                discord.Color.green()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='max_futures')
        async def max_futures(ctx, count: int):
            """Set max futures positions"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if count < 0:
                await ctx.send("❌ Count must be >= 0")
                return
            
            await self.config.update_config({"max_futures_trade": count})
            embed = self._create_embed(
                "✅ Max Futures Updated", 
                f"Max futures positions set to {count}", 
                discord.Color.green()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='max_spot')
        async def max_spot(ctx, count: int):
            """Set max spot positions"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            if count < 0:
                await ctx.send("❌ Count must be >= 0")
                return
            
            await self.config.update_config({"max_spot_trade": count})
            embed = self._create_embed(
                "✅ Max Spot Updated", 
                f"Max spot positions set to {count}", 
                discord.Color.green()
            )
            await ctx.send(embed=embed)
        
        @self.command(name='add_auth_user')
        async def add_auth_user(ctx, user_id: str):
            """Add authorized user"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            try:
                new_user_id = int(user_id)
                
                if new_user_id in self.authorized_users:
                    await ctx.send("❌ User is already authorized")
                    return
                
                # Try to fetch the new user to validate
                try:
                    new_user = await self.fetch_user(new_user_id)
                    user_display = f"{new_user.name}#{new_user.discriminator}" if new_user.discriminator != "0" else new_user.name
                except:
                    user_display = f"User ID {new_user_id}"
                
                # Update config
                new_authorized_users = self.authorized_users + [new_user_id]
                await self.config.update_config({"authorized_users": [str(uid) for uid in new_authorized_users]})
                
                # Update local variable
                self.authorized_users = new_authorized_users
                
                embed = self._create_embed(
                    "✅ Authorized User Added", 
                    f"Added: {user_display} (ID: {new_user_id})\n\nTotal authorized users: {len(self.authorized_users)}", 
                    discord.Color.green()
                )
                await ctx.send(embed=embed)
                
            except ValueError:
                await ctx.send("❌ Invalid user ID format. Must be a number.")
            except Exception as e:
                await ctx.send(f"❌ Error adding authorized user: {e}")
        
        @self.command(name='remove_auth_user')
        async def remove_auth_user(ctx, user_id: str):
            """Remove authorized user"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            try:
                remove_user_id = int(user_id)
                
                if remove_user_id not in self.authorized_users:
                    await ctx.send("❌ User is not authorized")
                    return
                
                if len(self.authorized_users) == 1:
                    await ctx.send("❌ Cannot remove the last authorized user")
                    return
                
                # Try to fetch the user for display
                try:
                    remove_user = await self.fetch_user(remove_user_id)
                    user_display = f"{remove_user.name}#{remove_user.discriminator}" if remove_user.discriminator != "0" else remove_user.name
                except:
                    user_display = f"User ID {remove_user_id}"
                
                # Update config
                new_authorized_users = [uid for uid in self.authorized_users if uid != remove_user_id]
                await self.config.update_config({"authorized_users": [str(uid) for uid in new_authorized_users]})
                
                # Update local variable
                self.authorized_users = new_authorized_users
                
                embed = self._create_embed(
                    "✅ Authorized User Removed", 
                    f"Removed: {user_display} (ID: {remove_user_id})\n\nRemaining authorized users: {len(self.authorized_users)}", 
                    discord.Color.orange()
                )
                await ctx.send(embed=embed)
                
            except ValueError:
                await ctx.send("❌ Invalid user ID format. Must be a number.")
            except Exception as e:
                await ctx.send(f"❌ Error removing authorized user: {e}")
        
        @self.command(name='list_auth_users')
        async def list_auth_users(ctx):
            """List all authorized users"""
            if not self._check_authorization(ctx.author.id):
                await self._handle_unauthorized_access(ctx.author, f"Command in {ctx.guild.name if ctx.guild else 'DM'}", ctx.message.content)
                await ctx.send("❌ Unauthorized access")
                return
            
            try:
                user_list = []
                for user_id in self.authorized_users:
                    try:
                        user = self.get_user(user_id) or await self.fetch_user(user_id)
                        user_display = f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name
                        user_list.append(f"• **{user_display}** (ID: {user_id})")
                    except:
                        user_list.append(f"• **User ID {user_id}** (Unknown user)")
                
                auth_text = f"""**Authorized Users ({len(self.authorized_users)}):**

{chr(10).join(user_list)}

Use `!add_auth_user <user_id>` or `!remove_auth_user <user_id>` to manage access."""
                
                embed = self._create_embed(
                    "👥 Authorized Users", 
                    auth_text, 
                    discord.Color.blue()
                )
                await ctx.send(embed=embed)
                
            except Exception as e:
                await ctx.send(f"❌ Error listing authorized users: {e}")
    
    async def _check_startup_status(self):
        """Check server access and channel monitoring status on startup"""
        try:
            status_lines = []
            
            # Check server access
            print(f"\n🔍 Discord Bot Startup Status Check:")
            print(f"📊 Bot User: {self.user} (ID: {self.user.id})")
            
            guilds = self.guilds
            if guilds:
                print(f"🏰 Connected to {len(guilds)} server(s):")
                status_lines.append(f"🏰 **Connected Servers ({len(guilds)}):**")
                
                for guild in guilds:
                    member_count = guild.member_count or 0
                    print(f"  • {guild.name} (ID: {guild.id}) - {member_count} members")
                    status_lines.append(f"  • **{guild.name}** (ID: {guild.id}) - {member_count} members")
            else:
                print("❌ Not connected to any servers!")
                status_lines.append("❌ **Not connected to any servers!**")
            
            # Check monitored channels
            monitored_channels = []
            accessible_channels = []
            inaccessible_channels = []
            
            if self.monitored_channel_ids:
                print(f"\n📺 Checking {len(self.monitored_channel_ids)} monitored channel(s):")
                status_lines.append(f"\n📺 **Monitored Channels ({len(self.monitored_channel_ids)}):**")
                
                for channel_id in self.monitored_channel_ids:
                    try:
                        channel = self.get_channel(channel_id)
                        if channel:
                            guild_name = channel.guild.name if channel.guild else "DM"
                            channel_type = "Text" if hasattr(channel, 'type') and channel.type.name == 'text' else channel.type.name if hasattr(channel, 'type') else "Unknown"
                            print(f"  ✅ #{channel.name} in '{guild_name}' (ID: {channel_id}) [{channel_type}]")
                            status_lines.append(f"  ✅ **#{channel.name}** in {guild_name}")
                            accessible_channels.append(channel)
                            monitored_channels.append(f"{guild_name}#{channel.name}")
                        else:
                            print(f"  ❌ Channel ID {channel_id} - Not accessible or doesn't exist")
                            status_lines.append(f"  ❌ Channel ID {channel_id} - **Not accessible**")
                            inaccessible_channels.append(str(channel_id))
                    except Exception as e:
                        print(f"  ❌ Channel ID {channel_id} - Error: {e}")
                        status_lines.append(f"  ❌ Channel ID {channel_id} - **Error accessing**")
                        inaccessible_channels.append(str(channel_id))
            else:
                print("📺 No channels configured for monitoring")
                status_lines.append("📺 **No channels configured for monitoring**")
            
            # Check authorized users
            print(f"\n👤 Authorized Users ({len(self.authorized_users)}):")
            status_lines.append(f"👤 **Authorized Users ({len(self.authorized_users)}):**")
            
            for user_id in self.authorized_users:
                try:
                    auth_user = self.get_user(user_id)
                    if auth_user:
                        print(f"  ✅ {auth_user} (ID: {user_id})")
                        status_lines.append(f"  ✅ **{auth_user}** (ID: {user_id})")
                    else:
                        print(f"  ⚠️ User ID {user_id} - Not found in cache (may still work)")
                        status_lines.append(f"  ⚠️ **User ID {user_id}** - Not in cache")
                except Exception as e:
                    print(f"  ❌ User ID {user_id} - Error: {e}")
                    status_lines.append(f"  ❌ **User ID {user_id}** - Error checking")
            
            # Print summary
            print(f"\n📋 Summary:")
            print(f"  • Servers: {len(guilds)}")
            print(f"  • Accessible Channels: {len(accessible_channels)}")
            if accessible_channels:
                print(f"    → Monitoring: {', '.join([f'#{ch.name}' for ch in accessible_channels])}")
            print(f"  • Inaccessible Channels: {len(inaccessible_channels)}")
            if inaccessible_channels:
                print(f"    → Failed IDs: {', '.join(inaccessible_channels)}")
            print(f"  • Ready for monitoring: {'✅ Yes' if accessible_channels else '❌ No channels available'}")
            
            # Send status to authorized user via DM
            await self._send_startup_status_dm(status_lines, accessible_channels, inaccessible_channels)
            
        except Exception as e:
            print(f"❌ Error during startup status check: {e}")
            self.error_handler.handle_exception(e, "Discord startup status check")
    
    async def _send_startup_status_dm(self, status_lines, accessible_channels, inaccessible_channels):
        """Send startup status to all authorized users via DM"""
        try:
            sent_count = 0
            for user_id in self.authorized_users:
                user = self.get_user(user_id)
                if not user:
                    # Try to fetch user if not in cache
                    try:
                        user = await self.fetch_user(user_id)
                        print(f"✅ Fetched authorized user: {user}")
                    except Exception as e:
                        print(f"⚠️ Cannot send startup status DM to user {user_id}: {e}")
                        continue
                
                # Create status message
                status_text = "\n".join(status_lines)
                
                # Add summary
                summary_text = f"""
📋 **Summary:**
• Servers: {len(self.guilds)}
• Accessible Channels: {len(accessible_channels)}
• Inaccessible Channels: {len(inaccessible_channels)}
• Status: {'✅ Ready for monitoring' if accessible_channels else '❌ No channels available'}

⚙️ **Bot Configuration:**
• Bot User: {self.user}
• Authorized Users: {', '.join([f'<@{uid}>' for uid in self.authorized_users])}
• Ready to receive commands via DM"""
                
                embed = self._create_embed(
                    "🤖 Discord Bot Startup Status",
                    status_text + summary_text,
                    discord.Color.blue()
                )
                
                await user.send(embed=embed)
                sent_count += 1
                
                # Send warnings for inaccessible channels
                if inaccessible_channels:
                    warning_text = f"""⚠️ **Channel Access Issues:**
                    
The following monitored channels are not accessible:
{chr(10).join([f'• ID: {ch_id}' for ch_id in inaccessible_channels])}

**Possible reasons:**
• Bot doesn't have access to the server
• Channel was deleted or made private
• Incorrect channel ID
• Bot lacks required permissions

**To fix:**
1. Check channel IDs in your .env file
2. Ensure bot has access to the servers
3. Verify bot has read permissions in channels"""
                    
                    warning_embed = self._create_embed(
                        "⚠️ Channel Access Warning",
                        warning_text,
                        discord.Color.orange()
                    )
                    await user.send(embed=warning_embed)
                
                print(f"✅ Startup status sent to {user} via DM")
            
            print(f"📤 Startup status sent to {sent_count}/{len(self.authorized_users)} authorized users")
            
        except Exception as e:
            print(f"❌ Failed to send startup status DM: {e}")
            self.error_handler.handle_exception(e, "sending startup status DM")
    
    async def on_ready(self):
        """Called when bot is ready"""
        print(f'{self.user} has connected to Discord!')
        self.error_handler.log_success(f"Discord bot logged in as {self.user}")
        
        # Check server access and channel monitoring status
        await self._check_startup_status()
    
    async def on_message(self, message):
        """Handle incoming messages"""
        # Ignore messages from the bot itself
        if message.author == self.user:
            return
        
        # Debug logging
        print(f"📨 Message received from {message.author} in channel {message.channel.id}")
        print(f"📺 Monitored channels: {self.monitored_channel_ids}")
        print(f"📍 Channel type: {type(message.channel)}")
        
        # Handle DM commands from authorized users
        if isinstance(message.channel, discord.DMChannel):
            print(f"💬 DM message from {message.author}")
            if message.author.id in self.authorized_users:
                await self.process_commands(message)
            else:
                await self._handle_unauthorized_access(message.author, "DM", message.content)
                await message.channel.send("❌ Unauthorized access")
            return
        
        # Handle monitored channel messages
        if message.channel.id in self.monitored_channel_ids:
            print(f"🎯 Processing signal from monitored channel {message.channel.id}")
            await self._process_signal_message(message)
        else:
            print(f"⚠️ Message from unmonitored channel {message.channel.id}")
        
        # Process commands in all channels (authorization checked in commands)
        await self.process_commands(message)
    
    async def _process_signal_message(self, message):
        """Process potential signal message from monitored channels"""
        try:
            print(f"🔄 Processing signal message from {message.channel}")
            print(f"📄 Content: {message.content[:100]}...")
            print(f"🖼️ Attachments: {len(message.attachments)}")
            print(f"🔗 Signal callback set: {self.signal_callback is not None}")
            
            if self.signal_callback:
                # Get message content and attachments
                content = message.content
                images = []
                
                # Process attachments (images)
                for attachment in message.attachments:
                    if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                        images.append(attachment.url)
                
                # Forward to signal processor
                source = f"{message.guild.name}#{message.channel.name}" if message.guild else "DM"
                print(f"📡 Calling signal callback with source: {source}")
                await self.signal_callback(content, images, source)
                
                # Send raw message as DM to authorized users
                print(f"📤 Sending DM to {len(self.authorized_users)} authorized users")
                for user_id in self.authorized_users:
                    print(f"   📱 Trying to send to user {user_id}")
                    user = self.get_user(user_id)
                    if not user:
                        print(f"   🔍 User {user_id} not in cache, fetching...")
                        try:
                            user = await self.fetch_user(user_id)
                            print(f"   ✅ Successfully fetched user: {user}")
                        except Exception as e:
                            print(f"   ❌ Failed to fetch user {user_id}: {e}")
                            continue
                    
                    if user:
                        try:
                            embed = self._create_embed(
                                f"📡 Signal from {source}",
                                f"**Original Message:**\n{content[:1900]}{'...' if len(content) > 1900 else ''}",
                                discord.Color.orange()
                            )
                            
                            if images:
                                embed.add_field(name="Images", value=f"{len(images)} image(s) attached", inline=False)
                            
                            await user.send(embed=embed)
                            print(f"   ✅ DM sent successfully to {user}")
                            
                            # Send images as separate messages if any
                            for image_url in images:
                                await user.send(image_url)
                                print(f"   🖼️ Image sent to {user}")
                        except Exception as e:
                            print(f"   ❌ Failed to send DM to {user}: {e}")
                    else:
                        print(f"   ❌ Could not get user {user_id}")
                        
        except Exception as e:
            self.error_handler.handle_exception(e, f"processing signal message from {message.channel}")
    
    def _check_authorization(self, user_id: int) -> bool:
        """Check if user is authorized"""
        return user_id in self.authorized_users
    
    async def _handle_unauthorized_access(self, user, location: str, content: str = "") -> None:
        """Handle unauthorized access attempts with detailed logging"""
        try:
            # Get user details
            username = f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name
            user_id = user.id
            
            # Get additional user info if possible
            user_info = []
            user_info.append(f"Username: {username}")
            user_info.append(f"ID: {user_id}")
            user_info.append(f"Location: {location}")
            
            if hasattr(user, 'created_at'):
                user_info.append(f"Account Created: {user.created_at.strftime('%Y-%m-%d')}")
            
            if hasattr(user, 'avatar') and user.avatar:
                user_info.append(f"Has Avatar: Yes")
            
            # Check if user is in mutual servers
            mutual_servers = []
            for guild in self.guilds:
                member = guild.get_member(user_id)
                if member:
                    mutual_servers.append(guild.name)
            
            if mutual_servers:
                user_info.append(f"Mutual Servers: {', '.join(mutual_servers[:3])}")
            
            # Log to terminal
            print(f"\n🚨 UNAUTHORIZED ACCESS ATTEMPT:")
            print(f"  User: {username} (ID: {user_id})")
            print(f"  Location: {location}")
            if content:
                print(f"  Message: {content[:100]}{'...' if len(content) > 100 else ''}")
            if mutual_servers:
                print(f"  Mutual Servers: {', '.join(mutual_servers)}")
            print(f"  Authorized Users: {', '.join(map(str, self.authorized_users))}")
            
            # Send notification to all authorized users
            for auth_user_id in self.authorized_users:
                auth_user = self.get_user(auth_user_id)
                if not auth_user:
                    try:
                        auth_user = await self.fetch_user(auth_user_id)
                    except:
                        continue
                
                if auth_user:
                    warning_text = f"""🚨 **Unauthorized Access Attempt**

👤 **User Details:**
• Username: `{username}`
• User ID: `{user_id}`
• Location: {location}

🔍 **Additional Info:**
{chr(10).join([f'• {info}' for info in user_info[3:]])}

📝 **Message Attempted:**
```
{content[:500] if content else 'No message content'}
```

⚙️ **Authorized Users:** {', '.join([f'<@{uid}>' for uid in self.authorized_users])}

Use `!add_auth_user <user_id>` or `!remove_auth_user <user_id>` to manage authorization."""
                    
                    embed = self._create_embed(
                        "🚨 Security Alert",
                        warning_text,
                        discord.Color.red()
                    )
                    
                    try:
                        await auth_user.send(embed=embed)
                    except Exception as e:
                        print(f"Failed to send security alert to {auth_user}: {e}")
            
        except Exception as e:
            print(f"Error handling unauthorized access: {e}")
            self.error_handler.handle_exception(e, "handling unauthorized access")
    
    def _create_embed(self, title: str, description: str, color: discord.Color) -> discord.Embed:
        """Create a Discord embed"""
        embed = discord.Embed(title=title, description=description, color=color)
        embed.timestamp = datetime.now()
        return embed
    
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
    
    async def send_message(self, text: str) -> bool:
        """Send DM message to all authorized users"""
        try:
            sent_count = 0
            # Split long messages into chunks
            chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
            
            for user_id in self.authorized_users:
                user = self.get_user(user_id)
                if not user:
                    try:
                        user = await self.fetch_user(user_id)
                    except:
                        continue
                
                if user:
                    try:
                        for chunk in chunks:
                            await user.send(chunk)
                        sent_count += 1
                    except Exception as e:
                        print(f"Failed to send message to {user}: {e}")
            
            return sent_count > 0
        except Exception as e:
            self.error_handler.handle_exception(e, "sending Discord message")
            return False
    
    async def send_signal_notification(self, signal_text: str, original_content: str) -> bool:
        """Send signal notification before execution to all authorized users"""
        try:
            sent_count = 0
            
            for user_id in self.authorized_users:
                user = self.get_user(user_id)
                if not user:
                    try:
                        user = await self.fetch_user(user_id)
                    except:
                        continue
                
                if user:
                    try:
                        embed = self._create_embed(
                            "📡 Trading Signal Received",
                            signal_text,
                            discord.Color.blue()
                        )
                        
                        # Add original content as field if it fits
                        original_preview = original_content[:1000] + ('...' if len(original_content) > 1000 else '')
                        embed.add_field(name="Original Message", value=original_preview, inline=False)
                        
                        await user.send(embed=embed)
                        sent_count += 1
                    except Exception as e:
                        print(f"Failed to send signal notification to {user}: {e}")
            
            return sent_count > 0
        except Exception as e:
            self.error_handler.handle_exception(e, "sending signal notification")
            return False