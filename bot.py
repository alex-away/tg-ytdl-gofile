import logging
import re
import os
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import TimedOut

import config
from utils.youtube import YouTubeDownloader
from utils.gofile import GoFileUploader

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store video information temporarily
video_info_cache = {}

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

async def update_status(message, text: str, keyboard=None):
    """Update status message with error handling."""
    try:
        if keyboard:
            await message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        else:
            await message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except TimedOut:
        pass
    except Exception as e:
        logger.error(f"Error updating status: {str(e)}")

@restricted
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /download command."""
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

    # Single status message for all updates
    status_message = await update.message.reply_text(
        "🎥 *Processing Request*\n"
        "└ Fetching video information...",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        # Get video information
        downloader = YouTubeDownloader()
        info = downloader.get_video_info(url)
        
        # Cache video information
        video_info_cache[info['video_id']] = {
            'url': url,
            'info': info,
            'message_id': status_message.message_id,
            'chat_id': status_message.chat_id,
            'user': update.effective_user.name
        }

        # Create format selection buttons
        keyboard = []
        
        # Video formats
        for quality in sorted(info['formats']['video'].keys(), 
                            key=lambda x: int(x[:-1]), reverse=True):
            for ext in sorted(info['formats']['video'][quality].keys()):
                keyboard.append([
                    InlineKeyboardButton(
                        f"🎥 {quality} • {ext.upper()}",
                        callback_data=f"v_{quality}_{ext}_{info['video_id']}"
                    )
                ])
        
        # Audio formats
        audio_row = []
        for audio_format in config.SUPPORTED_AUDIO_FORMATS:
            audio_row.append(
                InlineKeyboardButton(
                    f"🎵 {audio_format.upper()}",
                    callback_data=f"a_{audio_format}_none_{info['video_id']}"
                )
            )
        keyboard.append(audio_row)

        # Format video information
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
        # Parse callback data
        action, format_type, format_ext, video_id = query.data.split('_')
        
        if video_id not in video_info_cache:
            await update_status(query.message, "❌ Session expired. Please try downloading again.")
            return

        video_data = video_info_cache[video_id]
        status_message = query.message

        # Progress callback for single message updates
        async def progress_callback(text: str):
            full_text = (
                f"🎥 *YouTube Download*\n"
                f"├ Title: `{video_data['info']['title']}`\n"
                f"└ Status:\n{text}"
            )
            await update_status(status_message, full_text)

        # Start download
        downloader = YouTubeDownloader()
        filename, title = await downloader.download(
            video_data['url'],
            'audio' if action == 'a' else 'video',
            format_type,
            format_ext,
            progress_callback
        )

        # Check file size
        file_size = downloader.get_file_size(filename)
        
        if file_size > (config.MAX_DOWNLOAD_SIZE * 1024 * 1024):  # Convert MB to bytes
            await progress_callback("📤 File too large for Telegram. Uploading to Gofile...")
            
            # Upload to Gofile
            gofile = GoFileUploader()
            result = await gofile.upload_file(filename, progress_callback)
            
            # Final status update with Gofile link
            final_text = (
                f"✅ *Download Complete*\n"
                f"├ Title: `{title}`\n"
                f"├ Size: {file_size / (1024*1024):.1f} MB\n"
                f"├ Format: {format_type}\n"
                f"└ [Download from Gofile]({result['download_link']})\n\n"
                f"⚠️ Note: Link expires after some time"
            )
            await update_status(status_message, final_text)
            
        else:
            # Send file directly through Telegram
            await progress_callback("📤 Uploading to Telegram...")
            
            with open(filename, 'rb') as f:
                if action == 'a':
                    await context.bot.send_audio(
                        chat_id=video_data['chat_id'],
                        audio=f,
                        title=title,
                        caption=f"🎵 {title}"
                    )
                else:
                    await context.bot.send_video(
                        chat_id=video_data['chat_id'],
                        video=f,
                        caption=f"🎥 {title}"
                    )
            
            # Final status update
            await update_status(
                status_message,
                f"✅ *Download Complete*\n"
                f"├ Title: `{title}`\n"
                f"├ Size: {file_size / (1024*1024):.1f} MB\n"
                f"└ Format: {format_type}"
            )

        # Cleanup
        try:
            os.remove(filename)
        except:
            pass

        # Remove from cache
        del video_info_cache[video_id]

    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}")
        await update_status(query.message, f"❌ *Error*\n└ {str(e)}")

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(config.BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 