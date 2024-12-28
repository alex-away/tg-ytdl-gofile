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
    def __init__(self, file_path='data/users.json'):
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.allowed_users = set(USERS)
        logger.info(f"Initialized UserManager with {len(USERS)} users from .env")
        self.load_users()

    def load_users(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    data = json.load(f)
                    before_count = len(self.allowed_users)
                    self.allowed_users.update(data.get('allowed_users', []))
                    after_count = len(self.allowed_users)
                    logger.info(f"Loaded {after_count - before_count} additional users from file")
        except Exception as e:
            logger.error(f"Error loading users from {self.file_path}: {e}")

    def save_users(self):
        try:
            users_to_save = [u for u in self.allowed_users if u not in USERS]
            with open(self.file_path, 'w') as f:
                json.dump({'allowed_users': users_to_save}, f)
            logger.info(f"Saved {len(users_to_save)} users to {self.file_path}")
        except Exception as e:
            logger.error(f"Error saving users to {self.file_path}: {e}")

    def add_user(self, user_id: int) -> bool:
        if user_id in SUDO_USERS:
            logger.info(f"Attempted to add sudo user {user_id} to allowed users")
            return False
        if user_id in USERS:
            logger.info(f"Attempted to add .env user {user_id} to allowed users")
            return False
        if user_id not in self.allowed_users:
            self.allowed_users.add(user_id)
            self.save_users()
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
            self.save_users()
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

user_manager = UserManager()

MAX_DOWNLOAD_SIZE = int(os.getenv('MAX_DOWNLOAD_SIZE', 2048))
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', 2))
GOFILE_API_KEY = os.getenv('GOFILE_API_KEY')

SUPPORTED_AUDIO_FORMATS = ['mp3', 'wav']
SUPPORTED_VIDEO_QUALITIES = ['144p', '240p', '360p', '480p', '720p', '1080p', '1440p', '2160p']

DOWNLOAD_PATH = 'downloads'
COOKIES_PATH = 'cookies'
TEMP_PATH = os.path.join(DOWNLOAD_PATH, 'temp')

for path in [DOWNLOAD_PATH, COOKIES_PATH, TEMP_PATH]:
    os.makedirs(path, exist_ok=True) 