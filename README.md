# YouTube Telegram Downloader Bot

A Telegram bot that downloads YouTube videos and audio with advanced features and user management.

## Features

- 🎥 High-quality video downloads (144p to 4K)
- 🎵 Audio extraction (MP3/WAV)
- 📤 Automatic Gofile.io upload for large files
- 👥 User management system with sudo users
- 📝 Configurable log channel
- 🍪 Cookie support for restricted videos
- 📊 Real-time progress tracking
- 🔄 Automatic retries and fallback servers
- 🛡️ Rate limiting and concurrent download management

## Setup

### Using Docker (Recommended)

1. Clone the repository
2. Copy `.env.example` to `.env` and configure it
3. Build and run the Docker container:
```bash
docker build -t yt-tg-bot .
docker run -d --name yt-tg-bot --env-file .env yt-tg-bot
```

### Manual Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# OR
.\venv\Scripts\activate  # Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

## Configuration

Required environment variables in `.env`:
- `BOT_TOKEN`: Telegram bot token from @BotFather
- `SUDO_USERS`: Comma-separated list of Telegram user IDs for admin access
- `USERS`: Optional comma-separated list of allowed user IDs

Optional settings:
- `GOFILE_API_KEY`: GoFile.io API key for authenticated uploads
- `MAX_DOWNLOAD_SIZE`: Maximum file size in MB (default: 2048)
- `MAX_CONCURRENT_DOWNLOADS`: Maximum parallel downloads (default: 2)
- `FORCE_GOFILE`: Always use GoFile.io for uploads (true/false)

## Commands

### User Commands
- `/start` - Start the bot and see features
- `/help` - Show available commands
- `/download <url>` - Download YouTube video/audio
- `/cookieytdl <url>` - Download using stored cookies

### Admin Commands (Sudo Users Only)
- `/adduser <user_id>` - Add allowed user
- `/removeuser <user_id>` - Remove allowed user
- `/listusers` - List all users
- `/setlogchannel <channel_id>` - Set log channel
- `/setcookie` - Set YouTube cookies for restricted videos

## Features in Detail

### User Management
- Three-tier system: Sudo users, allowed users, and unauthorized users
- Persistent user storage in `data/data.json`
- Sudo users can manage allowed users list

### Download System
- Automatic quality selection based on availability
- Progress tracking with ETA and speed
- Automatic file upload to GoFile.io for large files
- Support for restricted videos using cookies

### Upload System
- Smart server selection with fallback options
- Automatic retries with exponential backoff
- Progress tracking for uploads
- Direct and page links for downloads

## File Structure
```
├── bot.py           # Main bot code
├── config.py        # Configuration and user management
├── utils/
│   ├── youtube.py   # YouTube download handling
│   └── gofile.py    # GoFile upload handling
├── data/
│   ├── data.json    # User data storage
│   └── cookies.txt  # YouTube cookies
└── downloads/       # Temporary download storage
```

## Requirements

- Python 3.12 or higher
- FFmpeg (for audio conversion)
- Internet connection for YouTube downloads and GoFile uploads 