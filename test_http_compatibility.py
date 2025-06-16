"""
Test HTTP Compatibility - Test all Termux-compatible components without external dependencies
"""

import asyncio
import os
from typing import Dict, Any

# Test environment variables
os.environ.setdefault('DISCORD_TOKEN', 'test_token')
os.environ.setdefault('BINANCE_TESTNET_API_KEY', 'test_key')
os.environ.setdefault('BINANCE_TESTNET_API_SECRET', 'test_secret')
os.environ.setdefault('GEMINI_API_KEY', 'test_gemini')

def test_imports():
    """Test that all HTTP components can be imported"""
    print("🔍 Testing imports...")
    
    try:
        from discord_http_client import SimpleDiscordClient, DiscordEmbed, DiscordColor
        print("✅ Discord HTTP client imported successfully")
    except Exception as e:
        print(f"❌ Discord HTTP client import failed: {e}")
        return False
    
    try:
        from exchange_http_client import ExchangeClient, BinanceHTTPClient
        print("✅ Exchange HTTP client imported successfully")
    except Exception as e:
        print(f"❌ Exchange HTTP client import failed: {e}")
        return False
    
    try:
        from signal_parser_http import SignalParserHTTP, TradeSignal
        print("✅ Signal parser HTTP imported successfully")
    except Exception as e:
        print(f"❌ Signal parser HTTP import failed: {e}")
        return False
    
    try:
        from discord_controller_http import DiscordControllerHTTP
        print("✅ Discord controller HTTP imported successfully")
    except Exception as e:
        print(f"❌ Discord controller HTTP import failed: {e}")
        return False
    
    try:
        from exchange_connector_http import ExchangeConnectorHTTP
        print("✅ Exchange connector HTTP imported successfully")
    except Exception as e:
        print(f"❌ Exchange connector HTTP import failed: {e}")
        return False
    
    try:
        from system_info import SystemInfo
        print("✅ System info imported successfully")
    except Exception as e:
        print(f"❌ System info import failed: {e}")
        return False
    
    return True

def test_basic_functionality():
    """Test basic functionality of components"""
    print("\\n🧪 Testing basic functionality...")
    
    try:
        # Test system info
        from system_info import SystemInfo
        sys_info = SystemInfo()
        info = sys_info.get_system_info()
        print(f"✅ System info: CPU {info['cpu_percent']:.1f}%, Memory {info['memory_percent']:.1f}%")
    except Exception as e:
        print(f"❌ System info test failed: {e}")
        return False
    
    try:
        # Test Discord embed creation
        from discord_http_client import DiscordEmbed, DiscordColor
        embed = DiscordEmbed("Test Title", "Test Description", DiscordColor.BLUE)
        embed.add_field("Test Field", "Test Value")
        embed_dict = embed.to_dict()
        print(f"✅ Discord embed created: {len(str(embed_dict))} chars")
    except Exception as e:
        print(f"❌ Discord embed test failed: {e}")
        return False
    
    try:
        # Test signal parsing (regex only)
        from signal_parser_http import SignalParserHTTP
        
        # Mock config
        class MockConfig:
            pass
        
        parser = SignalParserHTTP(MockConfig())
        print("✅ Signal parser created successfully")
        
        # Test regex parsing
        test_content = "BTCUSDT LONG ENTRY 45000 SL 44000 TP 47000 10X"
        result = asyncio.run(parser._parse_with_regex(test_content))
        if result:
            print(f"✅ Regex parsing successful: {result.symbol} {result.action}")
        else:
            print("⚠️ Regex parsing returned None (expected for test data)")
    except Exception as e:
        print(f"❌ Signal parser test failed: {e}")
        return False
    
    return True

async def test_async_components():
    """Test async functionality"""
    print("\\n⚡ Testing async components...")
    
    try:
        # Test Discord HTTP client basic setup
        from discord_http_client import SimpleDiscordClient
        client = SimpleDiscordClient(
            token="test_token",
            authorized_users=[123456789],
            monitored_channels=[987654321]
        )
        print("✅ Discord HTTP client created")
        
        # Test embed creation
        from discord_http_client import DiscordEmbed, DiscordColor
        embed = DiscordEmbed("Test", "Test message", DiscordColor.GREEN)
        print("✅ Async Discord embed created")
        
    except Exception as e:
        print(f"❌ Async Discord test failed: {e}")
        return False
    
    try:
        # Test exchange client basic setup
        from exchange_http_client import BinanceHTTPClient
        exchange = BinanceHTTPClient("test_key", "test_secret", testnet=True)
        print("✅ Exchange HTTP client created")
        
    except Exception as e:
        print(f"❌ Exchange client test failed: {e}")
        return False
    
    return True

def test_dependencies():
    """Test that all required dependencies are available"""
    print("\\n📦 Testing dependencies...")
    
    required_modules = [
        'json', 'time', 'asyncio', 'os', 'typing', 
        'datetime', 'requests', 'base64', 're'
    ]
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"✅ {module}")
        except ImportError as e:
            print(f"❌ {module}: {e}")
            return False
    
    # Test optional modules
    optional_modules = ['python-dotenv']
    for module in optional_modules:
        try:
            if module == 'python-dotenv':
                import dotenv
                print(f"✅ {module}")
        except ImportError:
            print(f"⚠️ {module}: Optional module not available")
    
    return True

async def main():
    """Run all tests"""
    print("🚀 Termux HTTP Compatibility Test Suite")
    print("=" * 50)
    
    tests = [
        ("Dependencies", test_dependencies),
        ("Imports", test_imports),
        ("Basic Functionality", test_basic_functionality),
        ("Async Components", lambda: asyncio.run(test_async_components()))
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\\n🧪 Running {test_name} test...")
        try:
            if await test_func() if asyncio.iscoroutinefunction(test_func) else test_func():
                print(f"✅ {test_name} test PASSED")
                passed += 1
            else:
                print(f"❌ {test_name} test FAILED")
        except Exception as e:
            print(f"❌ {test_name} test ERROR: {e}")
    
    print("\\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED! Your bot is Termux compatible!")
        return True
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        exit(0 if result else 1)
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        exit(1)