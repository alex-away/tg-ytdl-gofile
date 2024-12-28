import os
import colorlog
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up colored logging
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))

logger = colorlog.getLogger()
logger.addHandler(handler)
logger.setLevel('INFO')

# Required Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in .env file")

LOG_CHANNEL_ID = os.getenv('LOG_CHANNEL_ID')
if not LOG_CHANNEL_ID:
    raise ValueError("LOG_CHANNEL_ID is required in .env file")
LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)

# User Access Control
ALLOWED_USERS = os.getenv('ALLOWED_USERS', '')
if not ALLOWED_USERS:
    raise ValueError("ALLOWED_USERS is required in .env file")
ALLOWED_USERS = [int(user_id.strip()) for user_id in ALLOWED_USERS.split(',') if user_id.strip()]

# Download Configuration
MAX_DOWNLOAD_SIZE = int(os.getenv('MAX_DOWNLOAD_SIZE', 2048))  # in MB
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', 2))

# Gofile Configuration
GOFILE_API_KEY = os.getenv('GOFILE_API_KEY')  # Optional

# Format Support
SUPPORTED_AUDIO_FORMATS = ['mp3', 'wav']
SUPPORTED_VIDEO_QUALITIES = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']

# Paths
DOWNLOAD_PATH = 'downloads'
COOKIES_PATH = 'cookies'
TEMP_PATH = os.path.join(DOWNLOAD_PATH, 'temp')

# Create necessary directories
for path in [DOWNLOAD_PATH, COOKIES_PATH, TEMP_PATH]:
    os.makedirs(path, exist_ok=True) 