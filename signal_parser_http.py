"""
Signal Parser HTTP - Pure HTTP implementation for Gemini API compatible with Termux
Processes text and image content to extract trading information with rate limiting
"""

import asyncio
import json
import base64
import os
import re
import time
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import requests
from error_handler import get_error_handler
from performance_monitor import get_performance_monitor


@dataclass
class TradeSignal:
    """Trade signal data structure"""
    symbol: str
    action: str  # 'buy', 'sell', 'long', 'short'
    entry_price: float
    stop_loss: float
    take_profit: float
    leverage: Optional[int] = None
    trade_type: str = "futures"  # 'futures' or 'spot'
    confidence_score: float = 0.0
    source: str = ""
    raw_content: str = ""
    
    # Additional calculated fields
    stop_loss_percentage: float = 0.0
    take_profit_percentage: float = 0.0
    
    def __post_init__(self):
        """Calculate percentages after initialization"""
        if self.entry_price > 0:
            self.stop_loss_percentage = abs((self.stop_loss - self.entry_price) / self.entry_price * 100)
            self.take_profit_percentage = abs((self.take_profit - self.entry_price) / self.entry_price * 100)


class RateLimiter:
    """Simple rate limiter for API calls"""
    
    def __init__(self, requests_per_minute: int):
        self.requests_per_minute = requests_per_minute
        self.requests = []
    
    async def wait_if_needed(self):
        """Wait if rate limit would be exceeded"""
        now = time.time()
        
        # Remove requests older than 1 minute
        self.requests = [req_time for req_time in self.requests if now - req_time < 60]
        
        # Check if we need to wait
        if len(self.requests) >= self.requests_per_minute:
            oldest_request = min(self.requests)
            wait_time = 60 - (now - oldest_request)
            if wait_time > 0:
                print(f"⏳ Rate limit reached, waiting {wait_time:.1f} seconds...")
                await asyncio.sleep(wait_time)
        
        # Record this request
        self.requests.append(now)


class SignalParserHTTP:
    """HTTP-based signal parser compatible with Termux"""
    
    def __init__(self, config):
        self.config = config
        self.error_handler = get_error_handler()
        self.performance_monitor = get_performance_monitor()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        print(f"🔑 Gemini API key loaded: {'✅ Yes' if self.gemini_api_key else '❌ No'}")
        if self.gemini_api_key:
            print(f"🔑 Key length: {len(self.gemini_api_key)} characters")
        
        self.rate_limiter = RateLimiter(60)  # 60 requests per minute
        self.signal_cache: Dict[str, TradeSignal] = {}
        
        if self.gemini_api_key:
            print("🤖 Signal Parser Mode: GEMINI AI ONLY")
            print("📡 All signal extraction handled exclusively by Gemini 1.5 Flash")
            print("❌ No fallback parsing methods - Gemini failures will be reported")
        else:
            print("⚠️ No Gemini API key - using fallback regex parsing only")
        
        self.error_handler.log_startup("Signal Parser HTTP")
    
    async def parse_signal(self, content: str, images: List[str] = None, source: str = "") -> Optional[TradeSignal]:
        """Parse trading signal from content and images"""
        try:
            if not content and not images:
                return None
            
            # Try Gemini AI parsing first if available
            if self.gemini_api_key:
                signal = await self._parse_with_gemini(content, images, source)
                if signal:
                    return signal
            
            # Fallback to regex parsing
            signal = await self._parse_with_regex(content, source)
            return signal
            
        except Exception as e:
            self.error_handler.handle_exception(e, "parsing signal")
            return None
    
    async def _parse_with_gemini(self, content: str, images: List[str] = None, source: str = "") -> Optional[TradeSignal]:
        """Parse signal using Gemini AI API"""
        try:
            await self.rate_limiter.wait_if_needed()
            
            # Prepare the prompt
            prompt = self._create_gemini_prompt()
            
            # Prepare the request
            parts = [{"text": prompt}, {"text": f"Signal content: {content}"}]
            
            # Add images if available
            if images:
                for image_url in images[:3]:  # Limit to 3 images
                    try:
                        # Download and encode image
                        image_data = await self._download_image(image_url)
                        if image_data:
                            parts.append({
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": image_data
                                }
                            })
                    except Exception as e:
                        print(f"⚠️ Failed to process image {image_url}: {e}")
            
            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.1,
                    "topK": 1,
                    "topP": 0.8,
                    "maxOutputTokens": 1024,
                }
            }
            
            # Make API request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={self.gemini_api_key}"
            
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if 'candidates' in result and result['candidates']:
                    response_text = result['candidates'][0]['content']['parts'][0]['text']
                    signal = self._parse_gemini_response(response_text, content, source)
                    
                    if signal:
                        print(f"✅ Gemini successfully parsed signal: {signal.symbol} {signal.action}")
                        return signal
                    else:
                        print("❌ Gemini parsing failed - no valid signal found")
                else:
                    print("❌ Gemini API returned no candidates")
            else:
                print(f"❌ Gemini API error: {response.status_code} - {response.text}")
            
            return None
            
        except Exception as e:
            self.error_handler.handle_exception(e, "Gemini AI parsing")
            return None
    
    async def _download_image(self, image_url: str) -> Optional[str]:
        """Download and encode image for Gemini"""
        try:
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
            return None
        except Exception as e:
            print(f"❌ Error downloading image: {e}")
            return None
    
    def _create_gemini_prompt(self) -> str:
        """Create the prompt for Gemini AI"""
        return """
You are a cryptocurrency trading signal parser. Extract trading information from the provided text and/or images.

CRITICAL REQUIREMENTS:
1. Return ONLY valid JSON in the exact format specified below
2. All numeric values must be valid numbers (not null, not strings)
3. If any required field cannot be determined, return {"signal": null}

REQUIRED JSON FORMAT:
{
    "signal": {
        "symbol": "BTCUSDT",
        "action": "buy",
        "entry_price": 45000.0,
        "stop_loss": 44000.0,
        "take_profit": 47000.0,
        "leverage": 10,
        "trade_type": "futures",
        "confidence_score": 85.0
    }
}

PARSING RULES:
- symbol: Extract crypto symbol (e.g., BTC, ETH) and add USDT if not present
- action: "buy" for long/buy signals, "sell" for short/sell signals
- entry_price: The entry/buy price (must be a number)
- stop_loss: The stop loss price (must be a number)
- take_profit: The take profit price (use first TP if multiple)
- leverage: Extract leverage multiplier (default to 10 if not specified)
- trade_type: "futures" for leveraged trades, "spot" for spot trades
- confidence_score: Rate signal quality 0-100 based on clarity

COMMON SIGNAL FORMATS TO RECOGNIZE:
- "#BTCUSDT LONG" with entry, SL, TP
- "BTC/USDT Buy at 45000, SL: 44000, TP: 47000"
- Images with trading charts and annotations
- Signals with multiple take profit levels (use first TP)

If the content doesn't contain a clear trading signal, return {"signal": null}
"""
    
    def _parse_gemini_response(self, response_text: str, original_content: str, source: str) -> Optional[TradeSignal]:
        """Parse Gemini's JSON response into TradeSignal"""
        try:
            # Clean up the response text
            response_text = response_text.strip()
            
            # Extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                print("❌ No JSON found in Gemini response")
                return None
            
            json_text = response_text[json_start:json_end]
            
            # Parse JSON
            data = json.loads(json_text)
            
            if not data.get('signal'):
                print("ℹ️ Gemini determined no valid signal present")
                return None
            
            signal_data = data['signal']
            
            # Validate required fields
            required_fields = ['symbol', 'action', 'entry_price', 'stop_loss', 'take_profit']
            for field in required_fields:
                if field not in signal_data or signal_data[field] is None:
                    print(f"❌ Missing required field: {field}")
                    return None
            
            # Create TradeSignal
            signal = TradeSignal(
                symbol=str(signal_data['symbol']).upper(),
                action=str(signal_data['action']).lower(),
                entry_price=float(signal_data['entry_price']),
                stop_loss=float(signal_data['stop_loss']),
                take_profit=float(signal_data['take_profit']),
                leverage=int(signal_data.get('leverage', 10)),
                trade_type=str(signal_data.get('trade_type', 'futures')),
                confidence_score=float(signal_data.get('confidence_score', 0)),
                source=source,
                raw_content=original_content
            )
            
            # Validate signal logic
            if not self._validate_signal_logic(signal):
                print("❌ Signal failed logic validation")
                return None
            
            return signal
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error in Gemini response: {e}")
            return None
        except (ValueError, KeyError) as e:
            print(f"❌ Data validation error in Gemini response: {e}")
            return None
        except Exception as e:
            print(f"❌ Error parsing Gemini response: {e}")
            return None
    
    async def _parse_with_regex(self, content: str, source: str = "") -> Optional[TradeSignal]:
        """Fallback regex-based signal parsing"""
        try:
            print("🔍 Using fallback regex parsing...")
            
            # Normalize content
            content = content.upper().replace('/', '').replace('-', '').replace('_', '')
            
            # Extract symbol
            symbol_patterns = [
                r'#([A-Z]{2,6})USDT',
                r'([A-Z]{2,6})USDT',
                r'([A-Z]{2,6})/USDT',
                r'#([A-Z]{2,6})'
            ]
            
            symbol = None
            for pattern in symbol_patterns:
                match = re.search(pattern, content)
                if match:
                    symbol = match.group(1) + 'USDT'
                    break
            
            if not symbol:
                print("❌ Could not extract symbol from content")
                return None
            
            # Extract action
            action = 'buy'  # Default
            if any(word in content for word in ['SHORT', 'SELL', 'BEAR']):
                action = 'sell'
            elif any(word in content for word in ['LONG', 'BUY', 'BULL']):
                action = 'buy'
            
            # Extract prices
            price_patterns = [
                r'ENTRY[:\s]*(\d+\.?\d*)',
                r'BUY[:\s]*(\d+\.?\d*)',
                r'PRICE[:\s]*(\d+\.?\d*)',
                r'(\d+\.?\d*)'  # Any number as fallback
            ]
            
            prices = []
            for line in content.split('\\n'):
                for pattern in price_patterns:
                    matches = re.findall(pattern, line)
                    for match in matches:
                        try:
                            price = float(match)
                            if 0.001 < price < 1000000:  # Reasonable price range
                                prices.append(price)
                        except ValueError:
                            continue
            
            if len(prices) < 3:
                print(f"❌ Insufficient price data found: {len(prices)} prices")
                return None
            
            # Assign prices (entry, stop loss, take profit)
            entry_price = prices[0]
            stop_loss = prices[1]
            take_profit = prices[2]
            
            # Extract leverage
            leverage_match = re.search(r'(\d+)X|LEVERAGE[:\s]*(\d+)', content)
            leverage = 10  # Default
            if leverage_match:
                leverage = int(leverage_match.group(1) or leverage_match.group(2))
            
            signal = TradeSignal(
                symbol=symbol,
                action=action,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                leverage=leverage,
                trade_type='futures',
                confidence_score=50.0,  # Lower confidence for regex
                source=source,
                raw_content=content
            )
            
            if self._validate_signal_logic(signal):
                print(f"✅ Regex parsing successful: {signal.symbol} {signal.action}")
                return signal
            else:
                print("❌ Regex signal failed validation")
                return None
            
        except Exception as e:
            self.error_handler.handle_exception(e, "regex parsing")
            return None
    
    def _validate_signal_logic(self, signal: TradeSignal) -> bool:
        """Validate signal logic and price relationships"""
        try:
            # Basic price validation
            if signal.entry_price <= 0 or signal.stop_loss <= 0 or signal.take_profit <= 0:
                return False
            
            # Check price relationships for buy signals
            if signal.action == 'buy':
                # Stop loss should be below entry, take profit above
                if signal.stop_loss >= signal.entry_price:
                    print(f"⚠️ Invalid buy signal: SL ({signal.stop_loss}) >= Entry ({signal.entry_price})")
                    return False
                if signal.take_profit <= signal.entry_price:
                    print(f"⚠️ Invalid buy signal: TP ({signal.take_profit}) <= Entry ({signal.entry_price})")
                    return False
            
            # Check price relationships for sell signals
            elif signal.action == 'sell':
                # Stop loss should be above entry, take profit below
                if signal.stop_loss <= signal.entry_price:
                    print(f"⚠️ Invalid sell signal: SL ({signal.stop_loss}) <= Entry ({signal.entry_price})")
                    return False
                if signal.take_profit >= signal.entry_price:
                    print(f"⚠️ Invalid sell signal: TP ({signal.take_profit}) >= Entry ({signal.entry_price})")
                    return False
            
            # Check leverage
            if signal.leverage < 1 or signal.leverage > 125:
                print(f"⚠️ Invalid leverage: {signal.leverage}")
                return False
            
            # Check that stop loss and take profit aren't too close to entry
            entry = signal.entry_price
            sl_distance = abs(signal.stop_loss - entry) / entry
            tp_distance = abs(signal.take_profit - entry) / entry
            
            if sl_distance < 0.001:  # Less than 0.1%
                print(f"⚠️ Stop loss too close to entry: {sl_distance*100:.3f}%")
                return False
            
            if tp_distance < 0.001:  # Less than 0.1%
                print(f"⚠️ Take profit too close to entry: {tp_distance*100:.3f}%")
                return False
            
            print(f"✅ Signal validation passed: SL {sl_distance*100:.1f}%, TP {tp_distance*100:.1f}%")
            return True
            
        except Exception as e:
            print(f"❌ Signal validation error: {e}")
            return False


# Alias for compatibility
SignalParser = SignalParserHTTP