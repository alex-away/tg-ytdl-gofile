import logging
import re
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

import config
from utils.youtube import YouTubeDownloader

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

video_info_cache = {}

def restricted(func):
    """Decorator to restrict bot usage to allowed users."""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.ALLOWED_USERS:
            logger.warning(f"Unauthorized access denied for {user_id}")
            await update.message.reply_text("Sorry, you are not authorized to use this bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

@restricted
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f'Hi {user.first_name}! 👋\n\n'
        'I can help you download YouTube videos and audio.\n'
        'Use /help to see available commands.'
    )

@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        '🎥 *Available Commands*:\n\n'
        '/start - Start the bot\n'
        '/help - Show this help message\n'
        '/download <url> - Download YouTube video\n'
        '\n'
        '🎯 *Features*:\n'
        '• Video and audio quality selection\n'
        '• MP3 and WAV audio formats\n'
        '• Automatic Gofile upload for large files\n'
        '• Cookie support for restricted videos'
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

@restricted
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /download command."""
    if not context.args:
        await update.message.reply_text(
            "Please provide a YouTube URL.\n"
            "Example: `/download https://youtube.com/watch?v=...`",
            parse_mode='Markdown'
        )
        return

    url = context.args[0]
    
    if not re.match(r'https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+', url):
        await update.message.reply_text("Please provide a valid YouTube video URL.")
        return

    try:
        status_message = await update.message.reply_text("🔍 Fetching video information...")
        
        await context.bot.send_message(
            chat_id=config.LOG_CHANNEL_ID,
            text=f"Download started by {update.effective_user.name} ({update.effective_user.id})\nURL: {url}"
        )

        downloader = YouTubeDownloader()
        info = downloader.get_video_info(url)
        
        video_info_cache[info['video_id']] = {
            'url': url,
            'info': info
        }

        keyboard = []
        
        for quality in sorted(info['formats']['video'].keys(), 
                            key=lambda x: int(x[:-1]), reverse=True):
            keyboard.append([
                InlineKeyboardButton(
                    f"Video {quality}",
                    callback_data=f"v_{quality}_{info['video_id']}"
                )
            ])
        
        audio_row = []
        for audio_format in config.SUPPORTED_AUDIO_FORMATS:
            audio_row.append(
                InlineKeyboardButton(
                    f"Audio ({audio_format.upper()})",
                    callback_data=f"a_{audio_format}_{info['video_id']}"
                )
            )
        keyboard.append(audio_row)

        await status_message.edit_text(
            f"📝 *Title*: {info['title']}\n"
            f"⏱ *Duration*: {info['duration']} seconds\n\n"
            "Please select a format to download:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        error_message = f"Error processing video: {str(e)}"
        logger.error(error_message)
        await status_message.edit_text(f"❌ {error_message}")
        
        await context.bot.send_message(
            chat_id=config.LOG_CHANNEL_ID,
            text=f"❌ Download failed for {update.effective_user.name} ({update.effective_user.id})\nURL: {url}\nError: {str(e)}"
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks for format selection."""
    query = update.callback_query
    await query.answer()

    try:
        action, format_type, video_id = query.data.split('_')
        
        if video_id not in video_info_cache:
            await query.edit_message_text("❌ Session expired. Please try downloading again.")
            return

        video_data = video_info_cache[video_id]
        await query.edit_message_text(
            f"Selected format: {format_type}\n"
            "Download functionality coming in next phase!"
        )

    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}")
        await query.edit_message_text(f"❌ Error: {str(e)}")

def main():
    """Start the bot."""
    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 