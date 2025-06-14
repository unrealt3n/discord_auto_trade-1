"""
Signal Parser - Gemini API integration for extracting trade data from Discord signals
Processes text and image content to extract trading information with rate limiting
"""

import asyncio
import aiohttp
import json
import base64
import os
import re
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from error_handler import get_error_handler
from performance_monitor import get_performance_monitor


@dataclass
class TradeSignal:
    symbol: str
    direction: str  # 'long' or 'short'
    entry_price: float
    stop_loss: float
    take_profits: List[float]
    leverage: Optional[int] = None
    trade_type: str = "futures"  # 'futures' or 'spot'
    confidence: float = 0.0
    source: str = ""
    raw_content: str = ""


class SignalParser:
    def __init__(self):
        self.error_handler = get_error_handler()
        self.performance_monitor = get_performance_monitor()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        print(f"🔑 Gemini API key loaded: {'✅ Yes' if self.gemini_api_key else '❌ No'}")
        if self.gemini_api_key:
            print(f"🔑 Key length: {len(self.gemini_api_key)} characters")
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(60, 60)  # 60 requests per minute
        self.signal_cache: Dict[str, TradeSignal] = {}  # Cache for similar signals
        
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
    
    async def initialize(self) -> None:
        """Initialize signal parser"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'Content-Type': 'application/json'}
        )
        
        print("🤖 Signal Parser Mode: GEMINI AI ONLY")
        print("📡 All signal extraction handled exclusively by Gemini 1.5 Flash")
        print("❌ No fallback parsing methods - Gemini failures will be reported")
        
        self.error_handler.log_startup("Signal Parser")
    
    async def shutdown(self) -> None:
        """Shutdown signal parser"""
        if self.session:
            await self.session.close()
        self.error_handler.log_shutdown("Signal Parser")
    
    async def parse_signal(self, content: str, images: List[bytes] = None, 
                          source: str = "unknown") -> Optional[TradeSignal]:
        """Parse trading signal from text and/or images"""
        with self.performance_monitor.time_operation("signal_parsing"):
            try:
                # Check cache first for similar content
                content_hash = str(hash(content[:500]))  # Hash first 500 chars
                if content_hash in self.signal_cache:
                    cached_signal = self.signal_cache[content_hash]
                    # Update source and return cached signal
                    cached_signal.source = source
                    self.error_handler.log_debug(f"Using cached signal for {cached_signal.symbol}")
                    return cached_signal
                
                await self.rate_limiter.acquire()
                
                # Enhanced content validation
                if not self._validate_content(content, images):
                    return None
                
                prompt = self._build_extraction_prompt()
                
                gemini_content = []
                if content.strip():
                    gemini_content.append({"text": content})
                
                if images:
                    for i, image_data in enumerate(images):
                        if len(image_data) > 20 * 1024 * 1024:  # 20MB limit
                            self.error_handler.log_warning(f"Image {i+1} too large, skipping")
                            continue
                        
                        image_base64 = base64.b64encode(image_data).decode('utf-8')
                        gemini_content.append({
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64
                            }
                        })
                
                if not gemini_content:
                    self.error_handler.log_warning("No valid content to parse")
                    return None
                
                with self.performance_monitor.time_operation("gemini_api_call"):
                    response = await self._call_gemini_api(prompt, gemini_content)
                
                if response:
                    signal = self._parse_gemini_response(response, content, source)
                    if signal and self._enhanced_signal_validation(signal, content):
                        # Cache the signal
                        self.signal_cache[content_hash] = signal
                        
                        # Limit cache size
                        if len(self.signal_cache) > 100:
                            oldest_key = next(iter(self.signal_cache))
                            del self.signal_cache[oldest_key]
                        
                        self.error_handler.log_success(
                            f"Signal parsed: {signal.symbol} {signal.direction.upper()} "
                            f"@ {signal.entry_price} (confidence: {signal.confidence:.2f})"
                        )
                        return signal
                    else:
                        self.error_handler.log_error(f"❌ Gemini signal validation failed for {source}")
                        return None
                else:
                    self.error_handler.log_error(f"❌ Gemini API returned no response for {source}")
                    return None
                
            except Exception as e:
                self.error_handler.handle_exception(e, "parsing signal")
                return None
    
    def _build_extraction_prompt(self) -> str:
        """Build extraction prompt for Gemini API"""
        return """
You are a trading signal extraction AI. Extract trading information from the provided content (text and/or images).

Return ONLY a JSON object with this exact structure:
{
    "symbol": "BTCUSDT",
    "direction": "long",
    "entry_price": 45000.0,
    "stop_loss": 44000.0,
    "take_profits": [46000.0, 47000.0, 48000.0],
    "leverage": 10,
    "trade_type": "futures",
    "confidence": 0.85
}

RULES:
1. symbol: Extract the trading pair (e.g., BTCUSDT, ETHUSDT)
2. direction: "long" for buy/long positions, "short" for sell/short positions
3. entry_price: Entry price as float
4. stop_loss: Stop loss price as float
5. take_profits: Array of all TP levels as floats
6. leverage: Integer leverage (null if not specified)
7. trade_type: "futures" or "spot"
8. confidence: Your confidence in the extraction (0.0-1.0)

TRADE TYPE DETECTION:
- Use "futures" if: leverage mentioned, words like "futures", "perpetual", "margin", "short", "long", or margin interface visible
- Use "spot" if: no leverage, words like "spot", "buy", "sell" without margin context, or spot UI shown
- Default to "futures" if ambiguous

If you cannot extract a valid trading signal, return:
{"error": "Unable to extract trading signal"}

Do not include any explanation, only return the JSON object.
"""
    
    async def _call_gemini_api(self, prompt: str, content: List[Dict]) -> Optional[Dict]:
        """Call Gemini API with rate limiting"""
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}] + content
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "topK": 1,
                    "topP": 0.1,
                    "maxOutputTokens": 1024
                },
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
            }
            
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"🔍 Gemini API response: {data}")
                    
                    if 'candidates' in data and data['candidates']:
                        text_response = data['candidates'][0]['content']['parts'][0]['text']
                        print(f"📝 Gemini text response: {text_response}")
                        
                        if text_response and text_response.strip():
                            try:
                                # Remove markdown code block formatting if present
                                clean_text = text_response.strip()
                                if clean_text.startswith('```json'):
                                    clean_text = clean_text[7:]  # Remove ```json
                                if clean_text.endswith('```'):
                                    clean_text = clean_text[:-3]  # Remove ```
                                clean_text = clean_text.strip()
                                
                                print(f"🧹 Cleaned JSON text: {clean_text}")
                                return json.loads(clean_text)
                            except json.JSONDecodeError as e:
                                self.error_handler.log_error(f"Failed to parse Gemini text as JSON: {e}")
                                self.error_handler.log_error(f"Raw text: {text_response}")
                                return None
                        else:
                            self.error_handler.log_error("Gemini returned empty text response")
                            return None
                    else:
                        self.error_handler.log_error("Gemini response missing candidates")
                        return None
                else:
                    error_text = await response.text()
                    self.error_handler.log_error(f"Gemini API error {response.status}: {error_text}")
                    return None
                    
        except json.JSONDecodeError as e:
            self.error_handler.log_error(f"Failed to parse Gemini response as JSON: {e}")
            return None
        except Exception as e:
            self.error_handler.handle_exception(e, "calling Gemini API")
            return None
    
    def _parse_gemini_response(self, response: Dict, original_content: str, 
                              source: str) -> Optional[TradeSignal]:
        """Parse Gemini API response into TradeSignal"""
        try:
            if "error" in response:
                self.error_handler.log_warning(f"Gemini extraction failed: {response['error']}")
                return None
            
            required_fields = ['symbol', 'direction', 'entry_price', 'stop_loss', 'take_profits']
            for field in required_fields:
                if field not in response:
                    self.error_handler.log_error(f"Missing required field: {field}")
                    return None
            
            symbol = response['symbol'].upper()
            if not symbol.endswith('USDT'):
                symbol += 'USDT'
            
            direction = response['direction'].lower()
            if direction not in ['long', 'short']:
                self.error_handler.log_error(f"Invalid direction: {direction}")
                return None
            
            entry_price = float(response['entry_price'])
            stop_loss = float(response['stop_loss'])
            take_profits = [float(tp) for tp in response['take_profits']]
            
            if not take_profits:
                self.error_handler.log_error("No take profit levels found")
                return None
            
            leverage = response.get('leverage')
            if leverage is not None:
                leverage = int(leverage)
            
            trade_type = response.get('trade_type', 'futures').lower()
            if trade_type not in ['futures', 'spot']:
                trade_type = 'futures'
            
            confidence = float(response.get('confidence', 0.0))
            
            if not self._validate_signal_logic(direction, entry_price, stop_loss, take_profits):
                return None
            
            return TradeSignal(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profits=take_profits,
                leverage=leverage,
                trade_type=trade_type,
                confidence=confidence,
                source=source,
                raw_content=original_content[:500]
            )
            
        except (ValueError, TypeError, KeyError) as e:
            self.error_handler.log_error(f"Failed to parse signal data: {e}")
            return None
    
    def _validate_signal_logic(self, direction: str, entry: float, sl: float, 
                              tps: List[float]) -> bool:
        """Validate signal logic consistency"""
        try:
            if direction == 'long':
                if sl >= entry:
                    self.error_handler.log_error("Invalid LONG: stop loss must be below entry")
                    return False
                for tp in tps:
                    if tp <= entry:
                        self.error_handler.log_error("Invalid LONG: take profits must be above entry")
                        return False
            
            elif direction == 'short':
                if sl <= entry:
                    self.error_handler.log_error("Invalid SHORT: stop loss must be above entry")
                    return False
                for tp in tps:
                    if tp >= entry:
                        self.error_handler.log_error("Invalid SHORT: take profits must be below entry")
                        return False
            
            return True
            
        except Exception as e:
            self.error_handler.log_error(f"Error validating signal logic: {e}")
            return False
    
    def get_filtered_take_profits(self, take_profits: List[float]) -> List[float]:
        """Get filtered take profits (1st, 3rd, 5th levels)"""
        filtered_tps = []
        indices = [0, 2, 4]  # 1st, 3rd, 5th (0-indexed)
        
        for i in indices:
            if i < len(take_profits):
                filtered_tps.append(take_profits[i])
        
        return filtered_tps
    
    def _validate_content(self, content: str, images: List[bytes] = None) -> bool:
        """Validate content before processing"""
        # Check for minimum content length
        if not content or len(content.strip()) < 10:
            if not images:
                self.error_handler.log_warning("Content too short and no images provided")
                return False
        
        # Check for trading keywords
        trading_keywords = [
            'buy', 'sell', 'long', 'short', 'entry', 'exit', 'tp', 'sl', 
            'take profit', 'stop loss', 'leverage', 'usdt', 'btc', 'eth',
            'target', 'price', 'position'
        ]
        
        content_lower = content.lower()
        has_trading_keywords = any(keyword in content_lower for keyword in trading_keywords)
        
        if not has_trading_keywords and not images:
            self.error_handler.log_warning("No trading keywords found in content")
            return False
        
        return True
    
    def _enhanced_signal_validation(self, signal: TradeSignal, original_content: str) -> bool:
        """Enhanced signal validation with additional checks"""
        try:
            # Basic validation
            if not self._validate_signal_logic(signal.direction, signal.entry_price, 
                                             signal.stop_loss, signal.take_profits):
                return False
            
            # Price reasonableness check
            if signal.entry_price <= 0 or signal.stop_loss <= 0:
                self.error_handler.log_error("Invalid prices: must be positive")
                return False
            
            # Risk/reward ratio check
            risk = abs(signal.entry_price - signal.stop_loss)
            reward = abs(signal.take_profits[0] - signal.entry_price) if signal.take_profits else 0
            
            if reward == 0:
                self.error_handler.log_error("No valid take profit levels")
                return False
            
            risk_reward_ratio = risk / reward
            if risk_reward_ratio > 5.0:  # Risk more than 5x the reward
                self.error_handler.log_warning(f"Poor risk/reward ratio: {risk_reward_ratio:.2f}:1")
                return False
            
            # Stop loss distance check (shouldn't be more than 20% from entry)
            sl_distance_pct = abs(signal.stop_loss - signal.entry_price) / signal.entry_price * 100
            if sl_distance_pct > 20:
                self.error_handler.log_warning(f"Stop loss too far: {sl_distance_pct:.1f}% from entry")
                return False
            
            # Confidence threshold
            if signal.confidence < 0.3:
                self.error_handler.log_warning(f"Low confidence signal: {signal.confidence:.2f}")
                return False
            
            # Leverage check
            if signal.leverage and signal.leverage > 100:
                self.error_handler.log_warning(f"Excessive leverage: {signal.leverage}x")
                return False
            
            return True
            
        except Exception as e:
            self.error_handler.log_error(f"Error in enhanced validation: {e}")
            return False


class RateLimiter:
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Acquire rate limit slot"""
        async with self._lock:
            now = datetime.now()
            cutoff = now - timedelta(seconds=self.time_window)
            
            self.requests = [req_time for req_time in self.requests if req_time > cutoff]
            
            if len(self.requests) >= self.max_requests:
                wait_time = (self.requests[0] + timedelta(seconds=self.time_window) - now).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    return await self.acquire()
            
            self.requests.append(now)