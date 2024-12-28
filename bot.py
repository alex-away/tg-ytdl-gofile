import asyncio
import logging
import re
import os
import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import TimedOut, RetryAfter

import config
from utils.youtube import YouTubeDownloader
from utils.gofile import GoFileUploader

logging.basicConfig(
    format='%(levelname)-8s %(message)s',
    level=logging.WARNING
)
logger = logging.getLogger(__name__)

video_info_cache = {}
last_update_time = {}
bot = None

async def log_to_channel(text: str):
    """Send log message to the configured channel."""
    if not config.LOG_CHANNEL_ID or not bot:
        return
    try:
        await bot.send_message(
            chat_id=config.LOG_CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Failed to send log to channel: {e}")

async def update_status(message, text: str, keyboard=None):
    """Update status message with rate limiting."""
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
        logger.error(f"Error updating status: {str(e)}")

def restricted(func):
    """Decorator to restrict bot usage to allowed users."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.ALLOWED_USERS:
            logger.warning(f"Unauthorized access denied for {user_id}")
            await update.message.reply_text("🚫 Sorry, you are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

@restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
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

@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        '🎥 *Available Commands*:\n\n'
        '▶️ /start - Start the bot\n'
        '❓ /help - Show this help message\n'
        '⬇️ /download <url> - Download YouTube video\n\n'
        '📋 *How to use*:\n'
        '1. Send /download command with YouTube URL\n'
        '2. Select video quality or audio format\n'
        '3. Wait for download to complete\n'
        '4. Receive file or Gofile link\n\n'
        '⚠️ *Note*: Large files will be uploaded to Gofile'
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

@restricted
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /download command."""
    user = update.effective_user
    await log_to_channel(
        f"🔄 *Download Request*\n"
        f"├ User: `{user.name}` ({user.id})\n"
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
    if not re.match(r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+', url):
        await update.message.reply_text("❌ Please provide a valid YouTube video URL.")
        return

    status_message = await update.message.reply_text(
        "🎥 *Processing Request*\n"
        "└ Fetching video information...",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        downloader = YouTubeDownloader()
        info = downloader.get_video_info(url)
        
        video_info_cache[info['video_id']] = {
            'url': url,
            'info': info,
            'message_id': status_message.message_id,
            'chat_id': status_message.chat_id,
            'user': update.effective_user.name
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
            f"🎯 Select format to download:",
            InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        error_msg = f"❌ *Download Failed*\n└ Error: {str(e)}"
        await update_status(status_message, error_msg)
        logger.error(f"Download error: {str(e)}")

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
            f"├ User: `{video_data['user']}`\n"
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

        downloader = YouTubeDownloader()
        filename, title = await downloader.download(
            video_data['url'],
            'audio' if action == 'a' else 'video',
            format_type,
            format_ext,
            progress_callback
        )

        file_size = downloader.get_file_size(filename)
        
        try:
            if file_size > (config.MAX_DOWNLOAD_SIZE * 1024 * 1024):
                await progress_callback("📤 File too large for Telegram. Uploading to Gofile...")
                
                gofile = GoFileUploader()
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
                
            else:
                await progress_callback("📤 Uploading to Telegram...")
                
                with open(filename, 'rb') as f:
                    if action == 'a':
                        await context.bot.send_audio(
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
                        await context.bot.send_video(
                            chat_id=video_data['chat_id'],
                            video=f,
                            caption=f"🎥 {title}",
                            read_timeout=300,
                            write_timeout=300,
                            connect_timeout=300,
                            pool_timeout=300
                        )
                
                await update_status(
                    status_message,
                    f"✅ *Download Complete*\n"
                    f"├ Title: `{title}`\n"
                    f"├ Size: {file_size / (1024*1024):.1f} MB\n"
                    f"└ Format: {format_type}"
                )
                
                await log_to_channel(
                    f"✅ *Upload Complete (Telegram)*\n"
                    f"├ User: `{video_data['user']}`\n"
                    f"├ Title: `{title}`\n"
                    f"└ Size: {file_size / (1024*1024):.1f} MB"
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

def main():
    """Start the bot."""
    global bot
    
    application = Application.builder().token(config.BOT_TOKEN).build()
    bot = application.bot
    
    try:
        asyncio.get_event_loop().run_until_complete(log_to_channel(
            "🤖 *Bot Started*\n"
            "└ Ready to process requests"
        ))
    except Exception as e:
        logger.error(f"Failed to send startup message: {e}")

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 