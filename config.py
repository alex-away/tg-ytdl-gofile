import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in .env file")

LOG_CHANNEL_ID = os.getenv('LOG_CHANNEL_ID')
if not LOG_CHANNEL_ID:
    raise ValueError("LOG_CHANNEL_ID is required in .env file")
LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)

SUDO_USERS = os.getenv('SUDO_USERS', '')
if not SUDO_USERS:
    raise ValueError("SUDO_USERS is required in .env file")
SUDO_USERS = [int(user_id.strip()) for user_id in SUDO_USERS.split(',') if user_id.strip()]

USERS = os.getenv('USERS', '')
USERS = [int(user_id.strip()) for user_id in USERS.split(',') if user_id.strip()]

class UserManager:
    def __init__(self, file_path='data/data.json'):
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.allowed_users = set(USERS)
        self.log_channel_id = LOG_CHANNEL_ID
        logger.info(f"Initialized UserManager with {len(USERS)} users from .env")
        self.load_data()

    def load_data(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    data = json.load(f)
                    before_count = len(self.allowed_users)
                    self.allowed_users.update(data.get('allowed_users', []))
                    after_count = len(self.allowed_users)
                    logger.info(f"Loaded {after_count - before_count} additional users from file")
                    self.log_channel_id = data.get('log_channel_id', LOG_CHANNEL_ID)
                    logger.info(f"Loaded log channel ID: {self.log_channel_id}")
        except Exception as e:
            logger.error(f"Error loading data from {self.file_path}: {e}")

    def save_data(self):
        try:
            data = {
                'allowed_users': [u for u in self.allowed_users if u not in USERS],
                'log_channel_id': self.log_channel_id
            }
            with open(self.file_path, 'w') as f:
                json.dump(data, f)
            logger.info(f"Saved {len(data['allowed_users'])} users and log channel ID to {self.file_path}")
        except Exception as e:
            logger.error(f"Error saving data to {self.file_path}: {e}")

    def add_user(self, user_id: int) -> bool:
        if user_id in SUDO_USERS:
            logger.info(f"Attempted to add sudo user {user_id} to allowed users")
            return False
        if user_id in USERS:
            logger.info(f"Attempted to add .env user {user_id} to allowed users")
            return False
        if user_id not in self.allowed_users:
            self.allowed_users.add(user_id)
            self.save_data()
            logger.info(f"Added user {user_id} to allowed users")
            return True
        logger.info(f"User {user_id} already in allowed users")
        return False

    def remove_user(self, user_id: int) -> bool:
        if user_id in SUDO_USERS:
            logger.info(f"Attempted to remove sudo user {user_id}")
            return False
        if user_id in USERS:
            logger.info(f"Attempted to remove .env user {user_id}")
            return False
        if user_id in self.allowed_users:
            self.allowed_users.remove(user_id)
            self.save_data()
            logger.info(f"Removed user {user_id} from allowed users")
            return True
        logger.info(f"Attempted to remove non-existent user {user_id}")
        return False

    def is_allowed(self, user_id: int) -> bool:
        allowed = user_id in self.allowed_users or user_id in SUDO_USERS or user_id in USERS
        logger.debug(f"Access check for user {user_id}: {'allowed' if allowed else 'denied'}")
        return allowed

    def get_users(self) -> list:
        return list(self.allowed_users)

    def is_sudo(self, user_id: int) -> bool:
        return user_id in SUDO_USERS

    def set_log_channel(self, channel_id: int):
        self.log_channel_id = channel_id
        self.save_data()

    def get_log_channel(self) -> int:
        return self.log_channel_id

user_manager = UserManager()

MAX_DOWNLOAD_SIZE = int(os.getenv('MAX_DOWNLOAD_SIZE', 2048))
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', 2))
GOFILE_API_KEY = os.getenv('GOFILE_API_KEY')
FORCE_GOFILE = os.getenv('FORCE_GOFILE', '').lower() == 'true'

SUPPORTED_AUDIO_FORMATS = ['mp3', 'wav']
SUPPORTED_VIDEO_QUALITIES = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']

DOWNLOAD_PATH = 'downloads'
COOKIES_PATH = 'cookies'
TEMP_PATH = os.path.join(DOWNLOAD_PATH, 'temp')

for path in [DOWNLOAD_PATH, COOKIES_PATH, TEMP_PATH]:
    os.makedirs(path, exist_ok=True) 