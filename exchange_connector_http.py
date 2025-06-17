"""
Exchange Connector HTTP - Pure HTTP implementation compatible with Termux
Handles both testnet and live trading with startup reconciliation
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Any, Tuple, Callable
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
from config_manager import Config
from error_handler import get_error_handler
from exchange_http_client import ExchangeClient, ExchangeError


class ExchangeConnectorHTTP:
    """HTTP-based exchange connector compatible with Termux"""
    
    def __init__(self, config: Config):
        self.config = config
        self.error_handler = get_error_handler()
        self.exchange: Optional[ExchangeClient] = None
        self._positions_cache: Dict[str, Dict] = {}
        self._last_cache_update = 0
        self._lock = asyncio.Lock()
        self._time_offset = 0
        
    async def initialize(self) -> None:
        """Initialize exchange connection"""
        try:
            await self._setup_exchange()
            await self._test_connection()
            await self._reconcile_positions()
            self.error_handler.log_startup("Exchange Connector HTTP")
        except Exception as e:
            self.error_handler.handle_exception(e, "exchange initialization")
            raise
    
    async def shutdown(self) -> None:
        """Gracefully shutdown exchange connection"""
        if self.exchange:
            # HTTP client doesn't need explicit close
            self.error_handler.log_shutdown("Exchange Connector HTTP")
    
    async def _setup_exchange(self) -> None:
        """Setup exchange connection based on mode"""
        is_live = self.config.mode == "live"
        
        if is_live:
            api_key = os.getenv("BINANCE_API_KEY")
            api_secret = os.getenv("BINANCE_API_SECRET")
            testnet = False
            print("🔴 Exchange configured for LIVE mode")
        else:
            api_key = os.getenv("BINANCE_TESTNET_API_KEY")
            api_secret = os.getenv("BINANCE_TESTNET_API_SECRET")
            testnet = True
            print("🟡 Exchange configured for TESTNET mode")
        
        if not api_key or not api_secret:
            raise ValueError(f"Exchange API credentials not found for {self.config.mode} mode")
        
        # Initialize HTTP exchange client
        self.exchange = ExchangeClient("binance", api_key, api_secret, testnet)
    
    async def _test_connection(self) -> None:
        """Test exchange connection and sync time"""
        try:
            # Test connectivity
            if not self.exchange.test_connectivity():
                raise ExchangeError("Exchange connectivity test failed")
            
            print("✅ Exchange connection verified")
            
        except Exception as e:
            raise ExchangeError(f"Exchange connection test failed: {str(e)}")
    
    async def _reconcile_positions(self) -> None:
        """Reconcile positions on startup to detect existing trades"""
        try:
            print("🔄 Performing position reconciliation...")
            
            # Get current futures positions
            positions = self.exchange.get_futures_positions()
            
            discrepancies = []
            for position in positions:
                symbol = position['symbol']
                size = abs(position['size'])
                
                if size > 0.001:  # Ignore very small positions
                    # Check if we have this position tracked
                    if symbol not in self._positions_cache:
                        discrepancies.append({
                            'symbol': symbol,
                            'size': position['size'],
                            'side': position['side'],
                            'pnl': position['pnl']
                        })
            
            if discrepancies:
                print(f"⚠️ Position reconciliation found {len(discrepancies)} discrepancies")
                for disc in discrepancies:
                    print(f"⚠️ Found untracked position: {disc['symbol']}")
            else:
                print("✅ Position reconciliation complete - no discrepancies found")
            
        except Exception as e:
            self.error_handler.handle_exception(e, "position reconciliation")
            print("⚠️ Position reconciliation failed - continuing anyway")
    
    async def get_balance(self, asset: str = "USDT") -> float:
        """Get balance for specified asset"""
        try:
            balance_info = self.exchange.get_balance(asset)
            return balance_info.get('free', 0.0)
        except Exception as e:
            self.error_handler.handle_exception(e, f"getting {asset} balance")
            return 0.0
    
    async def get_futures_balance(self) -> float:
        """Get futures account balance"""
        try:
            account = self.exchange.get_futures_account()
            for asset in account.get('assets', []):
                if asset['asset'] == 'USDT':
                    return float(asset['walletBalance'])
            return 0.0
        except Exception as e:
            self.error_handler.handle_exception(e, "getting futures balance")
            return 0.0
    
    async def get_price(self, symbol: str) -> float:
        """Get current price for symbol"""
        try:
            ticker = self.exchange.get_ticker(symbol)
            return ticker['price']
        except Exception as e:
            self.error_handler.handle_exception(e, f"getting price for {symbol}")
            raise
    
    async def create_order(self, symbol: str, side: str, order_type: str, 
                          amount: float, price: float = None, 
                          futures: bool = False, leverage: int = None) -> Dict:
        """Create order on exchange"""
        try:
            # Set leverage if specified and futures
            if futures and leverage:
                try:
                    self.exchange.set_leverage(symbol, leverage)
                except Exception as e:
                    print(f"⚠️ Failed to set leverage {leverage} for {symbol}: {e}")
            
            order = self.exchange.create_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=amount,
                price=price,
                futures=futures
            )
            
            # Normalize order response
            normalized_order = {
                'id': order['orderId'],
                'symbol': symbol,
                'side': side.lower(),
                'type': order_type.lower(),
                'amount': amount,
                'price': price,
                'status': order['status'].lower(),
                'timestamp': order.get('transactTime', int(time.time() * 1000)),
                'futures': futures
            }
            
            return normalized_order
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"creating {side} order for {symbol}")
            raise
    
    async def cancel_order(self, order_id: str, symbol: str, futures: bool = False) -> bool:
        """Cancel order"""
        try:
            self.exchange.cancel_order(symbol, int(order_id), futures=futures)
            return True
        except Exception as e:
            self.error_handler.handle_exception(e, f"cancelling order {order_id}")
            return False
    
    async def cancel_all_orders(self, symbol: str = None) -> int:
        """Cancel all orders"""
        try:
            # Cancel futures orders
            futures_count = self.exchange.cancel_all_orders(symbol, futures=True)
            
            # Cancel spot orders
            spot_count = self.exchange.cancel_all_orders(symbol, futures=False)
            
            total_count = futures_count + spot_count
            print(f"✅ Cancelled {total_count} orders ({futures_count} futures, {spot_count} spot)")
            return total_count
            
        except Exception as e:
            self.error_handler.handle_exception(e, "cancelling all orders")
            return 0
    
    async def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """Get open orders"""
        try:
            orders = []
            
            # Get futures orders
            futures_orders = self.exchange.get_open_orders(symbol, futures=True)
            for order in futures_orders:
                order['futures'] = True
                orders.append(order)
            
            # Get spot orders
            spot_orders = self.exchange.get_open_orders(symbol, futures=False)
            for order in spot_orders:
                order['futures'] = False
                orders.append(order)
            
            return orders
            
        except Exception as e:
            self.error_handler.handle_exception(e, "getting open orders")
            return []
    
    async def get_positions(self) -> List[Dict]:
        """Get current positions"""
        try:
            positions = self.exchange.get_futures_positions()
            
            # Cache positions
            self._positions_cache = {pos['symbol']: pos for pos in positions}
            self._last_cache_update = time.time()
            
            return positions
            
        except Exception as e:
            self.error_handler.handle_exception(e, "getting positions")
            return []
    
    async def get_position(self, symbol: str) -> Optional[Dict]:
        """Get position for specific symbol"""
        try:
            # Check cache first
            if (symbol in self._positions_cache and 
                time.time() - self._last_cache_update < 30):  # 30 second cache
                return self._positions_cache[symbol]
            
            # Refresh positions
            positions = await self.get_positions()
            for pos in positions:
                if pos['symbol'] == symbol:
                    return pos
            
            return None
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"getting position for {symbol}")
            return None
    
    async def close_position(self, symbol: str, percentage: float = 100.0) -> Optional[Dict]:
        """Close position by percentage"""
        try:
            position = await self.get_position(symbol)
            if not position:
                return None
            
            size = abs(position['size'])
            if size == 0:
                return None
            
            # Calculate close size
            close_size = size * (percentage / 100.0)
            
            # Determine opposite side
            close_side = 'sell' if position['side'] == 'long' else 'buy'
            
            # Create market order to close
            order = await self.create_order(
                symbol=symbol,
                side=close_side,
                order_type='market',
                amount=close_size,
                futures=True
            )
            
            return order
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"closing position {symbol}")
            return None
    
    def format_symbol(self, symbol: str, futures: bool = False) -> str:
        """Format symbol for exchange"""
        # Remove common suffixes and standardize
        symbol = symbol.upper().replace("/", "").replace("-", "").replace("_", "")
        
        # Add USDT if not present
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        
        return symbol
    
    def normalize_symbol(self, symbol: str, is_futures: bool = True) -> str:
        """Convert symbol from BTCUSDT format to HTTP exchange format"""
        try:
            # For HTTP implementation, we keep it simple - just format the symbol
            formatted = self.format_symbol(symbol, is_futures)
            
            # Validate the symbol isn't malformed
            if formatted.endswith('USDT'):
                base = formatted[:-4]
                # Check if base currency is valid (at least 2 chars and not a suffix fragment)
                if len(base) < 2 or base in ['TU', 'US', 'DT']:
                    self.error_handler.log_warning(f"Invalid base currency '{base}' from symbol '{symbol}', using original")
                    return symbol
            
            return formatted
            
        except Exception as e:
            self.error_handler.log_warning(f"Failed to normalize symbol {symbol}: {e}")
            return symbol
    
    def calculate_quantity(self, symbol: str, price: float, position_size: float, 
                          leverage: int = 1) -> float:
        """Calculate quantity based on position size and leverage"""
        try:
            # Calculate base quantity
            notional = position_size * leverage
            quantity = notional / price
            
            # Round down to avoid precision issues
            # This is a simplified rounding - in production you'd get symbol info
            if quantity >= 1:
                quantity = float(Decimal(str(quantity)).quantize(Decimal('0.001'), rounding=ROUND_DOWN))
            else:
                quantity = float(Decimal(str(quantity)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))
            
            return quantity
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"calculating quantity for {symbol}")
            return 0.0
    
    async def get_positions_summary(self) -> str:
        """Get formatted positions summary"""
        try:
            positions = await self.get_positions()
            
            if not positions:
                return "No active positions"
            
            summary_lines = []
            total_pnl = 0.0
            
            for pos in positions:
                total_pnl += pos['pnl']
                pnl_emoji = "🟢" if pos['pnl'] >= 0 else "🔴"
                
                summary_lines.append(
                    f"{pnl_emoji} {pos['symbol']} {pos['side'].upper()}\n"
                    f"   Size: {pos['size']:.4f}\n"
                    f"   Entry: ${pos['entry_price']:.4f}\n"
                    f"   Mark: ${pos['mark_price']:.4f}\n"
                    f"   PnL: {pos['pnl']:+.2f} USDT ({pos['percentage']:+.2f}%)"
                )
            
            total_emoji = "🟢" if total_pnl >= 0 else "🔴"
            summary = f"{total_emoji} **Total PnL: {total_pnl:+.2f} USDT**\n\n" + "\n\n".join(summary_lines)
            
            return summary
            
        except Exception as e:
            self.error_handler.handle_exception(e, "getting positions summary")
            return "❌ Error getting positions"
    
    async def monitor_positions(self, callback: Callable = None) -> None:
        """Monitor positions for changes (simplified for HTTP client)"""
        print("ℹ️ Position monitoring active (polling mode)")
        
        last_positions = {}
        
        while True:
            try:
                current_positions = await self.get_positions()
                
                # Compare with last known positions
                for pos in current_positions:
                    symbol = pos['symbol']
                    current_pnl = pos['pnl']
                    
                    if symbol in last_positions:
                        last_pnl = last_positions[symbol]['pnl']
                        pnl_change = current_pnl - last_pnl
                        
                        # Significant change threshold
                        if abs(pnl_change) > 5.0 and callback:  # $5 change
                            try:
                                await callback({
                                    'type': 'position_update',
                                    'symbol': symbol,
                                    'pnl': current_pnl,
                                    'pnl_change': pnl_change
                                })
                            except Exception as e:
                                print(f"❌ Error in position monitor callback: {e}")
                
                # Update last positions
                last_positions = {pos['symbol']: pos for pos in current_positions}
                
                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.error_handler.handle_exception(e, "position monitoring")
                await asyncio.sleep(60)  # Wait longer on error