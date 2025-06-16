"""
Trade Tracker - Monitors positions and tracks PnL, TP/SL hits
Updates positions.json and trades.json, reports events via Telegram
"""

import asyncio
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
# Use HTTP fallback for Termux compatibility
try:
    from exchange_connector import ExchangeConnector
except ImportError:
    from exchange_connector_http import ExchangeConnectorHTTP as ExchangeConnector
from config_manager import Config
from error_handler import get_error_handler


class TradeTracker:
    def __init__(self, exchange: ExchangeConnector, config: Config):
        self.exchange = exchange
        self.config = config
        self.error_handler = get_error_handler()
        self.telegram_callback: Optional[callable] = None
        self._tracking_task: Optional[asyncio.Task] = None
        self._last_positions: Dict[str, Dict] = {}
        self._untracked_positions_warned: set = set()  # Track warned positions
        
    async def initialize(self) -> None:
        """Initialize trade tracker"""
        self._tracking_task = asyncio.create_task(self._track_positions())
        self.error_handler.log_startup("Trade Tracker")
    
    async def shutdown(self) -> None:
        """Shutdown trade tracker"""
        if self._tracking_task:
            self._tracking_task.cancel()
            try:
                await self._tracking_task
            except asyncio.CancelledError:
                pass
        self.error_handler.log_shutdown("Trade Tracker")
    
    def set_telegram_callback(self, callback: callable) -> None:
        """Set callback for Telegram notifications"""
        self.telegram_callback = callback
    
    async def _track_positions(self) -> None:
        """Main position tracking loop"""
        while True:
            try:
                await self._update_positions()
                await asyncio.sleep(10)  # Check every 10 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_handler.handle_exception(e, "tracking positions")
                await asyncio.sleep(30)  # Wait longer on error
    
    async def _update_positions(self) -> None:
        """Update position statuses and detect changes"""
        try:
            current_positions = await self.exchange.get_open_positions()
            local_positions = self._load_local_positions()
            
            for symbol, local_pos in local_positions.items():
                if local_pos.get('status') != 'open':
                    continue
                
                if symbol in current_positions:
                    await self._update_existing_position(symbol, current_positions[symbol], local_pos)
                else:
                    # Check if this is actually a closed position or just a pending entry
                    await self._handle_missing_position(symbol, local_pos)
            
            await self._detect_new_positions(current_positions, local_positions)
            self._last_positions = current_positions.copy()
            
        except Exception as e:
            self.error_handler.handle_exception(e, "updating positions")
    
    async def _update_existing_position(self, symbol: str, exchange_pos: Dict, local_pos: Dict) -> None:
        """Update existing position with current data"""
        try:
            current_pnl = float(exchange_pos.get('pnl', 0))
            entry_price = float(local_pos.get('entry_price', 0))
            current_price = float(exchange_pos.get('mark_price', 0))
            
            # Mark position as confirmed opened
            if not local_pos.get('position_opened_confirmed'):
                await self._mark_position_confirmed(symbol)
                self.error_handler.log_success(f"Position {symbol} confirmed opened on exchange")
            
            pnl_change = 0
            if symbol in self._last_positions:
                last_pnl = float(self._last_positions[symbol].get('pnl', 0))
                pnl_change = current_pnl - last_pnl
            
            significant_change = abs(pnl_change) > 5.0
            
            if significant_change:
                change_text = f"{pnl_change:+.2f}" if pnl_change != 0 else ""
                self.error_handler.log_position_update(
                    symbol, f"PnL: {current_pnl:+.2f} USDT ({change_text})"
                )
            
            await self._check_take_profit_hits(symbol, local_pos, current_price)
            await self._check_stop_loss_hit(symbol, local_pos, current_price)
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"updating position {symbol}")
    
    async def _handle_missing_position(self, symbol: str, local_pos: Dict) -> None:
        """Handle when position exists locally but not on exchange"""
        try:
            # Check if this position was ever actually opened and confirmed
            if not local_pos.get('position_opened_confirmed'):
                # Position was never confirmed as opened - this was just a pending entry order
                self.error_handler.log_info(f"Position {symbol} appears to be pending entry order, not closed")
                
                # Clean up the pending position record without creating trade history
                await self._cleanup_pending_position(symbol)
                return
            
            # If we get here, position was actually opened and then closed
            await self._handle_closed_position(symbol, local_pos)
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"handling missing position {symbol}")
    
    async def _mark_position_confirmed(self, symbol: str) -> None:
        """Mark position as confirmed opened"""
        try:
            positions = self._load_local_positions()
            if symbol in positions:
                positions[symbol]['position_opened_confirmed'] = True
                
                positions_file = "positions.json"
                with open(positions_file, 'w') as f:
                    json.dump(positions, f, indent=2)
                    
        except Exception as e:
            self.error_handler.handle_exception(e, f"marking position confirmed {symbol}")
    
    async def _cleanup_pending_position(self, symbol: str) -> None:
        """Clean up pending position that was never opened (cancelled entry order)"""
        try:
            positions = self._load_local_positions()
            
            if symbol in positions:
                self.error_handler.log_info(f"Cleaning up pending position record for {symbol} (entry order was cancelled)")
                
                # Simply remove the position without creating trade history or calculating PnL
                del positions[symbol]
                self._save_local_positions(positions)
                
        except Exception as e:
            self.error_handler.handle_exception(e, f"cleaning up pending position {symbol}")
    
    async def _handle_closed_position(self, symbol: str, local_pos: Dict) -> None:
        """Handle position that was closed"""
        try:
            final_pnl = await self._calculate_final_pnl(symbol, local_pos)
            
            await self._close_position_in_records(symbol, final_pnl)
            
            close_reason = self._determine_close_reason(local_pos, final_pnl)
            
            self.error_handler.log_trade_event(
                "POSITION_CLOSED", symbol,
                f"{close_reason} | Final PnL: {final_pnl:+.2f} USDT",
                final_pnl >= 0
            )
            
            if self.telegram_callback:
                entry_price = float(local_pos.get('entry_price', 0))
                direction = local_pos.get('direction', '').upper()
                hold_time = (datetime.now() - datetime.fromisoformat(local_pos['timestamp'])).total_seconds() / 3600
                
                pnl_emoji = "🟢" if final_pnl >= 0 else "🔴"
                
                message = f"""{pnl_emoji} POSITION CLOSED

📊 Trade Summary:
  • Symbol: {symbol}
  • Direction: {direction}
  • Entry: {entry_price}
  • Close Reason: {close_reason}
  • Hold Time: {hold_time:.2f}h
  • Final PnL: {final_pnl:+.2f} USDT
  • ROI: {(final_pnl / local_pos.get('position_size', 1) * 100):+.2f}%
  
📈 Performance:
  • Source: {local_pos.get('source', 'Unknown')}
  • Trade Type: {local_pos.get('trade_type', 'Unknown').upper()}"""
                
                await self._send_telegram_notification(message)
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"handling closed position {symbol}")
    
    async def _detect_new_positions(self, current_positions: Dict, local_positions: Dict) -> None:
        """Detect newly opened positions not in local records"""
        for symbol, exchange_pos in current_positions.items():
            if symbol not in local_positions and symbol not in self._untracked_positions_warned:
                self.error_handler.log_warning(f"Detected untracked position: {symbol} (ignoring - might be from another bot)")
                self._untracked_positions_warned.add(symbol)
    
    async def _check_take_profit_hits(self, symbol: str, local_pos: Dict, current_price: float) -> None:
        """Check if any take profit levels were hit"""
        try:
            take_profits = local_pos.get('take_profits', [])
            direction = local_pos.get('direction', '').lower()
            
            for i, tp_price in enumerate(take_profits):
                tp_key = f'tp_{i+1}_hit'
                if local_pos.get(tp_key):
                    continue
                
                tp_hit = False
                if direction == 'long' and current_price >= tp_price:
                    tp_hit = True
                elif direction == 'short' and current_price <= tp_price:
                    tp_hit = True
                
                if tp_hit:
                    await self._record_take_profit_hit(symbol, i+1, tp_price)
                    
                    self.error_handler.log_trade_event(
                        f"TP{i+1}_HIT", symbol,
                        f"Price: {current_price} | Target: {tp_price}"
                    )
                    
                    if self.telegram_callback:
                        direction = local_pos.get('direction', '').upper()
                        entry_price = float(local_pos.get('entry_price', 0))
                        profit_pct = abs(current_price - entry_price) / entry_price * 100
                        
                        message = f"""🎯 TAKE PROFIT HIT

📊 TP Details:
  • Symbol: {symbol}
  • Direction: {direction}
  • TP Level: TP{i+1}
  • Target Price: {tp_price}
  • Hit Price: {current_price}
  • Entry Price: {entry_price}
  • Profit: {profit_pct:.2f}%"""
                        await self._send_telegram_notification(message)
                        
        except Exception as e:
            self.error_handler.handle_exception(e, f"checking TP hits for {symbol}")
    
    async def _check_stop_loss_hit(self, symbol: str, local_pos: Dict, current_price: float) -> None:
        """Check if stop loss was hit"""
        try:
            if local_pos.get('sl_hit'):
                return
            
            stop_loss = float(local_pos.get('stop_loss', 0))
            direction = local_pos.get('direction', '').lower()
            
            sl_hit = False
            if direction == 'long' and current_price <= stop_loss:
                sl_hit = True
            elif direction == 'short' and current_price >= stop_loss:
                sl_hit = True
            
            if sl_hit:
                await self._record_stop_loss_hit(symbol, stop_loss)
                
                self.error_handler.log_trade_event(
                    "STOP_LOSS_HIT", symbol,
                    f"Price: {current_price} | SL: {stop_loss}",
                    is_success=False
                )
                
                if self.telegram_callback:
                    direction = local_pos.get('direction', '').upper()
                    entry_price = float(local_pos.get('entry_price', 0))
                    loss_pct = abs(current_price - entry_price) / entry_price * 100
                    
                    message = f"""🛑 STOP LOSS HIT

📊 SL Details:
  • Symbol: {symbol}
  • Direction: {direction}
  • SL Price: {stop_loss}
  • Hit Price: {current_price}
  • Entry Price: {entry_price}
  • Loss: -{loss_pct:.2f}%"""
                    await self._send_telegram_notification(message)
                    
        except Exception as e:
            self.error_handler.handle_exception(e, f"checking SL hit for {symbol}")
    
    async def _record_take_profit_hit(self, symbol: str, tp_number: int, tp_price: float) -> None:
        """Record take profit hit in local position"""
        try:
            positions = self._load_local_positions()
            if symbol in positions:
                positions[symbol][f'tp_{tp_number}_hit'] = True
                positions[symbol][f'tp_{tp_number}_hit_time'] = datetime.now().isoformat()
                positions[symbol][f'tp_{tp_number}_hit_price'] = tp_price
                self._save_local_positions(positions)
        except Exception as e:
            self.error_handler.handle_exception(e, f"recording TP hit for {symbol}")
    
    async def _record_stop_loss_hit(self, symbol: str, sl_price: float) -> None:
        """Record stop loss hit in local position"""
        try:
            positions = self._load_local_positions()
            if symbol in positions:
                positions[symbol]['sl_hit'] = True
                positions[symbol]['sl_hit_time'] = datetime.now().isoformat()
                positions[symbol]['sl_hit_price'] = sl_price
                self._save_local_positions(positions)
        except Exception as e:
            self.error_handler.handle_exception(e, f"recording SL hit for {symbol}")
    
    async def _calculate_final_pnl(self, symbol: str, local_pos: Dict) -> float:
        """Calculate final PnL for closed position"""
        try:
            # Safety check: don't calculate PnL for positions that were never confirmed opened
            if not local_pos.get('position_opened_confirmed'):
                self.error_handler.log_warning(f"Not calculating PnL for {symbol} - position was never confirmed opened")
                return 0.0
            
            entry_price = float(local_pos.get('entry_price', 0))
            position_size = float(local_pos.get('position_size', 0))
            direction = local_pos.get('direction', '').lower()
            
            current_price = await self.exchange.get_current_price(symbol)
            
            if direction == 'long':
                pnl = (current_price - entry_price) * position_size
            else:
                pnl = (entry_price - current_price) * position_size
            
            return round(pnl, 2)
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"calculating final PnL for {symbol}")
            return 0.0
    
    def _determine_close_reason(self, local_pos: Dict, final_pnl: float) -> str:
        """Determine why position was closed"""
        if local_pos.get('sl_hit'):
            return "Stop Loss"
        
        tp_hits = sum(1 for i in range(1, 6) if local_pos.get(f'tp_{i}_hit'))
        if tp_hits > 0:
            return f"Take Profit (TP{tp_hits})"
        
        if final_pnl >= 0:
            return "Manual Close (Profit)"
        else:
            return "Manual Close (Loss)"
    
    async def _close_position_in_records(self, symbol: str, final_pnl: float) -> None:
        """Close position in local records and save to trade history"""
        try:
            positions = self._load_local_positions()
            
            if symbol not in positions:
                return
            
            position = positions[symbol]
            position['status'] = 'closed'
            position['close_time'] = datetime.now().isoformat()
            position['final_pnl'] = final_pnl
            
            await self._save_to_trade_history(position)
            
            del positions[symbol]
            self._save_local_positions(positions)
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"closing position records for {symbol}")
    
    async def _save_to_trade_history(self, position: Dict) -> None:
        """Save completed trade to trade history"""
        try:
            trades_file = "trades.json"
            trades = []
            
            if os.path.exists(trades_file):
                with open(trades_file, 'r') as f:
                    trades = json.load(f)
            
            start_time = datetime.fromisoformat(position['timestamp'])
            end_time = datetime.fromisoformat(position['close_time'])
            hold_time = (end_time - start_time).total_seconds() / 3600  # hours
            
            trade_record = {
                'symbol': position['symbol'],
                'direction': position['direction'],
                'trade_type': position['trade_type'],
                'entry_price': position['entry_price'],
                'position_size': position['position_size'],
                'leverage': position.get('leverage', 1),
                'pnl': position['final_pnl'],
                'hold_time_hours': round(hold_time, 2),
                'source': position.get('source', 'unknown'),
                'timestamp': position['timestamp'],
                'close_time': position['close_time'],
                'tp_hits': [position.get(f'tp_{i}_hit', False) for i in range(1, 6)],
                'sl_hit': position.get('sl_hit', False)
            }
            
            trades.append(trade_record)
            
            with open(trades_file, 'w') as f:
                json.dump(trades, f, indent=2)
                
        except Exception as e:
            self.error_handler.handle_exception(e, "saving trade history")
    
    def _load_local_positions(self) -> Dict[str, Dict]:
        """Load positions from local file"""
        try:
            positions_file = "positions.json"
            if os.path.exists(positions_file):
                with open(positions_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            self.error_handler.handle_exception(e, "loading local positions")
            return {}
    
    def _save_local_positions(self, positions: Dict[str, Dict]) -> None:
        """Save positions to local file"""
        try:
            with open("positions.json", 'w') as f:
                json.dump(positions, f, indent=2)
        except Exception as e:
            self.error_handler.handle_exception(e, "saving local positions")
    
    async def _send_telegram_notification(self, message: str) -> None:
        """Send notification to Telegram"""
        if self.telegram_callback:
            try:
                if asyncio.iscoroutinefunction(self.telegram_callback):
                    await self.telegram_callback(message)
                else:
                    self.telegram_callback(message)
            except Exception as e:
                self.error_handler.handle_exception(e, "sending Telegram notification")
    
    async def get_active_positions_summary(self) -> str:
        """Get summary of active positions"""
        try:
            positions = await self.exchange.get_open_positions()
            
            if not positions:
                return "No active positions"
            
            summary = f"Active Positions ({len(positions)}):\n\n"
            
            for symbol, position in positions.items():
                pnl = float(position.get('pnl', 0))
                pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                
                summary += (f"{pnl_emoji} {symbol}\n"
                           f"Side: {position['side'].upper()}\n"
                           f"Size: {position['size']}\n"
                           f"Entry: {position['entry_price']}\n"
                           f"Mark: {position['mark_price']}\n"
                           f"PnL: {pnl:+.2f} USDT\n\n")
            
            return summary.strip()
            
        except Exception as e:
            self.error_handler.handle_exception(e, "getting positions summary")
            return "Error getting positions summary"
    
    async def get_trade_statistics(self) -> Dict[str, Any]:
        """Get trading statistics"""
        try:
            trades_file = "trades.json"
            if not os.path.exists(trades_file):
                return {"total_trades": 0, "total_pnl": 0, "win_rate": 0}
            
            with open(trades_file, 'r') as f:
                trades = json.load(f)
            
            if not trades:
                return {"total_trades": 0, "total_pnl": 0, "win_rate": 0}
            
            total_trades = len(trades)
            total_pnl = sum(trade['pnl'] for trade in trades)
            winning_trades = sum(1 for trade in trades if trade['pnl'] > 0)
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            avg_hold_time = sum(trade['hold_time_hours'] for trade in trades) / total_trades
            
            return {
                "total_trades": total_trades,
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(win_rate, 1),
                "avg_hold_time": round(avg_hold_time, 2)
            }
            
        except Exception as e:
            self.error_handler.handle_exception(e, "getting trade statistics")
            return {"total_trades": 0, "total_pnl": 0, "win_rate": 0}