import asyncio
import logging
import re
import os
import time
import signal
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import TimedOut, RetryAfter, BadRequest
import shutil
import colorlog

import config
from utils.youtube import YouTubeDownloader, set_youtube_cookies
from utils.gofile import GoFileUploader

COLORS = {
    'red': '\033[91m',
    'green': '\033[92m',
    'yellow': '\033[93m',
    'blue': '\033[94m',
    'purple': '\033[95m',
    'cyan': '\033[96m',
    'white': '\033[97m',
    'grey': '\033[90m',
    'reset': '\033[0m'
}

class UpdatesFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        
        if "Initialized UserManager" in message:
            record.msg = f"{COLORS['cyan']}Initialized UserManager{COLORS['reset']} with {COLORS['yellow']}0{COLORS['reset']} users from {COLORS['blue']}.env{COLORS['reset']}"
            return True
        elif "Loaded" in message and "users from file" in message:
            record.msg = f"{COLORS['cyan']}Loaded{COLORS['reset']} {COLORS['yellow']}1{COLORS['reset']} additional users from {COLORS['blue']}file{COLORS['reset']}"
            return True
        elif "Loaded log channel ID" in message:
            record.msg = f"{COLORS['cyan']}Loaded log channel ID:{COLORS['reset']} {COLORS['yellow']}-4693946728{COLORS['reset']}"
            return True
        elif "Application started" in message:
            record.msg = f"{COLORS['purple']}Application started{COLORS['reset']}"
            return True
        elif "Bot shutting down" in message:
            record.msg = f"{COLORS['red']}Bot shutting down...{COLORS['reset']}"
            return True
        
        if "getUpdates" in message and "HTTP/1.1 200 OK" in message:
            return False

        if "HTTP Request:" in message:
            try:
                if "sendMessage" in message:
                    if "log_channel_id" in message:
                        record.msg = f"📢 {COLORS['green']}Sent log message to channel{COLORS['reset']}"
                    else:
                        record.msg = f"💬 {COLORS['green']}Sent response to user{COLORS['reset']}"
                elif "editMessageText" in message:
                    if '"text": "🎥 *YouTube Download*' in message or '"text": "📊' in message or '[download]' in message:
                        record.msg = f"📥 {COLORS['cyan']}Download progress: {message.split('[download]')[1].strip() if '[download]' in message else 'Starting...'}{COLORS['reset']}"
                    else:
                        record.msg = f"✏️ {COLORS['cyan']}Updated message{COLORS['reset']}"
                elif "sendVideo" in message:
                    record.msg = f"🎥 {COLORS['yellow']}Sent downloaded video to user{COLORS['reset']}"
                elif "sendAudio" in message:
                    record.msg = f"🎵 {COLORS['yellow']}Sent downloaded audio to user{COLORS['reset']}"
                elif "forwardMessage" in message:
                    record.msg = f"↪️ {COLORS['blue']}Forwarded media to log channel{COLORS['reset']}"
                elif "answerCallbackQuery" in message:
                    record.msg = f"🔄 {COLORS['purple']}Processed format selection{COLORS['reset']}"
                else:
                    return False
                
                if "200 OK" in message:
                    record.msg += f" {COLORS['green']}✓{COLORS['reset']}"
                else:
                    record.msg += f" {COLORS['red']}✗{COLORS['reset']}"
                
                record.args = ()
            except Exception:
                return False
                
        return True
    
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    f"{COLORS['grey']}%(asctime)s{COLORS['reset']} %(log_color)s[%(levelname)s]%(reset)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    reset=True,
    log_colors={
        'DEBUG':    'cyan',
        'INFO':     'blue',
        'WARNING':  'yellow',
        'ERROR':    'red',
        'CRITICAL': 'red,bg_white',
    }
))

root_logger.addHandler(handler)
logger = logging.getLogger(__name__)

for logger_name in ['', 'httpx', 'telegram', 'telegram.ext']:
    logging.getLogger(logger_name).addFilter(UpdatesFilter())

video_info_cache = {}
last_update_time = {}
bot = None
upload_progress = {}

COOKIE_PATH = os.path.join('data', 'cookies.txt')
os.makedirs('data', exist_ok=True)

def format_user_info(user, for_telegram=False) -> str:
    if for_telegram:
        username = f"@{user.username}" if user.username else f"{user.id}"
        return f"{user.first_name} ({username})"
    else:
        username = f"{COLORS['cyan']}@{user.username}{COLORS['reset']}" if user.username else f"{user.id}"
        return f"{COLORS['white']}{user.first_name}{COLORS['reset']} ({username})"

async def log_to_channel(text: str):
    log_channel_id = config.user_manager.get_log_channel()
    if not log_channel_id:
        return
    try:

        clean_text = re.sub(r'\033\[[0-9;]+m', '', text)
        await bot.send_message(
            chat_id=log_channel_id,
            text=clean_text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to send log to channel: {e}")

async def update_status(message, text: str, keyboard=None):
    message_id = f"{message.chat_id}_{message.message_id}"
    current_time = time.time()
    
    if message_id in last_update_time:
        time_diff = current_time - last_update_time[message_id]
        if time_diff < 2:
            return

    try:
        if keyboard:
            await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        last_update_time[message_id] = current_time
        
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)
    except TimedOut:
        pass
    except Exception as e:
        logger.error(f"Error updating status: {e}")

def restricted(sudo_only=False):
    def decorator(func):
        @wraps(func)
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            user_info = format_user_info(update.effective_user)
            command = update.message.text.split()[0] if update.message.text else "unknown"
            
            is_sudo = user_id in config.SUDO_USERS
            sudo_indicator = f"{COLORS['yellow']}[SUDO]{COLORS['reset']} " if is_sudo else ""
            logger.info(
                f"🤖 {sudo_indicator}Command {COLORS['yellow']}{command}{COLORS['reset']} used by {user_info}"
            )
            
            if not config.user_manager.is_allowed(user_id):
                logger.warning(f"Access denied for {user_info}")
                await log_to_channel(
                    f"⚠️ *Unauthorized Bot Access Attempt*\n"
                    f"├ User: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                    f"└ Command: `{command}`"
                )
                await update.message.reply_text("🚫 You are not authorized to use this bot.")
                return
            
            if sudo_only and user_id not in config.SUDO_USERS:
                logger.warning(f"Sudo access denied for {user_info}")
                await log_to_channel(
                    f"⚠️ *Unauthorized Sudo Access Attempt*\n"
                    f"├ User: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                    f"└ Command: `{command}`"
                )
                await update.message.reply_text("🚫 This command is only available to sudo users.")
                return
                
            return await func(update, context, *args, **kwargs)
        return wrapped
    return decorator

@restricted(sudo_only=True)
async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide a user ID to add.")
        return
        
    try:
        user_id = int(context.args[0])
        if config.user_manager.add_user(user_id):
            await update.message.reply_text(f"✅ User {user_id} added successfully.")
            await log_to_channel(
                f"👥 *User Added*\n"
                f"├ By: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                f"└ Added: `{user_id}`"
            )
        else:
            await update.message.reply_text(f"ℹ️ User {user_id} is already in the allowed list.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format.")

@restricted(sudo_only=True)
async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide a user ID to remove.")
        return
        
    try:
        user_id = int(context.args[0])
        if user_id in config.SUDO_USERS:
            await update.message.reply_text("❌ Cannot remove a sudo user.")
            return
            
        if config.user_manager.remove_user(user_id):
            await update.message.reply_text(f"✅ User {user_id} removed successfully.")
            await log_to_channel(
                f"👥 *User Removed*\n"
                f"├ By: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                f"└ Removed: `{user_id}`"
            )
        else:
            await update.message.reply_text(f"ℹ️ User {user_id} is not in the allowed list.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format.")

@restricted(sudo_only=True)
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sudo_users = config.SUDO_USERS
    allowed_users = config.user_manager.get_users()
    
    message = (
        "👥 *User List*\n\n"
        "*Sudo Users*:\n"
        + "\n".join([f"└ `{uid}`" for uid in sudo_users])
        + "\n\n*Allowed Users*:\n"
        + "\n".join([f"└ `{uid}`" for uid in allowed_users])
    )
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

@restricted(sudo_only=True)
async def set_log_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Please provide a channel ID.")
        return
        
    try:
        channel_id = int(context.args[0])
        config.user_manager.set_log_channel(channel_id)
        
        await update.message.reply_text(f"✅ Log channel updated to {channel_id}")
        await log_to_channel(
            f"📢 *Log Channel Updated*\n"
            f"├ By: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
            f"└ New: `{channel_id}`"
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID format.")

@restricted()
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    await log_to_channel(
        f"🤖 *Bot Started*\n"
        f"└ User: `{format_user_info(user, for_telegram=True)}`"
    )
    
    help_text = (
        f'👋 Hi {user.first_name}!\n\n'
        '🎥 I can help you download YouTube videos and audio.\n'
        '📝 Use /help to see available commands.\n\n'
        '🔰 Features:\n'
        '• High-quality video downloads\n'
        '• MP3 and WAV audio extraction\n'
        '• Automatic Gofile upload for large files\n'
        '• Progress tracking\n'
        '• Cookie support for restricted videos'
    )
    
    if user.id in config.SUDO_USERS:
        help_text += '\n\n🔑 You have sudo access to this bot.'
    
    await update.message.reply_text(help_text)

@restricted()
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    help_text = (
        "*🎥 Available Commands:*\n\n"
        "`/start` - Start the bot\n"
        "`/help` - Show this help message\n"
        "`/download <url>` - Download YouTube video\n\n"
    )
    
    if user_id in config.SUDO_USERS:
        help_text += (
            "*Sudo Commands:*\n"
            "`/adduser <user_id>` - Add allowed user\n"
            "`/removeuser <user_id>` - Remove allowed user\n"
            "`/listusers` - List all users\n"
            "`/setlogchannel <channel_id>` - Set log channel\n"
            "`/setcookie` - Set YouTube cookies for restricted videos\n"
            "`/cookieytdl <url>` - Download using stored cookies\n\n"
        )
    
    help_text += (
        "*📋 How to use:*\n"
        "1. Send `/download` command with YouTube URL\n"
        "2. Select video quality or audio format\n"
        "3. Wait for download to complete\n"
        "4. Receive file or Gofile link\n\n"
        "*⚠️ Note:* Large files will be uploaded to Gofile"
    )
    
    try:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    except BadRequest as e:
        logger.error(f"Failed to send help message: {e}")

        await update.message.reply_text(help_text.replace('*', '').replace('`', ''))

@restricted()
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /download command."""
    user = update.effective_user
    await log_to_channel(
        f"🔄 *Download Request*\n"
        f"├ User: `{format_user_info(user, for_telegram=True)}`\n"
        f"└ URL: `{context.args[0] if context.args else 'No URL provided'}`"
    )
    
    if not context.args:
        await update.message.reply_text(
            "ℹ️ Please provide a YouTube URL.\n"
            "📝 Example: `/download https://youtube.com/watch?v=...`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    url = context.args[0]
    if not re.match(r'https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|live/)|youtu\.be/)[\w-]+', url):
        await update.message.reply_text("❌ Please provide a valid YouTube video URL.")
        return

    status_message = await update.message.reply_text(
        "🎥 *Processing Request*\n"
        "└ Fetching video information...",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        cookie_path = os.path.join('data', 'cookies.txt') if context.user_data.get('use_cookies') else None
        downloader = YouTubeDownloader(cookie_path=cookie_path)
        info = await downloader.get_video_info(url)
        
        video_info_cache[info['video_id']] = {
            'url': url,
            'info': info,
            'message_id': status_message.message_id,
            'chat_id': status_message.chat_id,
            'user': update.effective_user.name,
            'use_cookies': context.user_data.get('use_cookies', False)
        }

        keyboard = []

        audio_row = []
        for audio_format in config.SUPPORTED_AUDIO_FORMATS:
            audio_row.append(
                InlineKeyboardButton(
                    f"🎵 {audio_format.upper()}",
                    callback_data=f"a_{audio_format}_none_{info['video_id']}"
                )
            )
        keyboard.append(audio_row)
        
        for quality in sorted(info['formats']['video'].keys(), 
                            key=lambda x: int(x[:-1])):
            row = []
            for ext in sorted(info['formats']['video'][quality].keys()):
                row.append(
                    InlineKeyboardButton(
                        f"🎥 {quality} • {ext.upper()}",
                        callback_data=f"v_{quality}_{ext}_{info['video_id']}"
                    )
                )
            keyboard.append(row)

        duration_min = info['duration'] // 60
        duration_sec = info['duration'] % 60
        views_formatted = "{:,}".format(info['views'])

        await update_status(
            status_message,
            f"📽 *Video Information*\n"
            f"├ Title: `{info['title']}`\n"
            f"├ Channel: {info['author']}\n"
            f"├ Duration: {duration_min}:{duration_sec:02d}\n"
            f"└ Views: {views_formatted}\n\n"
            f"Select format to download:",
            InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        error_msg = f"❌ *Download Failed*\n└ Error: {str(e)}"
        await update_status(status_message, error_msg)
        logger.error(f"Download error: {str(e)}")
        await log_to_channel(
            f"❌ *Download Error*\n"
            f"└ Error: `{str(e)}`"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks for format selection."""
    query = update.callback_query
    await query.answer("✅ Processing your selection...")

    try:
        action, format_type, format_ext, video_id = query.data.split('_')
        
        if video_id not in video_info_cache:
            await update_status(query.message, "❌ Session expired. Please try downloading again.")
            return

        video_data = video_info_cache[video_id]
        status_message = query.message
        
        await log_to_channel(
            f"📥 *Download Started*\n"
            f"├ User: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
            f"├ Title: `{video_data['info']['title']}`\n"
            f"├ Type: {'Audio' if action == 'a' else 'Video'}\n"
            f"└ Format: {format_type}"
        )

        last_progress_update = {'time': 0, 'percentage': 0}
        
        async def progress_callback(text: str):
            current_time = time.time()
            if 'progress' in text:
                try:
                    current_percentage = float(re.search(r'(\d+\.\d+)%', text).group(1))
                    if (current_time - last_progress_update['time'] < 2 and 
                        abs(current_percentage - last_progress_update['percentage']) < 10):
                        return
                    last_progress_update.update({'time': current_time, 'percentage': current_percentage})
                except:
                    pass
            
            full_text = (
                f"🎥 *YouTube Download*\n"
                f"├ Title: `{video_data['info']['title']}`\n"
                f"└ Status:\n{text}"
            )
            await update_status(status_message, full_text)

        cookie_path = os.path.join('data', 'cookies.txt') if video_data.get('use_cookies') else None
        downloader = YouTubeDownloader(cookie_path=cookie_path)
        
        filename, title = await downloader.download(
            video_data['url'],
            'audio' if action == 'a' else 'video',
            format_type,
            format_ext,
            progress_callback
        )

        await log_to_channel(
            f"✅ *Download Complete*\n"
            f"├ User: `{video_data['user']}`\n"
            f"├ Title: `{title}`\n"
            f"└ Size: {downloader.get_file_size(filename) / (1024*1024):.1f} MB"
        )

        file_size = downloader.get_file_size(filename)
        
        try:
            if file_size > (config.MAX_DOWNLOAD_SIZE * 1024 * 1024) or config.FORCE_GOFILE:
                await log_to_channel(
                    f"📤 *Upload Started*\n"
                    f"├ Platform: Gofile\n"
                    f"├ User: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                    f"├ Title: `{title}`\n"
                    f"└ Size: {file_size / (1024*1024):.1f} MB"
                )
                await progress_callback("📤 File will be uploaded to Gofile...")
                
                try:
                    async with GoFileUploader() as gofile:
                        result = await gofile.upload_file(filename, progress_callback)
                    
                    final_text = (
                        f"✅ *Download Complete*\n"
                        f"├ Title: `{title}`\n"
                        f"├ Size: {file_size / (1024*1024):.1f} MB\n"
                        f"├ Format: {format_type}\n"
                        f"└ [Download from Gofile]({result['download_link']})\n\n"
                        f"⚠️ Note: Link expires after some time"
                    )
                    await update_status(status_message, final_text)
                    
                    await log_to_channel(
                        f"✅ *Upload Complete (Gofile)*\n"
                        f"├ User: `{video_data['user']}`\n"
                        f"├ Title: `{title}`\n"
                        f"└ Size: {file_size / (1024*1024):.1f} MB"
                    )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Gofile upload error: {error_msg}")
                    await update_status(status_message, f"❌ *Upload Failed*\n└ Error: {error_msg}")
                    await log_to_channel(
                        f"❌ *Upload Error*\n"
                        f"├ User: `{video_data['user']}`\n"
                        f"├ Title: `{title}`\n"
                        f"└ Error: `{error_msg}`"
                    )
                    raise
                
            else:
                await log_to_channel(
                    f"📤 *Upload Started*\n"
                    f"├ Platform: Telegram\n"
                    f"├ User: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                    f"├ Title: `{title}`\n"
                    f"└ Size: {file_size / (1024*1024):.1f} MB"
                )
                await progress_callback("📤 Uploading to Telegram...")
                
                with open(filename, 'rb') as f:
                    if action == 'a':
                        sent_msg = await context.bot.send_audio(
                            chat_id=video_data['chat_id'],
                            audio=f,
                            title=title,
                            caption=f"🎵 {title}",
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=300,
                            pool_timeout=300
                        )
                    else:
                        sent_msg = await context.bot.send_video(
                            chat_id=video_data['chat_id'],
                            video=f,
                            caption=f"🎥 {title}",
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=300,
                            pool_timeout=300
                        )
                    
                    await log_to_channel(
                        f"✅ *Upload Complete (Telegram)*\n"
                        f"├ User: `{video_data['user']}`\n"
                        f"├ Title: `{title}`\n"
                        f"└ Size: {file_size / (1024*1024):.1f} MB"
                    )
                    
                    log_channel_id = config.user_manager.get_log_channel()
                    if log_channel_id:
                        await sent_msg.forward(
                            chat_id=log_channel_id,
                            disable_notification=True,
                            protect_content=True
                        )
                
                await update_status(
                    status_message,
                    f" *Download Complete*\n"
                    f"├ Title: `{title}`\n"
                    f"└ Size: {file_size / (1024*1024):.1f} MB\n"
                    f"└ Format: {format_type}"
                )
                
        finally:
            try:
                if os.path.exists(filename):
                    os.remove(filename)
                    await log_to_channel(
                        f"🗑 *File Deleted*\n"
                        f"└ Path: `{filename}`"
                    )
            except Exception as e:
                logger.error(f"Failed to delete file {filename}: {str(e)}")
                await log_to_channel(
                    f"⚠️ *File Deletion Failed*\n"
                    f"├ Path: `{filename}`\n"
                    f"└ Error: `{str(e)}`"
                )

        del video_info_cache[video_id]

    except TimedOut:
        await update_status(query.message, "⚠️ Upload timed out, but the file might still be processing. Please check your chat.")
        await log_to_channel("⚠️ *Upload Timed Out*")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in button callback: {error_msg}")
        await update_status(query.message, f"❌ *Error*\n└ {error_msg}")
        await log_to_channel(
            f"❌ *Download Error*\n"
            f"└ Error: `{error_msg}`"
        )

async def shutdown():
    """Perform graceful shutdown."""
    try:
        await log_to_channel(
            "🔴 *Bot Shutting Down*\n"
            "└ Graceful shutdown initiated"
        )
    except Exception as e:
        logger.error(f"Failed to send shutdown log: {e}")
    finally:
        logger.info("Bot shutting down...")
        os._exit(0)

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    loop = asyncio.get_running_loop()
    loop.create_task(shutdown())

def main():
    global bot
    
    application = Application.builder().token(config.BOT_TOKEN).build()
    bot = application.bot
    
    commands = [
        ("start", "Start the bot"),
        ("help", "Show help message"),
        ("download", "Download YouTube video/audio"),
        ("cookieytdl", "Download using stored cookies")
    ]
    
    sudo_commands = commands + [
        ("adduser", "Add allowed user"),
        ("removeuser", "Remove allowed user"),
        ("listusers", "List all users"),
        ("setlogchannel", "Set log channel"),
        ("setcookie", "Set YouTube cookies for restricted videos")
    ]
    
    async def set_commands():
        await bot.set_my_commands(commands)
        
        for sudo_id in config.SUDO_USERS:
            try:
                await bot.set_my_commands(
                    sudo_commands,
                    scope=BotCommandScopeChat(chat_id=sudo_id)
                )
            except Exception as e:
                logger.error(f"Failed to set sudo commands for {sudo_id}: {e}")

    async def startup():
        await log_to_channel(
            "🟢 *Bot Started*\n"
            "└ Ready to process requests"
        )
        await set_commands()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        loop.run_until_complete(startup())
        
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("download", download_command))
        application.add_handler(CommandHandler("cookieytdl", cookieytdl_command))
        application.add_handler(CommandHandler("adduser", add_user_command))
        application.add_handler(CommandHandler("removeuser", remove_user_command))
        application.add_handler(CommandHandler("listusers", list_users_command))
        application.add_handler(CommandHandler("setlogchannel", set_log_channel_command))
        application.add_handler(CommandHandler("setcookie", set_cookie_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+'),
            download_command
        ))

        logger.info(f"🚀 {COLORS['green']}Bot started successfully{COLORS['reset']}")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"{COLORS['red']}Failed to start bot: {e}{COLORS['reset']}")
        raise

@restricted(sudo_only=True)
async def set_cookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /setcookie command for sudo users."""

    if update.message.reply_to_message and update.message.reply_to_message.document:
        document = update.message.reply_to_message.document
    elif update.message.document:
        document = update.message.document
    else:
        await update.message.reply_text(
            "❌ Please send a cookie file in Netscape/Mozilla format.\n\n"
            "*How to get cookies:*\n"
            "1. Install a cookie exporter extension\n"
            "2. Go to YouTube in a private/incognito window\n"
            "3. Log in to your account\n"
            "4. Export cookies and send the file here\n"
            "5. Close the private/incognito window",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:

        cookie_file = await document.get_file()
        cookie_bytes = await cookie_file.download_as_bytearray()

        temp_cookie_path = os.path.join(config.TEMP_PATH, 'temp_cookies.txt')
        with open(temp_cookie_path, 'wb') as f:
            f.write(cookie_bytes)

        if set_youtube_cookies(temp_cookie_path):
            await update.message.reply_text(
                "✅ *Cookies Set Successfully*\n"
                "You can now use `/cookieytdl` to download restricted videos.",
                parse_mode=ParseMode.MARKDOWN
            )
            await log_to_channel(
                "🔄 *Cookies Updated*\n"
                f"├ By: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
                f"└ Status: Success"
            )
        else:
            await update.message.reply_text("❌ Invalid cookie file format. Please send a valid Netscape/Mozilla format cookie file.")

        try:
            os.remove(temp_cookie_path)
        except:
            pass

    except Exception as e:
        logger.error(f"Cookie file error: {e}")
        await update.message.reply_text(f"❌ Error processing cookie file: {str(e)}")
        await log_to_channel(
            "⚠️ *Cookie Update Failed*\n"
            f"├ By: `{format_user_info(update.effective_user, for_telegram=True)}`\n"
            f"└ Error: `{str(e)}`"
        )

@restricted()
async def cookieytdl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /cookieytdl command to download using stored cookies."""
    cookie_path = os.path.join('data', 'cookies.txt')
    
    if not os.path.exists(cookie_path):
        if update.effective_user.id in config.SUDO_USERS:
            await update.message.reply_text(
                "❌ No cookies set. Use /setcookie to add cookies first.\n\n"
                "*How to set cookies:*\n"
                "1. Use /setcookie command\n"
                "2. Reply with a cookie file in Netscape format\n"
                "3. Wait for confirmation",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ No cookies available. Please contact a sudo user to set up cookies."
            )
        return

    if not context.args:
        await update.message.reply_text(
            "ℹ️ Please provide a YouTube URL.\n"
            "📝 Example: `/cookieytdl https://youtube.com/watch?v=...`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    context.user_data['use_cookies'] = True
    await download_command(update, context)

def add_handlers(application: Application):

    application.add_handler(CommandHandler("setcookie", set_cookie_command))
    application.add_handler(CommandHandler("cookieytdl", cookieytdl_command))

if __name__ == '__main__':
    main() 