# YouTube Telegram Downloader Bot

A Telegram bot that downloads YouTube videos and audio with advanced features.

## Features

- 🎥 Video quality selection (up to 4K)
- 🎵 Audio format selection (MP3/WAV)
- 📤 Automatic Gofile upload for large files
- 📝 Log channel support
- 🍪 Cookie support for restricted videos

## Setup

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

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Required environment variables:
- `BOT_TOKEN`: Your Telegram bot token from @BotFather
- `LOG_CHANNEL_ID`: Telegram channel ID for logging

## Usage

1. Start the bot:
```bash
python bot.py
```

2. Available commands:
- `/start` - Start the bot
- `/help` - Show help message
- `/download <url>` - Download YouTube video

## Requirements

- Python 3.8 or higher
- FFmpeg (for audio conversion) 