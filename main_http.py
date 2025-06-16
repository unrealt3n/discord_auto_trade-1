"""
Main HTTP - Orchestrates all modules with HTTP-based components compatible with Termux
Coordinates Discord HTTP client, signal parser, trade manager, and other components
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
from exchange_connector_http import ExchangeConnectorHTTP
from signal_parser_http import SignalParserHTTP as SignalParser, TradeSignal
from trade_manager import TradeManager
from trade_tracker import TradeTracker
from discord_controller_http import DiscordControllerHTTP


class TradingBotHTTP:
    """HTTP-based trading bot compatible with Termux"""
    
    def __init__(self):
        self.error_handler = get_error_handler()
        self.performance_monitor = get_performance_monitor()
        self.config_manager: Optional[ConfigManager] = None
        self.exchange: Optional[ExchangeConnectorHTTP] = None
        self.signal_parser: Optional[SignalParser] = None
        self.trade_manager: Optional[TradeManager] = None
        self.trade_tracker: Optional[TradeTracker] = None
        self.discord: Optional[DiscordControllerHTTP] = None
        
        self._shutdown_event = asyncio.Event()
        self._running = False
        
    async def initialize(self) -> None:
        """Initialize all bot components"""
        try:
            print("ℹ️ 🤖 Initializing Trading Bot...")
            
            # Initialize performance monitor
            await self.performance_monitor.initialize()
            self.error_handler.log_success("Performance Monitor initialized")
            
            # Initialize config manager
            self.config_manager = ConfigManager()
            config = self.config_manager.get_config()
            
            # Initialize exchange connector
            self.exchange = ExchangeConnectorHTTP(config)
            await self.exchange.initialize()
            
            # Initialize signal parser
            self.signal_parser = SignalParser(config)
            
            # Initialize trade manager
            self.trade_manager = TradeManager(config, self.exchange)
            await self.trade_manager.initialize()
            
            # Initialize trade tracker
            self.trade_tracker = TradeTracker(config, self.exchange)
            await self.trade_tracker.initialize()
            
            # Initialize Discord controller
            self.discord = DiscordControllerHTTP(config)
            await self.discord.initialize()
            
            # Set up callbacks
            await self._setup_callbacks()
            
            print("✅ All components initialized successfully!")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "bot initialization")
            raise
    
    async def _setup_callbacks(self) -> None:
        """Setup callbacks between components"""
        try:
            # Set up Discord callbacks
            self.discord.set_cancel_all_callback(self._handle_cancel_all)
            self.discord.set_get_positions_callback(self._handle_get_positions)
            self.discord.set_get_stats_callback(self._handle_get_stats)
            self.discord.set_signal_callback(self._handle_signal)
            self.error_handler.log_success("Callbacks configured")
            
            # Start signal queue processor
            asyncio.create_task(self._process_signal_queue())
            self.error_handler.log_info("Signal queue processor started")
            
            # Start position monitoring
            current_positions = await self.exchange.get_positions()
            for pos in current_positions:
                if abs(pos['size']) > 0:
                    print(f"⚠️ Detected untracked position: {pos['symbol']} (ignoring - might be from another bot)")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "setting up callbacks")
            raise
    
    async def _handle_cancel_all(self) -> int:
        """Handle cancel all orders request"""
        try:
            count = await self.exchange.cancel_all_orders()
            self.error_handler.log_success(f"Cancelled {count} orders")
            return count
        except Exception as e:
            self.error_handler.handle_exception(e, "cancel all orders")
            return 0
    
    async def _handle_get_positions(self) -> str:
        """Handle get positions request"""
        try:
            return await self.exchange.get_positions_summary()
        except Exception as e:
            self.error_handler.handle_exception(e, "get positions")
            return "❌ Error getting positions"
    
    async def _handle_get_stats(self) -> dict:
        """Handle get stats request"""
        try:
            if self.trade_tracker:
                return await self.trade_tracker.get_statistics()
            return {"error": "Trade tracker not available"}
        except Exception as e:
            self.error_handler.handle_exception(e, "get stats")
            return {"error": str(e)}
    
    async def _handle_signal(self, content: str, images: list, source: str) -> None:
        """Handle incoming signal from Discord"""
        try:
            print(f"📡 Processing signal from {source}")
            print(f"📄 Content length: {len(content)} chars")
            print(f"🖼️ Images: {len(images)}")
            
            # Parse the signal
            signal_data = await self.signal_parser.parse_signal(content, images)
            
            if signal_data:
                print(f"✅ Signal parsed successfully: {signal_data.symbol} {signal_data.action}")
                
                # Send notification to Discord
                if self.discord:
                    signal_text = self._format_signal_for_notification(signal_data)
                    await self.discord.send_signal_notification(signal_text, content)
                
                # Add to queue for processing
                await self._add_signal_to_queue(signal_data, source)
            else:
                print("❌ Failed to parse signal")
                
        except Exception as e:
            self.error_handler.handle_exception(e, f"handling signal from {source}")
    
    def _format_signal_for_notification(self, signal: TradeSignal) -> str:
        """Format signal for Discord notification"""
        try:
            signal_text = f"""🎯 **{signal.action.upper()} Signal Detected**
            
📊 **Symbol:** {signal.symbol}
🎯 **Action:** {signal.action.upper()}
💰 **Entry:** ${signal.entry_price:.4f}
🛑 **Stop Loss:** ${signal.stop_loss:.4f} ({signal.stop_loss_percentage:.1f}%)
🎉 **Take Profit:** ${signal.take_profit:.4f} ({signal.take_profit_percentage:.1f}%)
⚡ **Leverage:** {signal.leverage}x
📈 **Type:** {signal.trade_type.upper()}
🔍 **Source:** {signal.source}"""
            
            if signal.confidence_score:
                signal_text += f"\\n🎯 **Confidence:** {signal.confidence_score:.1f}%"
            
            return signal_text
            
        except Exception as e:
            self.error_handler.handle_exception(e, "formatting signal notification")
            return f"Signal: {signal.symbol} {signal.action}"
    
    async def _add_signal_to_queue(self, signal: TradeSignal, source: str) -> None:
        """Add signal to processing queue"""
        try:
            if not hasattr(self, '_signal_queue'):
                self._signal_queue = asyncio.Queue()
            
            await self._signal_queue.put((signal, source, datetime.now()))
            print(f"📥 Signal added to queue: {signal.symbol}")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "adding signal to queue")
    
    async def _process_signal_queue(self) -> None:
        """Process signals from the queue"""
        if not hasattr(self, '_signal_queue'):
            self._signal_queue = asyncio.Queue()
        
        print("🔄 Signal queue processor started")
        
        while self._running:
            try:
                # Get signal from queue with timeout
                try:
                    signal, source, timestamp = await asyncio.wait_for(
                        self._signal_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Check if signal is too old (more than 5 minutes)
                age = (datetime.now() - timestamp).total_seconds()
                if age > 300:  # 5 minutes
                    print(f"⚠️ Discarding old signal: {signal.symbol} (age: {age:.1f}s)")
                    continue
                
                # Process the signal
                await self._execute_signal(signal, source)
                
            except Exception as e:
                self.error_handler.handle_exception(e, "processing signal queue")
                await asyncio.sleep(1)
    
    async def _execute_signal(self, signal: TradeSignal, source: str) -> None:
        """Execute a trading signal"""
        try:
            config = self.config_manager.get_config()
            
            # Check if trading is enabled
            if not config.is_trading_enabled:
                print(f"⚠️ Trading disabled - ignoring signal: {signal.symbol}")
                if self.discord:
                    await self.discord.send_message(
                        f"⚠️ **Trading Disabled**\\n\\n"
                        f"Received signal for {signal.symbol} but trading is disabled.\\n"
                        f"Use `!start` to enable trading."
                    )
                return
            
            print(f"🎯 Executing signal: {signal.symbol} {signal.action}")
            
            # Execute through trade manager
            if self.trade_manager:
                result = await self.trade_manager.execute_signal(signal)
                
                if result.get('success'):
                    print(f"✅ Signal executed successfully: {signal.symbol}")
                    if self.discord:
                        await self.discord.send_message(
                            f"✅ **Trade Executed**\\n\\n"
                            f"Signal: {signal.symbol} {signal.action.upper()}\\n"
                            f"Status: {result.get('message', 'Success')}"
                        )
                else:
                    print(f"❌ Signal execution failed: {result.get('message', 'Unknown error')}")
                    if self.discord:
                        await self.discord.send_message(
                            f"❌ **Trade Failed**\\n\\n"
                            f"Signal: {signal.symbol} {signal.action.upper()}\\n"
                            f"Error: {result.get('message', 'Unknown error')}"
                        )
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"executing signal {signal.symbol}")
    
    async def run(self) -> None:
        """Run the trading bot"""
        try:
            self._running = True
            
            # Setup signal handlers for graceful shutdown
            def signal_handler(signum, frame):
                print(f"\\n🛑 Received signal {signum}, initiating shutdown...")
                asyncio.create_task(self.shutdown())
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            print("🚀 Trading Bot started successfully!")
            print("📡 Monitoring Discord channels for signals...")
            print("💬 Send DM commands to the bot for control")
            print("🛑 Press Ctrl+C to stop")
            
            # Wait for shutdown event
            await self._shutdown_event.wait()
            
        except Exception as e:
            self.error_handler.handle_exception(e, "running bot")
            raise
    
    async def shutdown(self) -> None:
        """Shutdown the trading bot gracefully"""
        try:
            print("\\n🛑 Shutting down Trading Bot...")
            self._running = False
            
            # Shutdown components in reverse order
            if self.discord:
                await self.discord.shutdown()
            
            if self.trade_tracker:
                await self.trade_tracker.shutdown()
            
            if self.trade_manager:
                await self.trade_manager.shutdown()
            
            if self.exchange:
                await self.exchange.shutdown()
            
            if self.performance_monitor:
                await self.performance_monitor.shutdown()
            
            print("✅ Trading Bot shutdown complete")
            self._shutdown_event.set()
            
        except Exception as e:
            self.error_handler.handle_exception(e, "shutting down bot")


async def main():
    """Main entry point"""
    try:
        # Load environment variables
        load_dotenv()
        
        # Create and initialize bot
        bot = TradingBotHTTP()
        await bot.initialize()
        
        # Run bot
        await bot.run()
        
    except KeyboardInterrupt:
        print("\\n🛑 Keyboard interrupt received")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await bot.shutdown()
        except:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Critical error: {e}")
        sys.exit(1)