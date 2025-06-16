"""
Main - Orchestrates all modules and manages the trading bot lifecycle
Coordinates Discord listener, signal parser, trade manager, and Telegram controller
Uses HTTP-based components for Termux compatibility
"""

import asyncio
import signal
import sys
import os
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv
from config_manager import ConfigManager
from error_handler import get_error_handler
from performance_monitor import get_performance_monitor

# Use HTTP-based components for Termux compatibility
try:
    # Try to import WebSocket-based components first
    from exchange_connector import ExchangeConnector
    from signal_parser import SignalParser, TradeSignal
    from discord_controller import DiscordController
    USE_HTTP_FALLBACK = False
except ImportError as e:
    print(f"⚠️ WebSocket components not available ({e}), using HTTP fallback for Termux compatibility")
    from exchange_connector_http import ExchangeConnectorHTTP as ExchangeConnector
    from signal_parser_http import SignalParserHTTP as SignalParser, TradeSignal
    from discord_controller_http import DiscordControllerHTTP as DiscordController
    USE_HTTP_FALLBACK = True

from trade_manager import TradeManager
from trade_tracker import TradeTracker


class TradingBot:
    def __init__(self):
        self.error_handler = get_error_handler()
        self.performance_monitor = get_performance_monitor()
        self.config_manager: Optional[ConfigManager] = None
        self.exchange: Optional[ExchangeConnector] = None
        self.signal_parser: Optional[SignalParser] = None
        self.trade_manager: Optional[TradeManager] = None
        self.trade_tracker: Optional[TradeTracker] = None
        self.discord_controller: Optional[DiscordController] = None
        self._shutdown_event = asyncio.Event()
        
    async def initialize(self) -> None:
        """Initialize all bot components"""
        try:
            self.error_handler.log_info("🤖 Initializing Trading Bot...")
            
            # Initialize performance monitoring first
            await self.performance_monitor.initialize()
            
            # Initialize config manager
            with self.performance_monitor.time_operation("config_initialization"):
                self.config_manager = ConfigManager()
                await self.config_manager.initialize()
                config = self.config_manager.get_config()
            
            # Initialize exchange connector
            with self.performance_monitor.time_operation("exchange_initialization"):
                self.exchange = ExchangeConnector(config)
                await self.exchange.initialize()
            
            # Initialize signal parser
            with self.performance_monitor.time_operation("signal_parser_initialization"):
                self.signal_parser = SignalParser()
                await self.signal_parser.initialize()
            
            # Initialize trade manager
            with self.performance_monitor.time_operation("trade_manager_initialization"):
                self.trade_manager = TradeManager(self.exchange, config)
                await self.trade_manager.initialize()
            
            # Initialize trade tracker
            with self.performance_monitor.time_operation("trade_tracker_initialization"):
                self.trade_tracker = TradeTracker(self.exchange, config)
                await self.trade_tracker.initialize()
            
            # Initialize Discord controller (handles both commands and listening)
            with self.performance_monitor.time_operation("discord_controller_initialization"):
                if USE_HTTP_FALLBACK:
                    self.discord_controller = DiscordController(config)
                    await self.discord_controller.initialize()
                else:
                    self.discord_controller = DiscordController(config)
                    # Don't start the bot yet, just create it
            
            # Setup callbacks and connections BEFORE starting Discord (WebSocket version only)
            await self._setup_callbacks()
            
            # Now start the Discord bot with callbacks already set (WebSocket version only)
            if not USE_HTTP_FALLBACK:
                await self.discord_controller.initialize()
            
            # Subscribe to config changes
            self.config_manager.subscribe(self._on_config_change)
            
            # Setup signal handlers for graceful shutdown
            self._setup_signal_handlers()
            
            mode_text = "HTTP (Termux Compatible)" if USE_HTTP_FALLBACK else "WebSocket (Full Features)"
            self.error_handler.log_success(f"🚀 Trading Bot initialized successfully! Mode: {mode_text}")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "bot initialization")
            raise
    
    async def _setup_callbacks(self) -> None:
        """Setup inter-module callbacks"""
        try:
            # Set Discord callback for error handler
            self.error_handler.set_telegram_callback(self.discord_controller.send_message)
            
            # Set Discord callback for trade tracker
            self.trade_tracker.set_telegram_callback(self.discord_controller.send_message)
            
            # Set Discord signal callback for message processing
            self.discord_controller.set_signal_callback(self._process_discord_signal)
            print(f"✅ Signal callback set: {self.discord_controller.signal_callback is not None}")
            
            # Set Discord command callbacks
            self.discord_controller.set_cancel_all_callback(self.trade_manager.cancel_all_orders)
            self.discord_controller.set_get_positions_callback(self.trade_tracker.get_active_positions_summary)
            self.discord_controller.set_get_stats_callback(self.trade_tracker.get_trade_statistics)
            
            self.error_handler.log_success("Callbacks configured")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "setting up callbacks")
            raise
    
    async def _process_discord_signal(self, content: str, images: list, source: str) -> None:
        """Process signal from Discord"""
        try:
            print(f"🚀 _process_discord_signal called with:")
            print(f"   📄 Content length: {len(content)}")
            print(f"   🖼️ Images: {len(images)}")
            print(f"   📍 Source: {source}")
            
            self.error_handler.log_signal_received(source, "parsing...")
            
            # Parse signal using Gemini
            signal = await self.signal_parser.parse_signal(content, images, source)
            
            if signal:
                # Send detailed parsed signal to Telegram before execution
                filtered_tps = self.signal_parser.get_filtered_take_profits(signal.take_profits)
                
                signal_text = f"""📈 TRADING SIGNAL DETECTED

🎯 Signal Details:
  • Symbol: {signal.symbol}
  • Direction: {signal.direction.upper()}
  • Entry Price: {signal.entry_price}
  • Stop Loss: {signal.stop_loss}
  • Take Profits: {', '.join(map(str, signal.take_profits))}
  • Using TPs: {', '.join(map(str, filtered_tps))} (1st, 3rd, 5th)
  • Leverage: {signal.leverage or 'From Config'}
  • Trade Type: {signal.trade_type.upper()}
  • Confidence: {signal.confidence:.2f}
  • Source: {source}

💡 Risk Analysis:
  • Risk/Reward: {abs(signal.entry_price - signal.stop_loss) / abs(signal.take_profits[0] - signal.entry_price):.2f}:1
  • Stop Loss %: {abs(signal.stop_loss - signal.entry_price) / signal.entry_price * 100:.2f}%
  • First TP %: {abs(signal.take_profits[0] - signal.entry_price) / signal.entry_price * 100:.2f}%

📱 Raw Discord Message:
{content[:1000]}{'...' if len(content) > 1000 else ''}

⏳ Executing trade..."""
                
                await self.discord_controller.send_message(signal_text)
                
                # Queue signal for execution
                await self.trade_manager.queue_signal(signal)
            else:
                # Send error notification to Discord when Gemini fails
                error_message = f"""❌ SIGNAL EXTRACTION FAILED

🔍 **Source:** {source}
🤖 **AI Parser:** Gemini 1.5 Flash
⚠️ **Status:** Failed to extract valid trading signal

📱 **Raw Message:**
{content[:800]}{'...' if len(content) > 800 else ''}

💡 **Possible Reasons:**
• Message doesn't contain a trading signal
• Signal format not recognized by AI
• Missing required information (symbol, direction, entry, etc.)
• Gemini API error or rate limit

🔧 **Next Steps:**
• Check if message contains proper signal format
• Verify all required fields are present
• Check terminal logs for detailed error info"""
                
                await self.discord_controller.send_message(error_message)
                self.error_handler.log_error(f"❌ Gemini failed to extract signal from {source}")
                
        except Exception as e:
            # Send exception notification to Discord
            exception_message = f"""💥 SIGNAL PROCESSING ERROR

🔍 **Source:** {source}
❌ **Error:** {str(e)[:200]}{'...' if len(str(e)) > 200 else ''}
🤖 **AI Parser:** Gemini 1.5 Flash (Only)

📱 **Raw Message:**
{content[:500] if 'content' in locals() else 'Content not available'}{'...' if 'content' in locals() and len(content) > 500 else ''}

🔧 **Action Required:**
• Check terminal logs for full error details
• Verify Gemini API key and quota
• Ensure message format is valid"""
            
            await self.discord_controller.send_message(exception_message)
            self.error_handler.handle_exception(e, f"processing signal from {source}")
    
    async def _on_config_change(self, config) -> None:
        """Handle configuration changes"""
        try:
            self.error_handler.log_success("Configuration updated")
            
            # Update Discord channels if changed
            if self.discord_controller:
                # Update monitored channels in the controller
                self.discord_controller.monitored_channel_ids = []
                if hasattr(config, 'discord_channels') and config.discord_channels:
                    for ch in config.discord_channels:
                        try:
                            channel_id = int(ch)
                            self.discord_controller.monitored_channel_ids.append(channel_id)
                        except ValueError:
                            self.error_handler.log_warning(f"Invalid channel ID: {ch}")
                
        except Exception as e:
            self.error_handler.handle_exception(e, "handling config change")
    
    async def _send_startup_health_status(self) -> None:
        """Send detailed startup health status to Telegram"""
        try:
            config = self.config_manager.get_config()
            
            # Get exchange balance info
            try:
                balance = await self.exchange.get_account_balance()
                balance_text = f"💰 Balance: {balance['free_usdt']:.2f} USDT (Total: {balance['total_usdt']:.2f})"
            except:
                balance_text = "💰 Balance: Unable to fetch"
            
            # Get Discord connection status
            if self.discord_controller and not self.discord_controller.is_closed():
                discord_text = f"✅ Discord: Connected as {self.discord_controller.user} ({len(self.discord_controller.guilds)} servers)"
                channels_text = f"📺 Monitoring: {', '.join(map(str, self.discord_controller.monitored_channel_ids))}"
            else:
                discord_text = "❌ Discord: Disconnected"
                channels_text = "📺 Monitoring: None"
            
            # Get current positions
            try:
                positions = await self.exchange.get_open_positions()
                positions_text = f"📊 Active Positions: {len(positions)}"
                if positions:
                    pos_details = []
                    for symbol, pos in list(positions.items())[:3]:  # Show first 3
                        pnl = pos.get('pnl', 0)
                        pos_details.append(f"  • {symbol}: {pos['side']} (PnL: {pnl:+.2f})")
                    positions_text += "\n" + "\n".join(pos_details)
                    if len(positions) > 3:
                        positions_text += f"\n  ... and {len(positions) - 3} more"
            except:
                positions_text = "📊 Active Positions: Unable to fetch"
            
            # Get performance summary
            perf_summary = self.performance_monitor.get_performance_summary()
            
            startup_message = f"""🚀 Trading Bot Started Successfully!

⚙️ Configuration:
  • Mode: {config.mode.upper()}
  • Trading: {'✅ Enabled' if config.is_trading_enabled else '🛑 Disabled'}
  • Leverage: {config.leverage if config.leverage > 0 else 'From Signal'}
  • Futures Size: ${config.futures_position_size}
  • Spot Size: ${config.spot_position_size}
  • Max Futures: {config.max_futures_trade}
  • Max Spot: {config.max_spot_trade}
  • Daily Loss Limit: ${config.max_daily_loss}

🔗 Connections:
{discord_text}
{channels_text}
✅ Exchange: Connected ({config.mode} mode)
✅ Discord: Connected
✅ Signal Parser: Ready (Gemini 1.5 Flash)

{balance_text}

{positions_text}

⚡ Performance:
  • CPU: {perf_summary['system_health'].get('cpu_percent', 'N/A')}%
  • Memory: {perf_summary['system_health'].get('memory_percent', 'N/A')}% ({perf_summary['system_health'].get('memory_mb', 'N/A')} MB)
  • Initialization Time: {perf_summary['uptime_hours']:.2f}h

🕒 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            await self.discord_controller.send_message(startup_message)
            
        except Exception as e:
            self.error_handler.handle_exception(e, "sending startup health status")
    
    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.error_handler.log_info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self.shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def run(self) -> None:
        """Run the trading bot"""
        try:
            # Discord controller is already started in initialize()
            
            # Send detailed startup notification
            await self._send_startup_health_status()
            
            self.error_handler.log_success("🔄 Trading Bot is running...")
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
        except Exception as e:
            self.error_handler.handle_exception(e, "running bot")
            raise
    
    async def shutdown(self) -> None:
        """Gracefully shutdown all components"""
        try:
            self.error_handler.log_info("🛑 Shutting down Trading Bot...")
            
            # Signal shutdown
            self._shutdown_event.set()
            
            # Send shutdown notification
            if self.discord_controller:
                await self.discord_controller.send_message("🛑 Trading bot shutting down...")
            
            # Shutdown components in reverse order
            shutdown_tasks = []
            
            if self.discord_controller:
                shutdown_tasks.append(self.discord_controller.shutdown())
            
            if self.trade_tracker:
                shutdown_tasks.append(self.trade_tracker.shutdown())
            
            if self.trade_manager:
                shutdown_tasks.append(self.trade_manager.shutdown())
            
            if self.signal_parser:
                shutdown_tasks.append(self.signal_parser.shutdown())
            
            if self.exchange:
                shutdown_tasks.append(self.exchange.shutdown())
            
            if self.config_manager:
                shutdown_tasks.append(self.config_manager.shutdown())
            
            # Execute all shutdowns in parallel
            if shutdown_tasks:
                await asyncio.gather(*shutdown_tasks, return_exceptions=True)
            
            self.error_handler.log_success("✅ Trading Bot shutdown complete")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "bot shutdown")


async def main():
    """Main entry point"""
    bot = TradingBot()
    
    try:
        await bot.initialize()
        await bot.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    try:
        # Load environment variables from .env file
        load_dotenv()
        
        # Check Python version
        if sys.version_info < (3, 11):
            print("❌ Python 3.11+ required")
            sys.exit(1)
        
        # Run the bot
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        sys.exit(1)