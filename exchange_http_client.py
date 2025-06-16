"""
Lightweight Exchange HTTP Client - Termux compatible replacement for ccxt
Uses only requests and built-in libraries to interact with exchange APIs
"""

import json
import time
import hmac
import hashlib
import urllib.parse
from typing import Dict, List, Optional, Any
import requests
from datetime import datetime


class ExchangeError(Exception):
    """Base exception for exchange errors"""
    pass


class BinanceHTTPClient:
    """Pure HTTP Binance client compatible with Termux"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        if testnet:
            self.base_url = "https://testnet.binance.vision/api"
            self.futures_url = "https://testnet.binancefuture.com/fapi"
        else:
            self.base_url = "https://api.binance.com/api"
            self.futures_url = "https://fapi.binance.com/fapi"
        
        self.session = requests.Session()
        self.session.headers.update({
            'X-MBX-APIKEY': api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        })
    
    def _generate_signature(self, query_string: str) -> str:
        """Generate HMAC SHA256 signature"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds"""
        return int(time.time() * 1000)
    
    def _make_request(self, method: str, endpoint: str, params: Dict = None, signed: bool = False, futures: bool = False) -> Dict:
        """Make HTTP request to exchange"""
        try:
            base_url = self.futures_url if futures else self.base_url
            url = f"{base_url}{endpoint}"
            
            if params is None:
                params = {}
            
            if signed:
                params['timestamp'] = self._get_timestamp()
                query_string = urllib.parse.urlencode(params)
                params['signature'] = self._generate_signature(query_string)
            
            if method == 'GET':
                response = self.session.get(url, params=params)
            elif method == 'POST':
                response = self.session.post(url, data=params)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params)
            else:
                raise ExchangeError(f"Unsupported HTTP method: {method}")
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                raise ExchangeError(error_msg)
                
        except requests.exceptions.RequestException as e:
            raise ExchangeError(f"Network error: {str(e)}")
        except json.JSONDecodeError as e:
            raise ExchangeError(f"JSON decode error: {str(e)}")
    
    def test_connectivity(self) -> bool:
        """Test exchange connectivity"""
        try:
            # Test spot connectivity
            self._make_request('GET', '/v3/ping')
            
            # Test futures connectivity if available
            try:
                self._make_request('GET', '/v1/ping', futures=True)
            except:
                pass  # Futures might not be available in testnet
            
            return True
        except Exception as e:
            print(f"❌ Exchange connectivity test failed: {e}")
            return False
    
    def get_account_info(self) -> Dict:
        """Get account information"""
        return self._make_request('GET', '/v3/account', signed=True)
    
    def get_futures_account(self) -> Dict:
        """Get futures account information"""
        return self._make_request('GET', '/v2/account', signed=True, futures=True)
    
    def get_balance(self, symbol: str = None) -> Dict:
        """Get account balance"""
        account = self.get_account_info()
        balances = {}
        
        for balance in account.get('balances', []):
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])
            total = free + locked
            
            if total > 0:  # Only return non-zero balances
                balances[asset] = {
                    'free': free,
                    'locked': locked,
                    'total': total
                }
        
        if symbol:
            return balances.get(symbol, {'free': 0, 'locked': 0, 'total': 0})
        
        return balances
    
    def get_futures_positions(self) -> List[Dict]:
        """Get futures positions"""
        try:
            positions = self._make_request('GET', '/v2/positionRisk', signed=True, futures=True)
            active_positions = []
            
            for pos in positions:
                size = float(pos['positionAmt'])
                if abs(size) > 0:  # Only active positions
                    active_positions.append({
                        'symbol': pos['symbol'],
                        'size': size,
                        'side': 'long' if size > 0 else 'short',
                        'entry_price': float(pos['entryPrice']),
                        'mark_price': float(pos['markPrice']),
                        'pnl': float(pos['unRealizedProfit']),
                        'percentage': float(pos['percentage']) if pos['percentage'] else 0
                    })
            
            return active_positions
        except Exception as e:
            print(f"❌ Error getting futures positions: {e}")
            return []
    
    def get_ticker(self, symbol: str) -> Dict:
        """Get ticker price for symbol"""
        params = {'symbol': symbol}
        ticker = self._make_request('GET', '/v3/ticker/price', params)
        return {
            'symbol': ticker['symbol'],
            'price': float(ticker['price'])
        }
    
    def create_order(self, symbol: str, side: str, order_type: str, quantity: float,
                    price: float = None, time_in_force: str = 'GTC', futures: bool = False) -> Dict:
        """Create order"""
        params = {
            'symbol': symbol,
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': str(quantity)
        }
        
        if price and order_type.upper() in ['LIMIT', 'STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT']:
            params['price'] = str(price)
            params['timeInForce'] = time_in_force
        
        endpoint = '/v1/order' if futures else '/v3/order'
        return self._make_request('POST', endpoint, params, signed=True, futures=futures)
    
    def cancel_order(self, symbol: str, order_id: int = None, orig_client_order_id: str = None, futures: bool = False) -> Dict:
        """Cancel order"""
        params = {'symbol': symbol}
        
        if order_id:
            params['orderId'] = order_id
        elif orig_client_order_id:
            params['origClientOrderId'] = orig_client_order_id
        else:
            raise ExchangeError("Either order_id or orig_client_order_id must be provided")
        
        endpoint = '/v1/order' if futures else '/v3/order'
        return self._make_request('DELETE', endpoint, params, signed=True, futures=futures)
    
    def get_open_orders(self, symbol: str = None, futures: bool = False) -> List[Dict]:
        """Get open orders"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        
        endpoint = '/v1/openOrders' if futures else '/v3/openOrders'
        orders = self._make_request('GET', endpoint, params, signed=True, futures=futures)
        
        processed_orders = []
        for order in orders:
            processed_orders.append({
                'id': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'].lower(),
                'type': order['type'].lower(),
                'quantity': float(order['origQty']),
                'filled': float(order['executedQty']),
                'remaining': float(order['origQty']) - float(order['executedQty']),
                'price': float(order['price']) if order['price'] != '0.00000000' else None,
                'status': order['status'].lower(),
                'timestamp': order['time']
            })
        
        return processed_orders
    
    def cancel_all_orders(self, symbol: str = None, futures: bool = False) -> int:
        """Cancel all open orders"""
        try:
            if symbol:
                # Cancel orders for specific symbol
                params = {'symbol': symbol}
                endpoint = '/v1/allOpenOrders' if futures else '/v3/openOrders'
                result = self._make_request('DELETE', endpoint, params, signed=True, futures=futures)
                return len(result) if isinstance(result, list) else 1
            else:
                # Get all open orders and cancel them individually
                open_orders = self.get_open_orders(futures=futures)
                cancelled_count = 0
                
                for order in open_orders:
                    try:
                        self.cancel_order(order['symbol'], order['id'], futures=futures)
                        cancelled_count += 1
                    except Exception as e:
                        print(f"❌ Failed to cancel order {order['id']}: {e}")
                
                return cancelled_count
        except Exception as e:
            print(f"❌ Error cancelling orders: {e}")
            return 0
    
    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """Set leverage for futures symbol"""
        params = {
            'symbol': symbol,
            'leverage': leverage
        }
        return self._make_request('POST', '/v1/leverage', params, signed=True, futures=True)
    
    def get_exchange_info(self, futures: bool = False) -> Dict:
        """Get exchange information"""
        endpoint = '/v1/exchangeInfo' if futures else '/v3/exchangeInfo'
        return self._make_request('GET', endpoint, futures=futures)
    
    def get_klines(self, symbol: str, interval: str = '1h', limit: int = 100) -> List[List]:
        """Get kline/candlestick data"""
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        return self._make_request('GET', '/v3/klines', params)


class ExchangeClient:
    """Unified exchange client interface"""
    
    def __init__(self, exchange: str, api_key: str, api_secret: str, testnet: bool = False):
        self.exchange = exchange.lower()
        
        if self.exchange == 'binance':
            self.client = BinanceHTTPClient(api_key, api_secret, testnet)
        else:
            raise ExchangeError(f"Unsupported exchange: {exchange}")
    
    def __getattr__(self, name):
        """Delegate method calls to the underlying client"""
        return getattr(self.client, name)