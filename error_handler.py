"""
Error Handler - Centralized logging and exception routing system
Routes logs to terminal with emoji prioritization and sends critical errors to Telegram
"""

import asyncio
import logging
import sys
import traceback
from datetime import datetime
from typing import Optional, Callable, Any
from enum import Enum


class LogLevel(Enum):
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"
    INFO = "ℹ️"
    DEBUG = "🔍"


class ErrorHandler:
    def __init__(self):
        self.telegram_callback: Optional[Callable] = None
        self.logger = self._setup_logger()
        
    def _setup_logger(self) -> logging.Logger:
        """Setup structured logging with emoji prioritization"""
        logger = logging.getLogger("trading_bot")
        logger.setLevel(logging.DEBUG)
        
        if logger.handlers:
            logger.handlers.clear()
            
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def set_telegram_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for sending critical errors to Telegram"""
        self.telegram_callback = callback
    
    def log_success(self, message: str, notify_telegram: bool = False) -> None:
        """Log success message"""
        formatted_msg = f"{LogLevel.SUCCESS.value} {message}"
        self.logger.info(formatted_msg)
        
        if notify_telegram and self.telegram_callback:
            asyncio.create_task(self._send_to_telegram(formatted_msg))
    
    def log_warning(self, message: str, notify_telegram: bool = False) -> None:
        """Log warning message"""
        formatted_msg = f"{LogLevel.WARNING.value} {message}"
        self.logger.warning(formatted_msg)
        
        if notify_telegram and self.telegram_callback:
            asyncio.create_task(self._send_to_telegram(formatted_msg))
    
    def log_error(self, message: str, exception: Optional[Exception] = None, 
                  notify_telegram: bool = True) -> None:
        """Log error message with optional exception details"""
        formatted_msg = f"{LogLevel.ERROR.value} {message}"
        
        if exception:
            formatted_msg += f"\nException: {str(exception)}"
            self.logger.error(formatted_msg, exc_info=True)
        else:
            self.logger.error(formatted_msg)
        
        if notify_telegram and self.telegram_callback:
            asyncio.create_task(self._send_to_telegram(formatted_msg))
    
    def log_info(self, message: str, notify_telegram: bool = False) -> None:
        """Log info message"""
        formatted_msg = f"{LogLevel.INFO.value} {message}"
        self.logger.info(formatted_msg)
        
        if notify_telegram and self.telegram_callback:
            asyncio.create_task(self._send_to_telegram(formatted_msg))
    
    def log_debug(self, message: str) -> None:
        """Log debug message (terminal only)"""
        formatted_msg = f"{LogLevel.DEBUG.value} {message}"
        self.logger.debug(formatted_msg)
    
    async def _send_to_telegram(self, message: str) -> None:
        """Send message to Telegram with error handling"""
        if not self.telegram_callback:
            return
            
        try:
            if asyncio.iscoroutinefunction(self.telegram_callback):
                await self.telegram_callback(message)
            else:
                self.telegram_callback(message)
        except Exception as e:
            self.logger.error(f"Failed to send message to Telegram: {e}")
    
    def handle_exception(self, exception: Exception, context: str = "", 
                        notify_telegram: bool = True) -> None:
        """Handle exceptions with full context"""
        error_msg = f"Exception in {context}: {str(exception)}"
        
        if isinstance(exception, (ConnectionError, TimeoutError)):
            self.log_warning(f"Network issue in {context}: {exception}", notify_telegram)
        elif isinstance(exception, ValueError):
            self.log_error(f"Validation error in {context}: {exception}", notify_telegram=notify_telegram)
        else:
            self.log_error(error_msg, exception, notify_telegram)
    
    async def safe_execute(self, coro_func, context: str = "", 
                          retry_count: int = 0, max_retries: int = 5,
                          backoff_factor: float = 2.0, max_wait: float = 60.0) -> Any:
        """Execute async function with exponential backoff and error handling"""
        try:
            if asyncio.iscoroutinefunction(coro_func):
                return await coro_func()
            else:
                return coro_func()
                
        except Exception as e:
            # Determine if error is retryable
            is_retryable = self._is_retryable_error(e)
            
            if retry_count < max_retries and is_retryable:
                # Add jitter to prevent thundering herd
                import random
                jitter = random.uniform(0.1, 0.5)
                wait_time = min(backoff_factor ** retry_count + jitter, max_wait)
                
                self.log_warning(
                    f"Retry {retry_count + 1}/{max_retries} for {context} in {wait_time:.1f}s: {e}"
                )
                await asyncio.sleep(wait_time)
                return await self.safe_execute(coro_func, context, retry_count + 1, max_retries, backoff_factor, max_wait)
            else:
                if not is_retryable:
                    self.log_error(f"Non-retryable error in {context}: {e}")
                else:
                    self.log_error(f"Max retries exceeded for {context}: {e}")
                self.handle_exception(e, context)
                raise
    
    def _is_retryable_error(self, exception: Exception) -> bool:
        """Determine if an error should be retried"""
        retryable_errors = (
            ConnectionError,
            TimeoutError,
            OSError,
            asyncio.TimeoutError,
        )
        
        # Check for specific API errors that shouldn't be retried
        error_msg = str(exception).lower()
        non_retryable_keywords = [
            'invalid api key',
            'permission denied',
            'unauthorized',
            'forbidden',
            'bad request',
            'invalid symbol',
            'insufficient balance'
        ]
        
        if any(keyword in error_msg for keyword in non_retryable_keywords):
            return False
            
        return isinstance(exception, retryable_errors)
    
    def create_task_with_error_handling(self, coro, context: str = "") -> asyncio.Task:
        """Create async task with automatic error handling"""
        async def wrapped_coro():
            try:
                return await coro
            except Exception as e:
                self.handle_exception(e, context)
                raise
        
        return asyncio.create_task(wrapped_coro())
    
    def log_trade_event(self, event_type: str, symbol: str, details: str, 
                       is_success: bool = True) -> None:
        """Log trade-specific events with consistent formatting"""
        emoji = LogLevel.SUCCESS.value if is_success else LogLevel.ERROR.value
        message = f"{emoji} {event_type.upper()} | {symbol} | {details}"
        
        if is_success:
            self.log_success(message, notify_telegram=True)
        else:
            self.log_error(message, notify_telegram=True)
    
    def log_signal_received(self, source: str, symbol: str) -> None:
        """Log signal reception"""
        self.log_info(f"Signal received from {source} for {symbol}")
    
    def log_position_update(self, symbol: str, status: str, pnl: float = 0) -> None:
        """Log position updates"""
        pnl_text = f"PnL: {pnl:+.2f} USDT" if pnl != 0 else ""
        self.log_trade_event("POSITION", symbol, f"{status} {pnl_text}".strip())
    
    def log_config_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """Log configuration changes"""
        self.log_success(f"Config updated: {key} {old_value} → {new_value}")
    
    def log_startup(self, component: str) -> None:
        """Log component startup"""
        self.log_success(f"{component} initialized")
    
    def log_shutdown(self, component: str) -> None:
        """Log component shutdown"""
        self.log_info(f"{component} shutting down")


_error_handler = ErrorHandler()


def get_error_handler() -> ErrorHandler:
    """Get global error handler instance"""
    return _error_handler