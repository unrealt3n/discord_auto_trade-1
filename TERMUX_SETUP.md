# Termux Setup Guide

This Discord auto-trading bot is now fully compatible with Android Termux. The bot automatically detects when incompatible libraries are not available and falls back to HTTP-only implementations.

## Quick Setup for Termux

### 1. Install Python and Git
```bash
pkg update && pkg upgrade
pkg install python git
```

### 2. Clone the Repository
```bash
git clone <your-repo-url>
cd discord_auto_trade
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment
```bash
cp .env.example .env
# Edit .env with your credentials
nano .env
```

### 5. Run the Bot
```bash
python main.py
```

The bot will automatically use HTTP-compatible components when running on Termux.

## What's Different on Termux

### Automatically Replaced Libraries:
- **discord.py** → HTTP requests to Discord API
- **ccxt** → HTTP requests to exchange APIs  
- **psutil** → Lightweight system info module
- **python-telegram-bot** → Direct HTTP calls (if used)

### Features That Work on Termux:
✅ Discord message monitoring via HTTP polling  
✅ Exchange trading via HTTP API calls  
✅ Signal parsing with Gemini AI  
✅ Position tracking and management  
✅ Performance monitoring  
✅ Configuration management  
✅ Error handling and logging  

### Limitations on Termux:
⚠️ Real-time Discord events (uses polling instead)  
⚠️ WebSocket connections (uses HTTP requests)  
⚠️ Some advanced system monitoring features  

## Testing Termux Compatibility

Run the compatibility test:
```bash
python test_http_compatibility.py
```

## Troubleshooting

### Common Issues:
1. **Import errors**: The bot will automatically fall back to HTTP implementations
2. **Performance**: HTTP polling may be slightly slower than WebSocket connections
3. **Rate limits**: Be aware of Discord/Exchange API rate limits with HTTP requests

### Direct HTTP Mode:
If you want to force HTTP mode even when other libraries are available:
```bash
python main_http.py
```

## Configuration

The bot uses the same configuration files and environment variables as the full version. See `.env.example` for required settings.

All trading features work identically to the full version - only the underlying communication methods are different.