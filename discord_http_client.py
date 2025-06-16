"""
Pure HTTP Discord Client - Termux compatible replacement for discord.py
Uses only requests library to interact with Discord REST API
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Callable, Any
import requests
from datetime import datetime


class DiscordColor:
    """Discord color constants"""
    DEFAULT = 0x000000
    BLUE = 0x3498db
    GREEN = 0x2ecc71
    RED = 0xe74c3c
    ORANGE = 0xe67e22
    PURPLE = 0x9b59b6
    GOLD = 0xf1c40f


class DiscordEmbed:
    """Simple Discord embed representation"""
    def __init__(self, title: str = "", description: str = "", color: int = DiscordColor.DEFAULT):
        self.title = title
        self.description = description
        self.color = color
        self.fields = []
        self.timestamp = datetime.utcnow().isoformat()
    
    def add_field(self, name: str, value: str, inline: bool = True):
        """Add field to embed"""
        self.fields.append({
            "name": name,
            "value": value,
            "inline": inline
        })
    
    def to_dict(self) -> Dict:
        """Convert embed to dictionary for API"""
        embed_dict = {
            "title": self.title,
            "description": self.description,
            "color": self.color,
            "timestamp": self.timestamp
        }
        if self.fields:
            embed_dict["fields"] = self.fields
        return embed_dict


class DiscordUser:
    """Discord user representation"""
    def __init__(self, user_data: Dict):
        self.id = int(user_data["id"])
        self.username = user_data["username"]
        self.discriminator = user_data.get("discriminator", "0")
        self.name = self.username  # For compatibility
        
    def __str__(self):
        if self.discriminator != "0":
            return f"{self.username}#{self.discriminator}"
        return self.username


class DiscordChannel:
    """Discord channel representation"""
    def __init__(self, channel_data: Dict):
        self.id = int(channel_data["id"])
        self.name = channel_data.get("name", "")
        self.type = channel_data.get("type", 0)
        
    def __str__(self):
        return f"#{self.name}" if self.name else f"Channel {self.id}"


class DiscordGuild:
    """Discord guild/server representation"""
    def __init__(self, guild_data: Dict):
        self.id = int(guild_data["id"])
        self.name = guild_data["name"]
        self.member_count = guild_data.get("approximate_member_count", 0)


class DiscordMessage:
    """Discord message representation"""
    def __init__(self, message_data: Dict, client):
        self.id = int(message_data["id"])
        self.content = message_data["content"]
        self.channel_id = int(message_data["channel_id"])
        self.author = DiscordUser(message_data["author"])
        self.attachments = message_data.get("attachments", [])
        self.guild_id = message_data.get("guild_id")
        self._client = client
        
        # Mock channel and guild objects
        self.channel = type('Channel', (), {'id': self.channel_id})()
        if self.guild_id:
            self.guild = type('Guild', (), {'id': int(self.guild_id), 'name': 'Unknown'})()
        else:
            self.guild = None


class SimpleDiscordClient:
    """Pure HTTP Discord client compatible with Termux"""
    
    def __init__(self, token: str, authorized_users: List[int], monitored_channels: List[int]):
        self.token = token
        self.authorized_users = authorized_users
        self.monitored_channels = monitored_channels
        self.base_url = "https://discord.com/api/v10"
        self.headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 1.0)"
        }
        
        # Bot info
        self.user = None
        self.guilds = []
        self.channels = {}
        
        # Callbacks
        self.signal_callback: Optional[Callable] = None
        self.commands = {}
        
        # Gateway simulation
        self._running = False
        self._last_message_id = {}  # Per channel
        
    async def initialize(self):
        """Initialize the Discord client"""
        try:
            # Get bot user info
            response = requests.get(f"{self.base_url}/users/@me", headers=self.headers)
            if response.status_code == 200:
                user_data = response.json()
                self.user = DiscordUser(user_data)
                print(f"✅ Discord HTTP client logged in as {self.user}")
            else:
                raise Exception(f"Failed to get bot user info: {response.status_code}")
            
            # Get guilds
            await self._fetch_guilds()
            
            # Get channel info for monitored channels
            await self._fetch_channel_info()
            
            # Start message polling
            self._running = True
            asyncio.create_task(self._poll_messages())
            
        except Exception as e:
            print(f"❌ Discord HTTP client initialization failed: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the client"""
        self._running = False
        print("✅ Discord HTTP client shutdown")
    
    async def _fetch_guilds(self):
        """Fetch guild information"""
        try:
            response = requests.get(f"{self.base_url}/users/@me/guilds", headers=self.headers)
            if response.status_code == 200:
                guilds_data = response.json()
                self.guilds = [DiscordGuild(guild) for guild in guilds_data]
                print(f"✅ Fetched {len(self.guilds)} guilds")
            else:
                print(f"⚠️ Failed to fetch guilds: {response.status_code}")
        except Exception as e:
            print(f"❌ Error fetching guilds: {e}")
    
    async def _fetch_channel_info(self):
        """Fetch information for monitored channels"""
        for channel_id in self.monitored_channels:
            try:
                response = requests.get(f"{self.base_url}/channels/{channel_id}", headers=self.headers)
                if response.status_code == 200:
                    channel_data = response.json()
                    self.channels[channel_id] = DiscordChannel(channel_data)
                    print(f"✅ Channel access confirmed: #{self.channels[channel_id].name} ({channel_id})")
                else:
                    print(f"❌ Cannot access channel {channel_id}: {response.status_code}")
            except Exception as e:
                print(f"❌ Error fetching channel {channel_id}: {e}")
    
    async def _poll_messages(self):
        """Poll messages from monitored channels"""
        print("📡 Starting message polling...")
        
        while self._running:
            try:
                for channel_id in self.monitored_channels:
                    await self._check_channel_messages(channel_id)
                
                # Poll every 5 seconds to avoid rate limits
                await asyncio.sleep(5)
                
            except Exception as e:
                print(f"❌ Error in message polling: {e}")
                await asyncio.sleep(10)  # Wait longer on error
    
    async def _check_channel_messages(self, channel_id: int):
        """Check for new messages in a channel"""
        try:
            params = {"limit": 10}
            if channel_id in self._last_message_id:
                params["after"] = self._last_message_id[channel_id]
            
            response = requests.get(
                f"{self.base_url}/channels/{channel_id}/messages",
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 200:
                messages = response.json()
                
                # Process messages in chronological order (oldest first)
                for message_data in reversed(messages):
                    message = DiscordMessage(message_data, self)
                    
                    # Skip bot's own messages
                    if message.author.id == self.user.id:
                        continue
                    
                    # Update last seen message ID
                    self._last_message_id[channel_id] = message.id
                    
                    # Process the message
                    await self._handle_message(message)
                    
            elif response.status_code == 429:  # Rate limited
                retry_after = response.json().get("retry_after", 5)
                print(f"⚠️ Rate limited, waiting {retry_after} seconds")
                await asyncio.sleep(retry_after)
            elif response.status_code != 200:
                print(f"⚠️ Error fetching messages from {channel_id}: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error checking messages in channel {channel_id}: {e}")
    
    async def _handle_message(self, message: DiscordMessage):
        """Handle incoming message"""
        print(f"📨 New message from {message.author} in {message.channel_id}")
        
        # Check if it's a DM or from monitored channel
        if message.channel_id in self.monitored_channels:
            print(f"🎯 Processing signal from monitored channel {message.channel_id}")
            await self._process_signal_message(message)
        
        # Process commands (simple prefix check)
        if message.content.startswith("!"):
            await self._process_command(message)
    
    async def _process_signal_message(self, message: DiscordMessage):
        """Process signal message from monitored channels"""
        try:
            if self.signal_callback:
                # Extract image URLs from attachments
                images = []
                for attachment in message.attachments:
                    if any(attachment["filename"].lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                        images.append(attachment["url"])
                
                # Get source info
                channel_name = self.channels.get(message.channel_id)
                source = f"#{channel_name.name}" if channel_name else f"Channel {message.channel_id}"
                
                # Forward to signal processor
                await self.signal_callback(message.content, images, source)
                
                # Send DM to authorized users
                await self._send_signal_dm(message, source, images)
                
        except Exception as e:
            print(f"❌ Error processing signal message: {e}")
    
    async def _send_signal_dm(self, message: DiscordMessage, source: str, images: List[str]):
        """Send signal as DM to authorized users"""
        for user_id in self.authorized_users:
            try:
                # Create DM channel
                dm_channel = await self._create_dm_channel(user_id)
                if not dm_channel:
                    continue
                
                # Create embed
                embed = DiscordEmbed(
                    title=f"📡 Signal from {source}",
                    description=f"**Original Message:**\\n{message.content[:1900]}{'...' if len(message.content) > 1900 else ''}",
                    color=DiscordColor.ORANGE
                )
                
                if images:
                    embed.add_field(name="Images", value=f"{len(images)} image(s) attached", inline=False)
                
                # Send embed
                await self._send_message(dm_channel, embed=embed)
                
                # Send images separately
                for image_url in images:
                    await self._send_message(dm_channel, content=image_url)
                
                print(f"✅ Signal DM sent to user {user_id}")
                
            except Exception as e:
                print(f"❌ Failed to send signal DM to user {user_id}: {e}")
    
    async def _process_command(self, message: DiscordMessage):
        """Process command message"""
        # Simple command parsing
        parts = message.content[1:].split()  # Remove ! prefix
        if not parts:
            return
            
        command = parts[0].lower()
        args = parts[1:]
        
        # Check authorization for commands
        if message.author.id not in self.authorized_users:
            await self._handle_unauthorized_access(message.author, "Command", message.content)
            return
        
        # Handle basic commands
        if command == "status":
            await self._handle_status_command(message)
        elif command == "menu":
            await self._handle_menu_command(message)
        else:
            # Forward to registered command handlers
            if command in self.commands:
                try:
                    await self.commands[command](message, args)
                except Exception as e:
                    print(f"❌ Error executing command {command}: {e}")
    
    async def _handle_status_command(self, message: DiscordMessage):
        """Handle status command"""
        try:
            # Create DM channel
            dm_channel = await self._create_dm_channel(message.author.id)
            if not dm_channel:
                return
            
            status_text = f"""📊 **Bot Status**
            
🤖 Bot: {self.user}
🏰 Servers: {len(self.guilds)}
📺 Monitored Channels: {len(self.monitored_channels)}
👤 Authorized Users: {len(self.authorized_users)}
⚡ Status: Online"""
            
            embed = DiscordEmbed("📊 Bot Status", status_text, DiscordColor.BLUE)
            await self._send_message(dm_channel, embed=embed)
            
        except Exception as e:
            print(f"❌ Error in status command: {e}")
    
    async def _handle_menu_command(self, message: DiscordMessage):
        """Handle menu command"""
        try:
            dm_channel = await self._create_dm_channel(message.author.id)
            if not dm_channel:
                return
            
            menu_text = """🤖 **Available Commands**
            
**Information:**
• `!status` - Show bot status
• `!menu` - Show this menu

**Note:** This is a lightweight Discord client.
Some advanced features may be limited."""
            
            embed = DiscordEmbed("🤖 Command Menu", menu_text, DiscordColor.BLUE)
            await self._send_message(dm_channel, embed=embed)
            
        except Exception as e:
            print(f"❌ Error in menu command: {e}")
    
    async def _handle_unauthorized_access(self, user: DiscordUser, location: str, content: str):
        """Handle unauthorized access attempt"""
        print(f"🚨 Unauthorized access attempt by {user} in {location}: {content[:100]}")
        
        # Send alert to authorized users
        for user_id in self.authorized_users:
            try:
                dm_channel = await self._create_dm_channel(user_id)
                if not dm_channel:
                    continue
                
                alert_text = f"""🚨 **Unauthorized Access Attempt**
                
👤 User: {user}
📍 Location: {location}
📝 Content: {content[:200]}"""
                
                embed = DiscordEmbed("🚨 Security Alert", alert_text, DiscordColor.RED)
                await self._send_message(dm_channel, embed=embed)
                
            except Exception as e:
                print(f"❌ Failed to send security alert to {user_id}: {e}")
    
    async def _create_dm_channel(self, user_id: int) -> Optional[int]:
        """Create DM channel with user"""
        try:
            response = requests.post(
                f"{self.base_url}/users/@me/channels",
                headers=self.headers,
                json={"recipient_id": str(user_id)}
            )
            
            if response.status_code == 200:
                channel_data = response.json()
                return int(channel_data["id"])
            else:
                print(f"❌ Failed to create DM channel with user {user_id}: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error creating DM channel with user {user_id}: {e}")
            return None
    
    async def _send_message(self, channel_id: int, content: str = "", embed: DiscordEmbed = None):
        """Send message to channel"""
        try:
            payload = {}
            if content:
                payload["content"] = content
            if embed:
                payload["embeds"] = [embed.to_dict()]
            
            response = requests.post(
                f"{self.base_url}/channels/{channel_id}/messages",
                headers=self.headers,
                json=payload
            )
            
            if response.status_code == 200:
                return True
            elif response.status_code == 429:  # Rate limited
                retry_after = response.json().get("retry_after", 1)
                print(f"⚠️ Rate limited, waiting {retry_after} seconds")
                await asyncio.sleep(retry_after)
                return await self._send_message(channel_id, content, embed)  # Retry
            else:
                print(f"❌ Failed to send message to {channel_id}: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error sending message to {channel_id}: {e}")
            return False
    
    async def send_message_to_users(self, text: str) -> bool:
        """Send message to all authorized users"""
        sent_count = 0
        
        # Split long messages
        chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
        
        for user_id in self.authorized_users:
            try:
                dm_channel = await self._create_dm_channel(user_id)
                if not dm_channel:
                    continue
                
                for chunk in chunks:
                    if await self._send_message(dm_channel, content=chunk):
                        sent_count += 1
                        
            except Exception as e:
                print(f"❌ Failed to send message to user {user_id}: {e}")
        
        return sent_count > 0
    
    def set_signal_callback(self, callback: Callable):
        """Set signal processing callback"""
        self.signal_callback = callback
        print("✅ Signal callback set")
    
    def register_command(self, command: str, handler: Callable):
        """Register command handler"""
        self.commands[command] = handler
        print(f"✅ Command registered: {command}")