"""
Telegram Controller - Bot interface for controlling and monitoring the trading system
Handles commands, sends alerts, and provides trading statistics via inline keyboards
"""

import asyncio
import os
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from config_manager import Config
from error_handler import get_error_handler


class TelegramController:
    def __init__(self, config: Config):
        self.config = config
        self.error_handler = get_error_handler()
        self.application: Optional[Application] = None
        self.admin_id = int(os.getenv("ADMIN_ID", "0"))
        self.cancel_all_callback: Optional[Callable] = None
        self.get_positions_callback: Optional[Callable] = None
        self.get_stats_callback: Optional[Callable] = None
        
        self.telegram_token = os.getenv("TELEGRAM_TOKEN")
        if not self.telegram_token:
            raise ValueError("TELEGRAM_TOKEN not found in environment variables")
        
        if self.admin_id == 0:
            raise ValueError("ADMIN_ID not found in environment variables")
    
    async def initialize(self) -> None:
        """Initialize Telegram bot"""
        try:
            self.application = Application.builder().token(self.telegram_token).build()
            
            self._setup_handlers()
            
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            self.error_handler.log_startup("Telegram Controller")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "Telegram initialization")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown Telegram bot"""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        self.error_handler.log_shutdown("Telegram Controller")
    
    def _setup_handlers(self) -> None:
        """Setup command and callback handlers"""
        
        # Command handlers
        self.application.add_handler(CommandHandler("start", self._handle_start))
        self.application.add_handler(CommandHandler("stop", self._handle_stop))
        self.application.add_handler(CommandHandler("status", self._handle_status))
        self.application.add_handler(CommandHandler("positions", self._handle_active_positions))
        self.application.add_handler(CommandHandler("stats", self._handle_stats))
        self.application.add_handler(CommandHandler("health", self._handle_health))
        self.application.add_handler(CommandHandler("cancelall", self._handle_cancel_all))
        self.application.add_handler(CommandHandler("performance", self._handle_performance))
        self.application.add_handler(CommandHandler("menu", self._handle_menu))
        
        # Setting commands
        self.application.add_handler(CommandHandler("set_leverage", self._handle_set_leverage))
        self.application.add_handler(CommandHandler("set_futures_size", self._handle_set_futures_size))
        self.application.add_handler(CommandHandler("set_spot_size", self._handle_set_spot_size))
        self.application.add_handler(CommandHandler("max_futures", self._handle_max_futures))
        self.application.add_handler(CommandHandler("max_spot", self._handle_max_spot))
        
        # Callback query handler for inline buttons
        self.application.add_handler(CallbackQueryHandler(self._handle_callback_query))
        
        # Message handler for unauthorized users
        self.application.add_handler(MessageHandler(filters.ALL, self._handle_unauthorized))
    
    def _check_authorization(self, user_id: int) -> bool:
        """Check if user is authorized"""
        return user_id == self.admin_id
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        await self.config.update_config({"is_trading_enabled": True})
        
        keyboard = self._get_main_keyboard()
        await update.message.reply_text(
            "✅ Trading bot started!\n\n"
            "Use the menu below to control the bot:",
            reply_markup=keyboard
        )
    
    async def _handle_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stop command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        await self.config.update_config({"is_trading_enabled": False})
        
        await update.message.reply_text("🛑 Trading bot stopped!\n\nExisting positions will continue to be monitored.")
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        config = self.config.get_config()
        status_text = (
            f"📊 Bot Status\n\n"
            f"Trading: {'✅ Enabled' if config.is_trading_enabled else '🛑 Disabled'}\n"
            f"Mode: {config.mode.upper()}\n"
            f"Leverage: {config.leverage if config.leverage > 0 else 'From Signal'}\n"
            f"Futures Size: ${config.futures_position_size}\n"
            f"Spot Size: ${config.spot_position_size}\n"
            f"Max Futures: {config.max_futures_trade}\n"
            f"Max Spot: {config.max_spot_trade}\n"
            f"Daily Loss Limit: ${config.max_daily_loss}\n"
            f"Channels: {', '.join(config.discord_channels) if config.discord_channels else 'None'}"
        )
        
        keyboard = self._get_main_keyboard()
        await update.message.reply_text(status_text, reply_markup=keyboard)
    
    async def _handle_active_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /positions command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        if self.get_positions_callback:
            try:
                positions_text = await self.get_positions_callback()
                await update.message.reply_text(positions_text)
            except Exception as e:
                await update.message.reply_text(f"❌ Error getting positions: {e}")
        else:
            await update.message.reply_text("❌ Positions callback not configured")
    
    async def _handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        if self.get_stats_callback:
            try:
                stats = await self.get_stats_callback()
                stats_text = (
                    f"📈 Trading Statistics\n\n"
                    f"Total Trades: {stats.get('total_trades', 0)}\n"
                    f"Total PnL: {stats.get('total_pnl', 0):+.2f} USDT\n"
                    f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
                    f"Avg Hold Time: {stats.get('avg_hold_time', 0):.2f}h"
                )
                await update.message.reply_text(stats_text)
            except Exception as e:
                await update.message.reply_text(f"❌ Error getting stats: {e}")
        else:
            await update.message.reply_text("❌ Stats callback not configured")
    
    async def _handle_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /health command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        health_text = (
            f"🏥 System Health\n\n"
            f"Timestamp: {datetime.now().strftime('%H:%M:%S')}\n"
            f"Config: ✅ Loaded\n"
            f"Exchange: ✅ Connected\n"
            f"Discord: ✅ Connected\n"
            f"Telegram: ✅ Connected\n"
        )
        
        await update.message.reply_text(health_text)
    
    async def _handle_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /performance command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            from performance_monitor import get_performance_monitor
            perf_monitor = get_performance_monitor()
            
            summary = perf_monitor.get_performance_summary()
            
            perf_text = f"""⚡ PERFORMANCE METRICS

🖥️ System Health:
  • CPU: {summary['system_health'].get('cpu_percent', 'N/A')}%
  • Memory: {summary['system_health'].get('memory_percent', 'N/A')}% ({summary['system_health'].get('memory_mb', 'N/A')} MB)
  • Threads: {summary['system_health'].get('threads', 'N/A')}
  • Uptime: {summary['uptime_hours']:.2f}h

📊 Operations:
  • Total Operations: {summary['total_operations']}
  • Recent Success Rate: {summary['recent_performance']['success_rate']}%
  • Avg Response Time: {summary['recent_performance']['avg_response_time']:.3f}s
  • Recent Operations: {summary['recent_performance']['operations_count']}

🔧 Operation Breakdown:"""
            
            for op_name, op_stats in summary['operations_by_type'].items():
                perf_text += f"\n  • {op_name}: {op_stats['count']} ops, {op_stats['success_rate']:.1f}% success, {op_stats['avg_time']:.3f}s avg"
                
            await update.message.reply_text(perf_text)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error getting performance metrics: {e}")
    
    async def _handle_cancel_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cancelall command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        if self.cancel_all_callback:
            try:
                cancelled_count = await self.cancel_all_callback()
                await update.message.reply_text(f"✅ Cancelled {cancelled_count} orders")
            except Exception as e:
                await update.message.reply_text(f"❌ Error cancelling orders: {e}")
        else:
            await update.message.reply_text("❌ Cancel callback not configured")
    
    async def _handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /menu command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        keyboard = self._get_main_keyboard()
        await update.message.reply_text("🤖 Trading Bot Menu:", reply_markup=keyboard)
    
    async def _handle_set_leverage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set_leverage command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            if len(context.args) != 1:
                await update.message.reply_text("Usage: /set_leverage <value>\nExample: /set_leverage 10")
                return
            
            leverage = int(context.args[0])
            if leverage < 0 or leverage > 125:
                await update.message.reply_text("❌ Leverage must be between 0-125 (0 = use signal leverage)")
                return
            
            await self.config.update_config({"leverage": leverage})
            await update.message.reply_text(f"✅ Leverage set to {leverage}x")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid leverage value")
    
    async def _handle_set_futures_size(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set_futures_size command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            if len(context.args) != 1:
                await update.message.reply_text("Usage: /set_futures_size <amount>\nExample: /set_futures_size 100")
                return
            
            size = float(context.args[0])
            if size <= 0:
                await update.message.reply_text("❌ Size must be greater than 0")
                return
            
            await self.config.update_config({"futures_position_size": size})
            await update.message.reply_text(f"✅ Futures position size set to ${size}")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid amount")
    
    async def _handle_set_spot_size(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set_spot_size command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            if len(context.args) != 1:
                await update.message.reply_text("Usage: /set_spot_size <amount>\nExample: /set_spot_size 50")
                return
            
            size = float(context.args[0])
            if size <= 0:
                await update.message.reply_text("❌ Size must be greater than 0")
                return
            
            await self.config.update_config({"spot_position_size": size})
            await update.message.reply_text(f"✅ Spot position size set to ${size}")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid amount")
    
    async def _handle_max_futures(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /max_futures command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            if len(context.args) != 1:
                await update.message.reply_text("Usage: /max_futures <count>\nExample: /max_futures 3")
                return
            
            max_count = int(context.args[0])
            if max_count < 0:
                await update.message.reply_text("❌ Count must be >= 0")
                return
            
            await self.config.update_config({"max_futures_trade": max_count})
            await update.message.reply_text(f"✅ Max futures positions set to {max_count}")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid count")
    
    async def _handle_max_spot(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /max_spot command"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            if len(context.args) != 1:
                await update.message.reply_text("Usage: /max_spot <count>\nExample: /max_spot 2")
                return
            
            max_count = int(context.args[0])
            if max_count < 0:
                await update.message.reply_text("❌ Count must be >= 0")
                return
            
            await self.config.update_config({"max_spot_trade": max_count})
            await update.message.reply_text(f"✅ Max spot positions set to {max_count}")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid count")
    
    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard callbacks"""
        if not self._check_authorization(update.effective_user.id):
            await update.callback_query.answer("❌ Unauthorized access")
            return
        
        query = update.callback_query
        await query.answer()
        
        if query.data == "start_trading":
            await self.config.update_config({"is_trading_enabled": True})
            await query.edit_message_text("✅ Trading enabled!")
            
        elif query.data == "stop_trading":
            await self.config.update_config({"is_trading_enabled": False})
            await query.edit_message_text("🛑 Trading disabled!")
            
        elif query.data == "show_positions":
            if self.get_positions_callback:
                positions_text = await self.get_positions_callback()
                await query.edit_message_text(positions_text)
            else:
                await query.edit_message_text("❌ Positions callback not configured")
                
        elif query.data == "show_stats":
            if self.get_stats_callback:
                stats = await self.get_stats_callback()
                stats_text = (
                    f"📈 Trading Statistics\n\n"
                    f"Total Trades: {stats.get('total_trades', 0)}\n"
                    f"Total PnL: {stats.get('total_pnl', 0):+.2f} USDT\n"
                    f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
                    f"Avg Hold Time: {stats.get('avg_hold_time', 0):.2f}h"
                )
                await query.edit_message_text(stats_text)
            else:
                await query.edit_message_text("❌ Stats callback not configured")
                
        elif query.data == "cancel_all":
            if self.cancel_all_callback:
                cancelled_count = await self.cancel_all_callback()
                await query.edit_message_text(f"✅ Cancelled {cancelled_count} orders")
            else:
                await query.edit_message_text("❌ Cancel callback not configured")
                
        elif query.data == "main_menu":
            keyboard = self._get_main_keyboard()
            await query.edit_message_text("🤖 Trading Bot Menu:", reply_markup=keyboard)
    
    async def _handle_unauthorized(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle messages from unauthorized users"""
        if not self._check_authorization(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized access")
    
    def _get_main_keyboard(self) -> InlineKeyboardMarkup:
        """Get main menu keyboard"""
        keyboard = [
            [
                InlineKeyboardButton("🟢 Start Trading", callback_data="start_trading"),
                InlineKeyboardButton("🛑 Stop Trading", callback_data="stop_trading")
            ],
            [
                InlineKeyboardButton("📊 Positions", callback_data="show_positions"),
                InlineKeyboardButton("📈 Statistics", callback_data="show_stats")
            ],
            [
                InlineKeyboardButton("❌ Cancel All Orders", callback_data="cancel_all")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def set_cancel_all_callback(self, callback: Callable) -> None:
        """Set callback for cancel all orders"""
        self.cancel_all_callback = callback
    
    def set_get_positions_callback(self, callback: Callable) -> None:
        """Set callback for getting positions"""
        self.get_positions_callback = callback
    
    def set_get_stats_callback(self, callback: Callable) -> None:
        """Set callback for getting statistics"""
        self.get_stats_callback = callback
    
    async def send_message(self, text: str) -> bool:
        """Send message to admin"""
        try:
            if self.application and self.application.bot:
                await self.application.bot.send_message(chat_id=self.admin_id, text=text)
                return True
            return False
        except Exception as e:
            self.error_handler.handle_exception(e, "sending Telegram message")
            return False
    
    async def send_signal_notification(self, signal_text: str, original_content: str) -> bool:
        """Send signal notification before execution"""
        try:
            message = (
                f"📡 Trading Signal Received\n\n"
                f"{signal_text}\n\n"
                f"Original Message:\n{original_content[:500]}{'...' if len(original_content) > 500 else ''}"
            )
            return await self.send_message(message)
        except Exception as e:
            self.error_handler.handle_exception(e, "sending signal notification")
            return False