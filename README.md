# Discord-to-Binance Trading Bot

A production-ready, high-performance trading bot that listens to Discord signals, processes them with AI, and executes trades on Binance with comprehensive monitoring and Telegram control.

## 🚀 Features

### ✅ Core Architecture
- **Fully async** with single event loop design
- **Modular architecture** with complete separation of concerns
- **Hot-reloading** configuration system
- **Performance monitoring** with metrics and alerts
- **Graceful shutdown** handling

### 🤖 AI-Powered Signal Processing
- **Gemini 1.5 Flash** integration for text/image signal extraction
- **Smart trade type detection** (futures vs spot)
- **Advanced signal validation** with risk/reward analysis
- **Signal caching** for improved performance
- **Rate limiting** (60 requests/minute)

### 📈 Advanced Trading Features
- **Never uses market orders** for entry (limit orders only)
- **Smart TP strategy** using 1st, 3rd, 5th levels with price adjustment
- **Configurable position sizing** for futures and spot
- **Leverage management** (config override or signal-based)
- **Duplicate position prevention**
- **Risk management** with daily loss limits

### 🛡️ Risk Management
- Configurable max open positions (futures/spot separately)
- Daily loss limits with automatic trading halt
- Symbol blacklisting
- Position size limits
- Stop loss distance validation
- Risk/reward ratio checks

### 📱 Telegram Interface
- **Complete bot control** via commands
- **Real-time alerts** for all trading events
- **Detailed notifications** with raw Discord content
- **Performance metrics** and system health
- **Inline keyboards** for easy interaction
- **Authorized users only** with admin ID verification

### 🔗 Exchange Support
- **Binance Testnet** (futures only)
- **Binance Live** (futures + spot)
- **Position reconciliation** on startup
- **WebSocket integration** ready
- **Automatic leverage setting**

### 📊 Monitoring & Analytics
- **Position tracking** with PnL monitoring
- **Trade statistics** (win rate, avg hold time, etc.)
- **Performance metrics** (CPU, memory, response times)
- **Error tracking** with emoji-prioritized logs
- **System health monitoring**

## 🛠️ Installation

### Prerequisites
- Python 3.11+
- Git

### 1. Clone Repository
```bash
git clone <repository-url>
cd discord-binance-bot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

### 4. Configure Settings
Edit `config.json` for your trading preferences:

```json
{
  "mode": "demo",
  "leverage": 0,
  "max_futures_trade": 2,
  "max_spot_trade": 1,
  "max_daily_loss": 300,
  "futures_position_size": 150,
  "spot_position_size": 100,
  "blacklist": ["PEPEUSDT"],
  "discord_channels": ["signals-1", "signals-2", "1234567890123456789"],
  "is_trading_enabled": true
}
```

## 🔑 API Keys Setup

### Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create new application → Bot
3. Copy token to `DISCORD_TOKEN` in `.env`
4. Enable Message Content Intent

### Telegram Bot Token
1. Message [@BotFather](https://t.me/botfather)
2. Create new bot with `/newbot`
3. Copy token to `TELEGRAM_TOKEN` in `.env`
4. Get your user ID from [@userinfobot](https://t.me/userinfobot)
5. Set `ADMIN_ID` in `.env`

### Binance API Keys
1. **Testnet** (for demo mode):
   - Go to [Binance Testnet](https://testnet.binance.vision/)
   - Create API key
   - Set `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_SECRET`

2. **Live** (for production):
   - Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
   - Create API key with futures and spot trading permissions
   - Set `BINANCE_API_KEY` and `BINANCE_SECRET`

### Gemini API Key
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create API key
3. Set `GEMINI_API_KEY` in `.env`

## 🚀 Running the Bot

### Start the Bot
```bash
python main.py
```

### Running with Docker (Optional)
```bash
# Build image
docker build -t trading-bot .

# Run container
docker run -d --name trading-bot \
  --env-file .env \
  -v $(pwd)/config.json:/app/config.json \
  -v $(pwd)/data:/app/data \
  trading-bot
```

## 📱 Telegram Commands

### Basic Commands
- `/start` - Enable trading
- `/stop` - Disable trading  
- `/status` - Show bot status
- `/positions` - View active positions
- `/stats` - Trading statistics
- `/health` - System health check
- `/performance` - Performance metrics
- `/cancelall` - Cancel all open orders
- `/menu` - Show interactive menu

### Configuration Commands
- `/set_leverage <value>` - Set leverage (0 = use signal leverage)
- `/set_futures_size <amount>` - Set futures position size in USD
- `/set_spot_size <amount>` - Set spot position size in USD
- `/max_futures <count>` - Max concurrent futures positions
- `/max_spot <count>` - Max concurrent spot positions

### Examples
```
/set_leverage 10
/set_futures_size 200
/max_futures 3
```

## 📊 Discord Channel Configuration

The bot supports multiple ways to specify Discord channels:

### Channel Names
```json
"discord_channels": ["signals", "crypto-alerts"]
```

### Channel IDs (Recommended)
```json
"discord_channels": ["1234567890123456789", "9876543210987654321"]
```

### Mixed Format
```json
"discord_channels": ["signals", "1234567890123456789", "<#1234567890123456789>"]
```

To get channel IDs:
1. Enable Developer Mode in Discord
2. Right-click channel → Copy ID

## 🧪 Testing

Run the test suite:
```bash
pytest tests/ -v
```

Run specific tests:
```bash
pytest tests/test_signal_parser.py -v
```

## 📁 Project Structure

```
├── main.py                 # Main application orchestrator
├── config_manager.py       # Hot-reloading configuration system
├── error_handler.py        # Centralized logging and error handling
├── performance_monitor.py  # Performance metrics and monitoring
├── exchange_connector.py   # Binance integration with ccxt
├── signal_parser.py        # Gemini AI signal extraction
├── trade_manager.py        # Trade validation and execution
├── trade_tracker.py        # Position monitoring and PnL tracking
├── discord_listener.py     # Discord WebSocket listener
├── telegram_controller.py  # Telegram bot interface
├── tests/                  # Unit tests
│   └── test_signal_parser.py
├── config.json             # Live-editable configuration
├── .env.example            # Environment variables template
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## 📈 Performance Monitoring

The bot includes comprehensive performance monitoring:

### System Metrics
- CPU and memory usage
- File handle and network connection counts
- Operation timing and success rates
- Error tracking and categorization

### Trading Metrics
- Signal processing time (target: <1s)
- Config reload time (target: <100ms)
- API response times
- Success rates by operation type

### Access Metrics
Use `/performance` command in Telegram or check logs for real-time metrics.

## 🔧 Configuration Options

### Trading Settings
- `mode`: "demo" or "live"
- `leverage`: Global leverage (0 = use signal leverage)
- `max_futures_trade`: Max concurrent futures positions
- `max_spot_trade`: Max concurrent spot positions
- `max_daily_loss`: Daily loss limit in USDT
- `futures_position_size`: Position size for futures in USD
- `spot_position_size`: Position size for spot in USD

### Risk Management
- `blacklist`: Array of symbols to ignore
- `min_confidence_threshold`: Minimum AI confidence (0.0-1.0)
- `max_risk_reward_ratio`: Maximum risk/reward ratio

### Discord Settings
- `discord_channels`: Array of channel names/IDs to monitor

## 🚨 Important Notes

### Security
- Never commit API keys to version control
- Use testnet for development and testing
- Verify all signals before live trading
- Monitor positions regularly

### Risk Warning
- Trading cryptocurrencies involves substantial risk
- Past performance doesn't guarantee future results
- Never trade with funds you can't afford to lose
- This bot is for educational/research purposes

### Performance
- Recommended: VPS with 2GB+ RAM
- Stable internet connection required
- Monitor system resources regularly

## 🐛 Troubleshooting

### Common Issues

1. **"No matching channels found"**
   - Check channel IDs in config.json
   - Ensure bot has access to channels
   - Use `/performance` to see available channels

2. **"Detected untracked position"**
   - This is normal for positions from other bots
   - Warning appears only once per position

3. **API connection errors**
   - Verify API keys in .env
   - Check network connectivity
   - Ensure API permissions are correct

4. **Signal parsing failures**
   - Check Gemini API key
   - Monitor rate limits (60/min)
   - Verify content has trading keywords

### Logs
Check terminal output for detailed error messages with emoji indicators:
- ✅ Success operations
- ⚠️ Warnings  
- ❌ Errors
- ℹ️ Information
- 🔍 Debug messages

## 📞 Support

For issues and questions:
1. Check the troubleshooting section
2. Review logs for error messages
3. Test with minimal configuration
4. Use testnet for development

## 📄 License

This project is for educational purposes. Please ensure compliance with your local laws and exchange terms of service.

---

**⚠️ Disclaimer**: This software is provided as-is without any guarantees. Trading involves significant financial risk. The authors are not responsible for any financial losses.