"""
Exchange Connector - Binance integration with ccxt and WebSocket support
Handles both testnet and live trading with startup reconciliation
"""

import ccxt.async_support as ccxt
import asyncio
import json
import os
import time
import aiohttp
from typing import Dict, List, Optional, Any, Tuple, Callable
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
from config_manager import Config
from error_handler import get_error_handler


class ExchangeConnector:
    def __init__(self, config: Config):
        self.config = config
        self.error_handler = get_error_handler()
        self.exchange: Optional[ccxt.binance] = None
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
            self.error_handler.log_startup("Exchange Connector")
        except Exception as e:
            self.error_handler.handle_exception(e, "exchange initialization")
            raise
    
    async def shutdown(self) -> None:
        """Gracefully shutdown exchange connection"""
        if self.exchange:
            await self.exchange.close()
            self.error_handler.log_shutdown("Exchange Connector")
    
    async def _setup_exchange(self) -> None:
        """Setup exchange connection based on mode"""
        is_live = self.config.mode == "live"
        
        if is_live:
            api_key = os.getenv("BINANCE_API_KEY")
            secret = os.getenv("BINANCE_SECRET")
            sandbox = False
        else:
            api_key = os.getenv("BINANCE_TESTNET_API_KEY")
            secret = os.getenv("BINANCE_TESTNET_SECRET")
            sandbox = True
        
        if not api_key or not secret:
            raise ValueError(f"Missing Binance {'live' if is_live else 'testnet'} API credentials")
        
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret,
            'sandbox': sandbox,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
                'recvWindow': 10000,  # 10 seconds window
            }
        })
        
        mode_text = "LIVE" if is_live else "TESTNET"
        self.error_handler.log_success(f"Exchange configured for {mode_text} mode")
    
    async def _test_connection(self) -> None:
        """Test exchange connection"""
        try:
            # First synchronize time with server
            await self.exchange.load_time_difference()
            # Then test connection
            await self.exchange.fetch_balance()
            self.error_handler.log_success("Exchange connection verified")
        except Exception as e:
            raise ConnectionError(f"Exchange connection failed: {e}")
    
    async def _retry_on_timestamp_error(self, func: Callable, *args, **kwargs) -> Any:
        """Retry function on timestamp error with time sync"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_str = str(e).lower()
                if 'timestamp' in error_str or 'ahead of the server' in error_str or 'invalid nonce' in error_str:
                    if attempt < max_retries - 1:
                        self.error_handler.log_warning(f"Timestamp error (attempt {attempt + 1}), resyncing time...")
                        await self.exchange.load_time_difference()
                        await asyncio.sleep(0.1)  # Small delay
                        continue
                raise e
    
    async def _reconcile_positions(self) -> None:
        """Reconcile actual exchange positions with local positions.json"""
        try:
            actual_positions = await self.get_open_positions()
            
            positions_file = "positions.json"
            if os.path.exists(positions_file):
                with open(positions_file, 'r') as f:
                    local_positions = json.load(f)
            else:
                local_positions = {}
            
            discrepancies = []
            
            for symbol, position in actual_positions.items():
                if symbol not in local_positions:
                    discrepancies.append(f"Found untracked position: {symbol}")
            
            for symbol in local_positions:
                if symbol not in actual_positions:
                    discrepancies.append(f"Local position not found on exchange: {symbol}")
            
            if discrepancies:
                self.error_handler.log_warning(
                    f"Position reconciliation found {len(discrepancies)} discrepancies"
                )
                for discrepancy in discrepancies[:5]:
                    self.error_handler.log_warning(discrepancy)
            else:
                self.error_handler.log_success("Position reconciliation completed - all positions synced")
                
        except Exception as e:
            self.error_handler.handle_exception(e, "position reconciliation")
    
    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get symbol trading info"""
        try:
            markets = await self.exchange.fetch_markets()
            market = next((m for m in markets if m['symbol'] == symbol), None)
            
            if not market:
                raise ValueError(f"Symbol {symbol} not found")
            
            return {
                'symbol': symbol,
                'base': market['base'],
                'quote': market['quote'],
                'active': market['active'],
                'type': market['type'],
                'spot': market['spot'],
                'future': market['future'],
                'precision': market['precision'],
                'limits': market['limits']
            }
        except Exception as e:
            self.error_handler.handle_exception(e, f"getting symbol info for {symbol}")
            raise
    
    def normalize_symbol(self, symbol: str, is_futures: bool = True) -> str:
        """Convert symbol from BTCUSDT format to ccxt format"""
        try:
            # If already in ccxt format, return as-is
            if '/' in symbol:
                return symbol
            
            # Convert BTCUSDT to BTC/USDT format
            if symbol.endswith('USDT'):
                base = symbol[:-4]  # Remove USDT
                # Validate base currency - should be at least 2 chars and not a fragment of USDT
                # Also check if it's a known invalid base like TUT, UST, etc.
                invalid_bases = ['TU', 'US', 'DT', 'SDT', 'TUT', 'UST']
                if len(base) >= 2 and base not in invalid_bases:
                    # Additional check: make sure it's not just a fragment
                    if len(base) >= 3 or base in ['BTC', 'ETH', 'BNB', 'ADA', 'DOT', 'SOL']:
                        if is_futures:
                            return f"{base}/USDT:USDT"
                        else:
                            return f"{base}/USDT"
                    else:
                        self.error_handler.log_warning(f"Suspicious base currency '{base}' from symbol '{symbol}', keeping original")
                        return symbol
                else:
                    # Invalid base currency, return original symbol
                    self.error_handler.log_warning(f"Invalid base currency '{base}' extracted from symbol '{symbol}'")
                    return symbol
            
            # Handle other quote currencies if needed
            for quote in ['BTC', 'ETH', 'BNB']:
                if symbol.endswith(quote):
                    base = symbol[:-len(quote)]
                    # Validate base currency
                    if len(base) >= 2:
                        if is_futures:
                            return f"{base}/{quote}:{quote}"
                        else:
                            return f"{base}/{quote}"
                    else:
                        self.error_handler.log_warning(f"Invalid base currency '{base}' extracted from symbol '{symbol}'")
                        return symbol
            
            # If we can't parse it, return as-is
            return symbol
            
        except Exception as e:
            self.error_handler.log_warning(f"Failed to normalize symbol {symbol}: {e}")
            return symbol
    
    async def get_binance_exchange_limits(self, symbol: str) -> Dict[str, Any]:
        """Get real Binance exchange limits directly from API"""
        try:
            # Use testnet or live API based on mode
            if self.config.mode == "live":
                base_url = "https://fapi.binance.com"
            else:
                base_url = "https://testnet.binancefuture.com"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/fapi/v1/exchangeInfo") as resp:
                    if resp.status != 200:
                        raise Exception(f"Failed to fetch exchange info: {resp.status}")
                    
                    data = await resp.json()
                    
                    # Convert symbol format for lookup
                    lookup_symbol = symbol.replace("/", "").replace(":", "")
                    
                    for s in data["symbols"]:
                        if s["symbol"] == lookup_symbol:
                            limits = {}
                            for f in s["filters"]:
                                if f["filterType"] == "LOT_SIZE":
                                    limits["min_qty"] = float(f["minQty"])
                                    limits["max_qty"] = float(f["maxQty"])
                                    limits["step_size"] = float(f["stepSize"])
                                elif f["filterType"] == "MIN_NOTIONAL":
                                    limits["min_notional"] = float(f["notional"])
                                elif f["filterType"] == "NOTIONAL":
                                    limits["min_notional"] = float(f["minNotional"])
                            
                            return limits
                    
                    # Symbol not found
                    return {}
                    
        except Exception as e:
            self.error_handler.log_warning(f"Failed to get real Binance limits for {symbol}: {e}")
            return {}
    
    async def get_minimum_amount(self, symbol: str) -> float:
        """Get minimum trade amount for symbol - DEPRECATED, use validate_order_size instead"""
        try:
            # Try to get real Binance limits first
            limits = await self.get_binance_exchange_limits(symbol)
            if limits and 'min_qty' in limits:
                return limits['min_qty']
            
            # Fallback to ccxt (but with warning about potential inaccuracy)
            markets = await self.exchange.load_markets()
            
            # Try the symbol as-is first
            if symbol in markets:
                market = markets[symbol]
                min_amount = market['limits']['amount']['min']
                if min_amount is not None:
                    return float(min_amount)
            
            # Try normalized futures format
            futures_symbol = self.normalize_symbol(symbol, is_futures=True)
            if futures_symbol in markets:
                market = markets[futures_symbol]
                min_amount = market['limits']['amount']['min']
                if min_amount is not None:
                    return float(min_amount)
            
            # Try normalized spot format
            spot_symbol = self.normalize_symbol(symbol, is_futures=False)
            if spot_symbol in markets:
                market = markets[spot_symbol]
                min_amount = market['limits']['amount']['min']
                if min_amount is not None:
                    return float(min_amount)
            
            # If nothing found, use conservative default
            self.error_handler.log_warning(f"No minimum amount found for {symbol}, using conservative default 0.0001")
            return 0.0001
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"getting minimum amount for {symbol}")
            return 0.0001
    
    async def validate_order_size(self, symbol: str, amount: float, price: float) -> Dict[str, Any]:
        """Validate order size using real Binance limits (quantity + notional)"""
        try:
            # Get real Binance limits
            limits = await self.get_binance_exchange_limits(symbol)
            
            validation = {
                'valid': True,
                'errors': [],
                'warnings': [],
                'min_qty': 0.0001,  # Default conservative
                'min_notional': 5.0  # Default Binance Futures minimum
            }
            
            if limits:
                validation['min_qty'] = limits.get('min_qty', 0.0001)
                validation['min_notional'] = limits.get('min_notional', 5.0)
            else:
                validation['warnings'].append("Using default limits - could not fetch real Binance limits")
            
            # Check quantity limit
            if amount < validation['min_qty']:
                validation['valid'] = False
                validation['errors'].append(f"Amount {amount} below minimum quantity {validation['min_qty']}")
            
            # Check notional value limit
            notional = amount * price
            if notional < validation['min_notional']:
                validation['valid'] = False
                validation['errors'].append(f"Notional value ${notional:.2f} below minimum ${validation['min_notional']}")
            
            return validation
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"validating order size for {symbol}")
            return {
                'valid': False,
                'errors': [f"Validation error: {e}"],
                'warnings': [],
                'min_qty': 0.0001,
                'min_notional': 5.0
            }
    
    async def get_current_price(self, symbol: str) -> float:
        """Get current price for symbol"""
        try:
            # Try the symbol as-is first
            try:
                ticker = await self.exchange.fetch_ticker(symbol)
                return float(ticker['last'])
            except:
                pass
            
            # Try normalized futures format
            futures_symbol = self.normalize_symbol(symbol, is_futures=True)
            try:
                ticker = await self.exchange.fetch_ticker(futures_symbol)
                return float(ticker['last'])
            except:
                pass
            
            # Try normalized spot format
            spot_symbol = self.normalize_symbol(symbol, is_futures=False)
            ticker = await self.exchange.fetch_ticker(spot_symbol)
            return float(ticker['last'])
            
        except Exception as e:
            self.error_handler.handle_exception(e, f"getting price for {symbol}")
            raise
    
    async def get_account_balance(self) -> Dict[str, float]:
        """Get account balance"""
        try:
            balance = await self._retry_on_timestamp_error(self.exchange.fetch_balance)
            return {
                'total_usdt': balance['USDT']['total'] if 'USDT' in balance else 0,
                'free_usdt': balance['USDT']['free'] if 'USDT' in balance else 0,
                'used_usdt': balance['USDT']['used'] if 'USDT' in balance else 0
            }
        except Exception as e:
            self.error_handler.handle_exception(e, "getting account balance")
            raise
    
    async def get_open_positions(self) -> Dict[str, Dict]:
        """Get all open positions"""
        try:
            positions = await self._retry_on_timestamp_error(self.exchange.fetch_positions)
            open_positions = {}
            
            for position in positions:
                if position['contracts'] > 0:
                    symbol = position['symbol']
                    open_positions[symbol] = {
                        'symbol': symbol,
                        'side': position['side'],
                        'size': position['contracts'],
                        'entry_price': position['entryPrice'],
                        'mark_price': position['markPrice'],
                        'pnl': position['unrealizedPnl'],
                        'percentage': position['percentage']
                    }
            
            return open_positions
        except Exception as e:
            self.error_handler.handle_exception(e, "getting open positions")
            raise
    
    async def place_limit_order(self, symbol: str, side: str, amount: float, 
                               price: float, reduce_only: bool = False) -> Dict[str, Any]:
        """Place limit order"""
        try:
            params = {}
            if reduce_only:
                params['reduceOnly'] = True
            
            order = await self._retry_on_timestamp_error(
                self.exchange.create_limit_order,
                symbol, side, amount, price, params=params
            )
            
            self.error_handler.log_trade_event(
                "ORDER_PLACED", symbol, 
                f"{side.upper()} {amount} @ {price} (Limit)"
            )
            
            return order
        except Exception as e:
            self.error_handler.handle_exception(e, f"placing limit order {symbol}")
            raise
    
    async def place_take_profit_order(self, symbol: str, side: str, amount: float, 
                                     trigger_price: float) -> Dict[str, Any]:
        """Place take profit order - TAKE_PROFIT_MARKET for guaranteed execution"""
        try:
            params = {
                'stopPrice': trigger_price,
                'reduceOnly': True,  # Only reduce position, don't open new one
                'workingType': 'MARK_PRICE',  # Use mark price to avoid manipulation
                'timeInForce': 'GTE_GTC',
                'priceProtect': True  # Prevent orders from executing at extreme prices
            }
            
            order = await self._retry_on_timestamp_error(
                self.exchange.create_order,
                symbol, 'TAKE_PROFIT_MARKET', side, amount, None, params=params
            )
            
            self.error_handler.log_trade_event(
                "TP_ORDER_PLACED", symbol,
                f"{side.upper()} {amount} @ {trigger_price} (TP)"
            )
            
            return order
        except Exception as e:
            error_msg = str(e).lower()
            if "would immediately trigger" in error_msg:
                self.error_handler.log_warning(f"TP order for {symbol} would immediately trigger - price already reached")
                # This is actually a good thing - TP level already hit!
                return {"status": "immediately_triggered", "symbol": symbol, "type": "take_profit"}
            else:
                self.error_handler.handle_exception(e, f"placing TP order {symbol}")
                raise
    
    async def place_stop_loss_order(self, symbol: str, side: str, amount: float, 
                                   trigger_price: float) -> Dict[str, Any]:
        """Place stop loss order - STOP_MARKET for guaranteed execution"""
        try:
            params = {
                'stopPrice': trigger_price,
                'reduceOnly': True,  # Only reduce position, don't open new one
                'workingType': 'MARK_PRICE',  # Use mark price to avoid manipulation
                'timeInForce': 'GTE_GTC',
                'priceProtect': True  # Prevent orders from executing at extreme prices
            }
            
            order = await self._retry_on_timestamp_error(
                self.exchange.create_order,
                symbol, 'STOP_MARKET', side, amount, None, params=params
            )
            
            self.error_handler.log_trade_event(
                "SL_ORDER_PLACED", symbol,
                f"{side.upper()} {amount} @ {trigger_price} (SL)"
            )
            
            return order
        except Exception as e:
            self.error_handler.handle_exception(e, f"placing SL order {symbol}")
            raise
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel order"""
        try:
            await self.exchange.cancel_order(order_id, symbol)
            self.error_handler.log_trade_event("ORDER_CANCELLED", symbol, f"ID: {order_id}")
            return True
        except Exception as e:
            self.error_handler.handle_exception(e, f"cancelling order {order_id}")
            return False
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all orders for symbol or all symbols"""
        try:
            if symbol:
                orders = await self.exchange.fetch_open_orders(symbol)
                cancelled_count = 0
                for order in orders:
                    if await self.cancel_order(symbol, order['id']):
                        cancelled_count += 1
            else:
                cancelled_count = 0
                positions = await self.get_open_positions()
                for pos_symbol in positions.keys():
                    orders = await self.exchange.fetch_open_orders(pos_symbol)
                    for order in orders:
                        if await self.cancel_order(pos_symbol, order['id']):
                            cancelled_count += 1
            
            self.error_handler.log_success(f"Cancelled {cancelled_count} orders")
            return cancelled_count
        except Exception as e:
            self.error_handler.handle_exception(e, "cancelling all orders")
            return 0
    
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for symbol"""
        try:
            await self.exchange.set_leverage(leverage, symbol)
            self.error_handler.log_success(f"Set leverage {leverage}x for {symbol}")
            return True
        except Exception as e:
            self.error_handler.handle_exception(e, f"setting leverage for {symbol}")
            return False
    
    def calculate_position_size(self, symbol: str, price: float, 
                               usd_amount: float, is_futures: bool = True) -> float:
        """Calculate position size based on USD amount"""
        if is_futures:
            return round(usd_amount / price, 6)
        else:
            return round(usd_amount / price, 8)
    
    def adjust_tp_price(self, tp_price: float, side: str, adjustment: float = 0.0) -> float:
        """Return TP price as-is since we use TAKE_PROFIT_MARKET orders
        
        TAKE_PROFIT_MARKET orders execute at market price when triggered,
        so no price adjustment is needed - just use the exact TP level.
        """
        return tp_price  # No adjustment needed for market orders
    
    def is_futures_supported(self) -> bool:
        """Check if futures trading is supported in current mode"""
        return True
    
    def is_spot_supported(self) -> bool:
        """Check if spot trading is supported in current mode"""
        return self.config.mode == "live"