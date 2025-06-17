# GitHub Actions Setup Guide

Complete guide to run your Discord trading bot **FREE** on GitHub Actions 24/7.

## 🎯 Why GitHub Actions?

- ✅ **FREE**: 2000 minutes/month for public repositories
- ✅ **RELIABLE**: Runs on GitHub's infrastructure
- ✅ **24/7 OPERATION**: Automatic restarts every 6 hours
- ✅ **NO TERMUX ISSUES**: Pure cloud environment
- ✅ **EASY UPDATES**: Just push code changes

## 🚀 Step-by-Step Setup

### 1. Fork the Repository

1. Go to your bot's GitHub repository
2. Click **"Fork"** button in the top right
3. This creates your own copy of the bot

### 2. Configure Repository Secrets

1. Go to your forked repository
2. Click **Settings** tab
3. Click **Secrets and variables** → **Actions**
4. Click **New repository secret** for each:

#### Required Secrets:
```
Name: DISCORD_TOKEN
Value: YOUR_ACTUAL_DISCORD_BOT_TOKEN

Name: BINANCE_TESTNET_API_KEY  
Value: YOUR_TESTNET_API_KEY

Name: BINANCE_TESTNET_API_SECRET
Value: YOUR_TESTNET_API_SECRET

Name: MONITORED_CHANNEL_IDS
Value: 123456789,987654321,555444333

Name: GEMINI_API_KEY
Value: YOUR_GEMINI_API_KEY
```

#### Optional Secrets:
```
Name: BINANCE_API_KEY
Value: YOUR_LIVE_API_KEY

Name: BINANCE_API_SECRET  
Value: YOUR_LIVE_API_SECRET

Name: DISCORD_WEBHOOK_URL
Value: https://discord.com/api/webhooks/your_webhook_url
```

### 3. Enable GitHub Actions

1. Go to **Actions** tab in your repository
2. Click **"I understand my workflows, enable them"**
3. GitHub Actions are now enabled!

### 4. Start the Bot

**Option A: Push a change**
1. Edit any file (like README.md)
2. Commit and push the change
3. Bot starts automatically!

**Option B: Manual trigger**
1. Go to **Actions** tab
2. Click **"Discord Trading Bot"** workflow
3. Click **"Run workflow"** button
4. Click green **"Run workflow"** button

### 5. Monitor the Bot

1. Go to **Actions** tab to see running workflows
2. Click on a running workflow to see live logs
3. Bot will restart every 6 hours automatically

## 🔧 Configuration

### Environment File
The workflow creates a `.env` file from your secrets:
```bash
DISCORD_TOKEN=your_token
BINANCE_TESTNET_API_KEY=your_key
# ... other secrets
```

### Bot Configuration
Make sure your `config.json` is properly configured:
```json
{
  "mode": "demo",
  "is_trading_enabled": true,
  "authorized_users": ["your_discord_user_id"],
  "discord_channels": ["channel_id_1", "channel_id_2"]
}
```

## 📊 Workflow Features

### Automatic Restart System
```yaml
schedule:
  - cron: '0 */6 * * *'  # Every 6 hours
```
- Bot runs for 6 hours maximum
- Automatically restarts every 6 hours
- Provides continuous 24/7 operation

### Error Handling
- Uploads logs on failures
- Continues running even with minor errors
- Sends status notifications to Discord

### Multi-Python Testing
- Tests on Python 3.9, 3.10, 3.11
- Ensures compatibility across versions
- Validates all imports before running

## 🎛️ Bot Control

### Via Discord DMs
Send these commands to your bot:
```
!start    - Start trading
!stop     - Stop trading  
!status   - Check bot status
!health   - System health check
```

### Via GitHub Actions
- **Stop Bot**: Disable the workflow in Actions tab
- **Restart Bot**: Re-enable workflow or push a change
- **View Logs**: Click on workflow runs in Actions tab

## 📈 Usage Limits

### GitHub Actions Free Tier:
- **2000 minutes/month** for public repositories
- **500 MB storage** for artifacts/logs
- **Unlimited repositories** and workflows

### Calculation:
- Bot runs **24/7** = 720 hours/month = 43,200 minutes
- Free tier = 2000 minutes
- **You get ~3.4 days** of continuous operation per month

### Solutions for More Usage:
1. **Make repository public** (get 2000 free minutes)
2. **Use multiple GitHub accounts** with different repos
3. **Upgrade to Pro** ($4/month for 3000 minutes)
4. **Combine with other platforms** (Heroku, Railway, etc.)

## 🔍 Troubleshooting

### Common Issues:

**1. Workflow doesn't start**
- Check if GitHub Actions are enabled
- Verify you pushed to `main` branch
- Check workflow file syntax

**2. Bot fails to start**
- Verify all required secrets are set
- Check secret names match exactly
- View workflow logs for specific errors

**3. Import errors**
- Make sure `requirements.txt` is correct
- Check Python version compatibility
- Verify all files are in repository

**4. API errors**
- Test API keys work outside GitHub
- Check API key permissions
- Verify testnet vs live mode settings

### Debugging:

**View Logs:**
1. Go to Actions tab
2. Click on failed workflow
3. Click on failed job
4. Expand steps to see detailed logs

**Test Locally:**
```bash
python test_http_compatibility.py
```

**Manual Verification:**
```bash
python -c "
from main import TradingBotHTTP
print('✅ Bot can be imported')
"
```

## 🚨 Security Best Practices

### Repository Settings:
- ✅ Keep repository **private** if using live API keys
- ✅ Never commit `.env` files with real credentials
- ✅ Use testnet for public repositories
- ✅ Regularly rotate API keys

### Secret Management:
- ✅ Use descriptive secret names
- ✅ Store only necessary secrets
- ✅ Regularly audit secret access
- ✅ Remove unused secrets

### Access Control:
- ✅ Limit repository collaborators
- ✅ Use branch protection rules
- ✅ Require pull request reviews
- ✅ Enable two-factor authentication

## 🎉 Success Indicators

Your bot is running successfully when you see:

**In GitHub Actions logs:**
```
✅ Discord HTTP client logged in as YourBot#1234
✅ Exchange connection verified
✅ All components initialized successfully!
🚀 Trading Bot started successfully!
📡 Monitoring Discord channels for signals...
```

**In Discord:**
- Bot shows as online
- Responds to DM commands
- Sends signal notifications

**Monitoring:**
- Check Actions tab shows green checkmarks
- Workflow runs every 6 hours
- No error notifications

## 💡 Pro Tips

1. **Test First**: Always test with testnet before live trading
2. **Monitor Closely**: Watch first few hours of operation
3. **Small Positions**: Start with small position sizes
4. **Multiple Accounts**: Use different GitHub accounts for redundancy
5. **Backup Strategy**: Have Termux setup as backup option

## 🆘 Support

If you encounter issues:

1. **Check the logs** in GitHub Actions
2. **Run compatibility test** locally
3. **Verify configuration** files
4. **Test API keys** independently
5. **Join Discord** for community support

---

**🎯 Result: Your bot runs 24/7 on GitHub's servers for FREE!**

No more Termux compilation issues, battery drain, or phone dependency. Your trading bot operates reliably in the cloud while you sleep! 🚀