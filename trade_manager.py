"""
Trade Manager - Validates and executes trades with risk management
Handles trade validation, position sizing, and TP/SL order placement
"""

import asyncio
import json
import os
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from signal_parser import TradeSignal
from exchange_connector import ExchangeConnector
from config_manager import Config
from error_handler import get_error_handler


class TradeManager:
    def __init__(self, exchange: ExchangeConnector, config: Config):
        self.exchange = exchange
        self.config = config
        self.error_handler = get_error_handler()
        self.signal_queue = asyncio.Queue(maxsize=50)
        self._processing_task: Optional[asyncio.Task] = None
        
    async def initialize(self) -> None:
        """Initialize trade manager"""
        self._processing_task = asyncio.create_task(self._process_signal_queue())
        self.error_handler.log_startup("Trade Manager")
    
    async def shutdown(self) -> None:
        """Shutdown trade manager"""
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        self.error_handler.log_shutdown("Trade Manager")
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status for debugging"""
        return {
            'queue_size': self.signal_queue.qsize(),
            'queue_maxsize': self.signal_queue.maxsize,
            'processing_task_running': self._processing_task and not self._processing_task.done() if self._processing_task else False,
            'processing_task_cancelled': self._processing_task.cancelled() if self._processing_task else False,
            'processing_task_exception': str(self._processing_task.exception()) if self._processing_task and self._processing_task.done() and self._processing_task.exception() else None
        }
    
    async def queue_signal(self, signal: TradeSignal) -> bool:
        """Queue signal for processing"""
        try:
            if self.signal_queue.full():
                self.error_handler.log_warning("Signal queue is full, dropping oldest signal")
                try:
                    self.signal_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            
            await self.signal_queue.put(signal)
            queue_size = self.signal_queue.qsize()
            self.error_handler.log_info(f"Signal queued: {signal.symbol} (queue size now: {queue_size})")
            
            # Check if processing task is still running
            if self._processing_task and self._processing_task.done():
                self.error_handler.log_error("Signal processing task has stopped! Restarting...")
                self._processing_task = asyncio.create_task(self._process_signal_queue())
            
            return True
        except Exception as e:
            self.error_handler.handle_exception(e, "queuing signal")
            return False
    
    async def _process_signal_queue(self) -> None:
        """Process signals from queue"""
        self.error_handler.log_info("Signal queue processor started")
        while True:
            try:
                # Check if there are signals waiting
                queue_size = self.signal_queue.qsize()
                if queue_size > 0:
                    self.error_handler.log_info(f"Processing signal from queue (queue size: {queue_size})")
                
                signal = await asyncio.wait_for(self.signal_queue.get(), timeout=1.0)
                self.error_handler.log_info(f"Executing signal: {signal.symbol} {signal.direction}")
                
                await self._execute_signal(signal)
                self.signal_queue.task_done()
                
                self.error_handler.log_info(f"Signal execution completed for {signal.symbol}")
                
            except asyncio.TimeoutError:
                # No signals in queue, continue waiting
                continue
            except asyncio.CancelledError:
                self.error_handler.log_info("Signal queue processor cancelled")
                break
            except Exception as e:
                self.error_handler.handle_exception(e, "processing signal queue")
                await asyncio.sleep(1)
    
    async def _execute_signal(self, signal: TradeSignal) -> bool:
        """Execute trading signal"""
        try:
            start_time = datetime.now()
            self.error_handler.log_info(f"🚀 Starting execution of {signal.symbol} {signal.direction}")
            
            self.error_handler.log_info(f"📋 Validating signal for {signal.symbol}")
            if not await self._validate_signal(signal):
                self.error_handler.log_warning(f"❌ Signal validation failed for {signal.symbol}")
                return False
            
            self.error_handler.log_info(f"💰 Calculating position size for {signal.symbol}")
            position_size = await self._calculate_position_size(signal)
            if position_size <= 0:
                self.error_handler.log_error(f"Invalid position size for {signal.symbol}")
                return False
            
            self.error_handler.log_info(f"📈 Placing orders for {signal.symbol} (size: {position_size})")
            success = await self._place_trade_orders(signal, position_size)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            if execution_time > 3.0:
                self.error_handler.log_warning(
                    f"Slow signal execution: {execution_time:.2f}s (target: <3s)"
                )
            
            status = "✅ SUCCESS" if success else "❌ FAILED"
            self.error_handler.log_info(f"🎯 Signal execution {status} for {signal.symbol} in {execution_time:.2f}s")
            
            return success
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"executing signal {signal.symbol}")
            return False
    
    async def _validate_signal(self, signal: TradeSignal) -> bool:
        """Validate signal against risk management rules"""
        try:
            if not self.config.is_trading_enabled:
                self.error_handler.log_warning("Trading is disabled")
                return False
            
            if self.config.is_symbol_blacklisted(signal.symbol):
                self.error_handler.log_warning(f"Symbol {signal.symbol} is blacklisted")
                return False
            
            if signal.trade_type == "spot" and not self.exchange.is_spot_supported():
                self.error_handler.log_warning(
                    f"Spot trading not supported in {self.config.mode} mode, skipping {signal.symbol}"
                )
                return False
            
            if await self._has_duplicate_position(signal):
                self.error_handler.log_warning(
                    f"Duplicate position exists for {signal.symbol} {signal.direction}"
                )
                return False
            
            if not await self._check_position_limits(signal):
                return False
            
            if not await self._check_daily_loss_limit():
                return False
            
            if not await self._check_minimum_amount(signal):
                return False
            
            return True
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"validating signal {signal.symbol}")
            return False
    
    async def _has_duplicate_position(self, signal: TradeSignal) -> bool:
        """Check if duplicate position exists"""
        try:
            positions = await self.exchange.get_open_positions()
            for symbol, position in positions.items():
                if (symbol == signal.symbol and 
                    position['side'].lower() == signal.direction.lower()):
                    return True
            return False
        except Exception as e:
            self.error_handler.handle_exception(e, "checking duplicate positions")
            return True
    
    async def _check_position_limits(self, signal: TradeSignal) -> bool:
        """Check position count limits"""
        try:
            positions = await self.exchange.get_open_positions()
            
            if signal.trade_type == "futures":
                futures_count = sum(1 for pos in positions.values() 
                                   if pos.get('type', 'future') == 'future')
                if futures_count >= self.config.max_futures_trade:
                    self.error_handler.log_warning(
                        f"Max futures positions reached ({futures_count}/{self.config.max_futures_trade})"
                    )
                    return False
            
            elif signal.trade_type == "spot":
                spot_count = sum(1 for pos in positions.values() 
                                if pos.get('type', 'spot') == 'spot')
                if spot_count >= self.config.max_spot_trade:
                    self.error_handler.log_warning(
                        f"Max spot positions reached ({spot_count}/{self.config.max_spot_trade})"
                    )
                    return False
            
            return True
            
        except Exception as e:
            self.error_handler.handle_exception(e, "checking position limits")
            return False
    
    async def _check_daily_loss_limit(self) -> bool:
        """Check daily loss limit"""
        try:
            today = datetime.now().date()
            trades_file = "trades.json"
            
            if not os.path.exists(trades_file):
                return True
            
            with open(trades_file, 'r') as f:
                trades = json.load(f)
            
            daily_pnl = 0
            for trade in trades:
                trade_date = datetime.fromisoformat(trade['timestamp']).date()
                if trade_date == today and trade.get('pnl', 0) < 0:
                    daily_pnl += trade['pnl']
            
            if abs(daily_pnl) >= self.config.max_daily_loss:
                self.error_handler.log_error(
                    f"Daily loss limit reached: {daily_pnl:.2f} USDT"
                )
                return False
            
            return True
            
        except Exception as e:
            self.error_handler.handle_exception(e, "checking daily loss limit")
            return True
    
    async def _check_minimum_amount(self, signal: TradeSignal) -> bool:
        """Check if trade amount meets exchange minimum requirements using real Binance limits"""
        try:
            position_size = await self._calculate_position_size(signal)
            if position_size <= 0:
                return False
            
            # Use new validation method with real Binance limits
            validation = await self.exchange.validate_order_size(
                signal.symbol, position_size, signal.entry_price
            )
            
            # Log any warnings (like using default limits)
            for warning in validation.get('warnings', []):
                self.error_handler.log_warning(f"⚠️ {warning}")
            
            # Check if main order is valid
            if not validation['valid']:
                for error in validation['errors']:
                    self.error_handler.log_error(f"❌ {error}")
                return False
            
            # Check TP splitting with notional validation
            filtered_tps = self._get_filtered_take_profits(signal.take_profits)
            if filtered_tps:
                tp_size_per_order = position_size / len(filtered_tps)
                
                # Use first TP price for notional calculation (conservative estimate)
                tp_price = filtered_tps[0]
                tp_validation = await self.exchange.validate_order_size(
                    signal.symbol, tp_size_per_order, tp_price
                )
                
                if not tp_validation['valid']:
                    # Calculate how many TP orders we can actually place
                    min_notional = tp_validation['min_notional']
                    min_qty = tp_validation['min_qty']
                    
                    # Use the more restrictive limit
                    min_tp_amount = max(min_qty, min_notional / tp_price)
                    max_tp_orders = int(position_size / min_tp_amount)
                    
                    if max_tp_orders == 0:
                        self.error_handler.log_warning(
                            f"⚠️ Position too small for any TP orders, will skip TPs"
                        )
                    else:
                        self.error_handler.log_warning(
                            f"⚠️ TP orders will be reduced from {len(filtered_tps)} to {max_tp_orders} due to minimum notional/quantity constraints"
                        )
            
            return True
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"checking minimum amount for {signal.symbol}")
            return False
    
    async def _calculate_position_size(self, signal: TradeSignal) -> float:
        """Calculate position size based on signal type"""
        try:
            current_price = await self.exchange.get_current_price(signal.symbol)
            
            if signal.trade_type == "futures":
                usd_amount = self.config.futures_position_size
            else:
                usd_amount = self.config.spot_position_size
            
            position_size = self.exchange.calculate_position_size(
                signal.symbol, current_price, usd_amount, 
                signal.trade_type == "futures"
            )
            
            return position_size
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"calculating position size for {signal.symbol}")
            return 0
    
    async def _place_trade_orders(self, signal: TradeSignal, position_size: float) -> bool:
        """Place entry, TP, and SL orders"""
        try:
            leverage_to_use = self._get_leverage_for_signal(signal)
            
            if signal.trade_type == "futures" and leverage_to_use > 1:
                await self.exchange.set_leverage(signal.symbol, leverage_to_use)
            
            # Place all orders as a complete package when Gemini gives result
            self.error_handler.log_info(f"📤 Placing entry order for {signal.symbol}")
            entry_order = await self._place_entry_order(signal, position_size)
            if not entry_order:
                self.error_handler.log_error(f"❌ Entry order placement failed for {signal.symbol} - no order returned")
                return False
            
            self.error_handler.log_success(f"✅ Entry order placed successfully for {signal.symbol}: {entry_order.get('id', 'unknown_id')}")
            
            # Always place TP/SL orders immediately after entry order
            await self._place_tp_orders(signal, position_size)
            await self._place_sl_order(signal, position_size)
            
            # Save to positions.json for tracking (will be properly handled by position tracker)
            await self._save_position_to_file(signal, position_size, entry_order)
            
            self.error_handler.log_success(f"Complete trade setup placed for {signal.symbol}: Entry + TP/SL orders")
            
            return True
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"placing orders for {signal.symbol}")
            return False
    
    def _get_leverage_for_signal(self, signal: TradeSignal) -> int:
        """Get leverage to use for signal"""
        if self.config.leverage > 0:
            return self.config.leverage
        elif signal.leverage and signal.leverage > 0:
            return signal.leverage
        else:
            return 1
    
    async def _place_entry_order(self, signal: TradeSignal, position_size: float) -> Optional[Dict]:
        """Place entry limit order"""
        try:
            side = 'buy' if signal.direction == 'long' else 'sell'
            
            # Normalize symbol for exchange
            normalized_symbol = self.exchange.normalize_symbol(signal.symbol, signal.trade_type == "futures")
            
            self.error_handler.log_info(f"🔄 Attempting to place {side} order: {position_size} {normalized_symbol} @ {signal.entry_price}")
            
            order = await self.exchange.place_limit_order(
                normalized_symbol, side, position_size, signal.entry_price
            )
            
            if order and order.get('id'):
                self.error_handler.log_success(f"✅ Entry order placed on exchange: ID {order['id']}")
                return order
            else:
                self.error_handler.log_error(f"❌ Exchange returned invalid order response: {order}")
                return None
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"placing entry order for {signal.symbol}")
            return None
    
    async def _place_tp_orders(self, signal: TradeSignal, position_size: float) -> None:
        """Place take profit orders using real Binance validation"""
        try:
            filtered_tps = self._get_filtered_take_profits(signal.take_profits)
            if not filtered_tps:
                return
                
            close_side = 'sell' if signal.direction == 'long' else 'buy'
            
            # Normalize symbol for exchange
            normalized_symbol = self.exchange.normalize_symbol(signal.symbol, signal.trade_type == "futures")
            
            # Calculate TP size per order
            tp_size_per_order = position_size / len(filtered_tps)
            
            # Validate first TP order size using real Binance limits
            first_tp_price = filtered_tps[0]
            validation = await self.exchange.validate_order_size(
                signal.symbol, tp_size_per_order, first_tp_price
            )
            
            # If individual TP orders are too small, reduce the number
            if not validation['valid']:
                min_notional = validation['min_notional']
                min_qty = validation['min_qty']
                
                # Use the more restrictive limit
                min_tp_amount = max(min_qty, min_notional / first_tp_price)
                max_tp_orders = int(position_size / min_tp_amount)
                
                if max_tp_orders == 0:
                    self.error_handler.log_warning(
                        f"Position size {position_size} too small for any TP orders "
                        f"(need ≥{min_tp_amount:.6f} per order), skipping TPs"
                    )
                    return
                
                # Use only the first N TPs that we can afford
                original_count = len(filtered_tps)
                filtered_tps = filtered_tps[:max_tp_orders]
                tp_size_per_order = position_size / len(filtered_tps)
                
                self.error_handler.log_warning(
                    f"Reduced TP orders from {original_count} to {len(filtered_tps)} "
                    f"due to notional/quantity constraints (min: ${min_notional}, {min_qty})"
                )
            
            # Place the TP orders
            for i, tp_price in enumerate(filtered_tps):
                adjusted_tp = self.exchange.adjust_tp_price(tp_price, close_side)
                
                await self.exchange.place_take_profit_order(
                    normalized_symbol, close_side, tp_size_per_order, adjusted_tp
                )
                
                await asyncio.sleep(0.1)
                
        except Exception as e:
            self.error_handler.handle_exception(e, f"placing TP orders for {signal.symbol}")
    
    async def _place_sl_order(self, signal: TradeSignal, position_size: float) -> None:
        """Place stop loss order"""
        try:
            close_side = 'sell' if signal.direction == 'long' else 'buy'
            
            # Normalize symbol for exchange
            normalized_symbol = self.exchange.normalize_symbol(signal.symbol, signal.trade_type == "futures")
            
            await self.exchange.place_stop_loss_order(
                normalized_symbol, close_side, position_size, signal.stop_loss
            )
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"placing SL order for {signal.symbol}")
    
    def _get_filtered_take_profits(self, take_profits: List[float]) -> List[float]:
        """Get filtered take profits (1st, 3rd, 5th)"""
        filtered_tps = []
        indices = [0, 2, 4]  # 1st, 3rd, 5th (0-indexed)
        
        for i in indices:
            if i < len(take_profits):
                filtered_tps.append(take_profits[i])
        
        return filtered_tps
    
    async def _save_position_to_file(self, signal: TradeSignal, position_size: float, 
                                   entry_order: Dict) -> None:
        """Save position to positions.json"""
        try:
            positions_file = "positions.json"
            positions = {}
            
            if os.path.exists(positions_file):
                with open(positions_file, 'r') as f:
                    positions = json.load(f)
            
            position_data = {
                'symbol': signal.symbol,
                'direction': signal.direction,
                'trade_type': signal.trade_type,
                'entry_price': signal.entry_price,
                'stop_loss': signal.stop_loss,
                'take_profits': signal.take_profits,
                'position_size': position_size,
                'leverage': self._get_leverage_for_signal(signal),
                'entry_order_id': entry_order.get('id'),
                'timestamp': datetime.now().isoformat(),
                'source': signal.source,
                'status': 'open'
            }
            
            positions[signal.symbol] = position_data
            
            with open(positions_file, 'w') as f:
                json.dump(positions, f, indent=2)
                
        except Exception as e:
            self.error_handler.handle_exception(e, "saving position to file")
    
    async def cancel_all_orders(self) -> int:
        """Cancel all open orders"""
        try:
            return await self.exchange.cancel_all_orders()
        except Exception as e:
            self.error_handler.handle_exception(e, "cancelling all orders")
            return 0