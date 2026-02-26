import logging
import os
from pathlib import Path
import asyncio
import hashlib

from telegram import Update, ReactionTypeEmoji, InlineKeyboardButton, InlineKeyboardMarkup, InputTextMessageContent
from telegram.ext import (
    Application,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
    ContextTypes,
    InlineQueryHandler,
)

import yt_dlp

# CONFIG
BOT_TOKEN = "8572728429:AAGbA418OuCvgfs1rl46t9UO1vFmrGMaigk"  # তোর পুরো টোকেন দিস

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB Telegram limit
MAX_BATCH = 5

BOT_USERNAME = "@SmartVidDownloader_bot"
CAPTION_SUFFIX = f"\n\nYours, {BOT_USERNAME} 💙"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

url_map = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Send Link", callback_data="send_link")],
        [InlineKeyboardButton("Search on YouTube", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("Invite Friend", callback_data="invite")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Welcome to Smart Video Downloader! 🚀\n\n"
        "Send link(s) from YouTube, Instagram, TikTok, Facebook, Twitter/X etc.\n\n"
        "Use buttons below:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "invite":
        invite_link = f"https://t.me/{context.bot.username}?start=ref"
        await query.message.reply_text(f"Share this link:\n{invite_link}")
        return

    if data.startswith("q_"):
        quality, url_hash = data.split("_")[1:]
        url = url_map.get(url_hash)
        if not url:
            await query.edit_message_text("Session expired. Send link again.")
            return

        await query.edit_message_text(f"Downloading in {quality}...")
        await download_and_send(update, context, url, quality, query.message.message_id)

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        return

    results = []
    try:
        ydl_opts = {'quiet': True, 'format': 'best', 'max_downloads': 10}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch10:{query}", download=False)['entries']

        for i, entry in enumerate(search_results, 1):
            title = entry.get('title', 'No title')[:100]
            url = entry.get('webpage_url', '')
            thumbnail = entry.get('thumbnail', '')
            duration = entry.get('duration', 0)
            dur_str = f"{duration//60}:{duration%60:02d}" if duration else "Live"

            results.append(
                InlineQueryResultArticle(
                    id=str(i),
                    title=title,
                    url=url,
                    thumb_url=thumbnail,
                    description=f"Duration: {dur_str}",
                    input_message_content=InputTextMessageContent(url)
                )
            )

        await update.inline_query.answer(results, cache_time=0)

    except Exception as e:
        logger.error(f"Inline search failed: {e}")
        await update.inline_query.answer([])

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # 👀 reaction
    try:
        await context.bot.set_message_reaction(
            chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
            reaction=[ReactionTypeEmoji(emoji="👀")],
        )
    except Exception as e:
        logger.debug(f"Reaction failed: {e}")

    links = [line.strip() for line in text.splitlines() if line.strip().startswith(('http://', 'https://'))]
    if not links:
        return

    if len(links) > MAX_BATCH:
        await update.message.reply_text(f"Maximum {MAX_BATCH} links at a time!")
        return

    for i, url in enumerate(links, 1):
        msg = await update.message.reply_text(f"Processing {i}/{len(links)}...")
        await download_and_send(update, context, url, "best", msg.message_id)

async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, quality: str, msg_id: int):
    try:
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        url_map[url_hash] = url

        ydl_opts_info = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Untitled')
            is_youtube = "youtube.com" in url or "youtu.be" in url

        if is_youtube and quality == "best":
            keyboard = [
                [InlineKeyboardButton("1080p", callback_data=f"q_1080_{url_hash}"),
                 InlineKeyboardButton("720p", callback_data=f"q_720_{url_hash}")],
                [InlineKeyboardButton("480p", callback_data=f"q_480_{url_hash}"),
                 InlineKeyboardButton("360p", callback_data=f"q_360_{url_hash}")],
                [InlineKeyboardButton("144p", callback_data=f"q_144_{url_hash}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=msg_id,
                text=f"Choose quality for:\n{title}",
                reply_markup=reply_markup
            )
            return

        opts = {
            'quiet': True,
            'continuedl': True,
            'retries': 5,
            'outtmpl': str(DOWNLOAD_DIR / '%(id)s.%(ext)s'),
            'no_warnings': True,
        }

        # ফরম্যাট সিলেক্ট (শুধু ভিডিও)
        if is_youtube:
            height = int(quality[:-1]) if quality != "best" else 1080
            opts['format'] = f'bestvideo[height<={height}][ext=mp4]/best[ext=mp4]/best'
        else:
            opts['format'] = 'bestvideo[ext=mp4]/best[ext=mp4]'

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)

        file_path = next(DOWNLOAD_DIR.glob("*.*"), None)
        if not file_path:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text="File not found after download.")
            return

        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="😭😭\n\n**⛔️ File too large!**\nTelegram limit is 2GB.\n\n😶‍🌫️"
            )
            file_path.unlink()
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            return

        caption = f"Downloaded from:\n{url}{CAPTION_SUFFIX}"

        await context.bot.send_video(chat_id=update.effective_chat.id, video=open(file_path, "rb"), caption=caption)

        file_path.unlink()

        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=msg_id, text="Download complete! ✅")

    except Exception as e:
        error_str = str(e).lower()
        if "private" in error_str or "follow" in error_str or "registered users" in error_str or "data retrieval" in error_str or "could not be retrieved" in error_str:
            error_text = "😭😭\n\n**⛔️ Publication information could not be retrieved**\n\n**Possible causes:**\n▫️ **closed (private) account;**\n▫️ **data retrieval error;**\n▫️ **the account has age restrictions.**\n\n😶‍🌫️"
        else:
            error_text = f"😭😭\n\n**⛔️ Error:** {error_str[:150]}\n\n😶‍🌫️"

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=error_text
        )
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(InlineQueryHandler(inline_query))

    print("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()