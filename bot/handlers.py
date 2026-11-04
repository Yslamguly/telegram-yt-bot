"""Telegram message and command handlers."""

import asyncio
import functools
import logging
import os
import re

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.config import config
from bot.downloader import (
    DownloadError,
    ReencodeError,
    VideoDurationError,
    VideoTooLongError,
    download_video,
    reencode_to_fit,
)
from bot.s3 import get_s3_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YouTube URL pattern
# ---------------------------------------------------------------------------

YOUTUBE_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:"
    r"youtube\.com/(?:watch\?[^\s]*v=[^\s&]+|shorts/[^\s?]+)|"
    r"youtu\.be/[^\s?]+"
    r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# S3 client (lazy init)
# ---------------------------------------------------------------------------

_s3_client = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = get_s3_client(config)
    return _s3_client


# ---------------------------------------------------------------------------
# Access control decorator
# ---------------------------------------------------------------------------


def authorized_only(func):
    """Decorator that restricts handler access to whitelisted user IDs."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or user.id not in config.ALLOWED_USER_IDS:
            logger.warning(
                "Unauthorized access attempt by user %s (ID: %s)",
                user.full_name if user else "unknown",
                user.id if user else "unknown",
            )
            if update.message:
                await update.message.reply_text(
                    "⛔ Sorry, you are not authorized to use this bot."
                )
            return
        return await func(update, context)

    return wrapper


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command — send a welcome message."""
    await update.message.reply_text(
        "🎬 *YouTube Video Downloader Bot*\n\n"
        "Send me a YouTube link and I'll download the video and send it to you\\!\n\n"
        "*How to use:*\n"
        "• Just paste a YouTube URL in the chat\n"
        "• Or use `/download <url>`\n\n"
        "*Other commands:*\n"
        "• `/help` — Show usage instructions\n"
        "• `/update` — Update yt\\-dlp to latest version",
        parse_mode="MarkdownV2",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command — show usage instructions."""
    await update.message.reply_text(
        "📖 *Usage Instructions*\n\n"
        "*Download a video:*\n"
        "• Paste any YouTube link directly in the chat\n"
        "• Or use: `/download <youtube_url>`\n\n"
        "*Supported link formats:*\n"
        "• `youtube.com/watch?v=...`\n"
        "• `youtu.be/...`\n"
        "• `youtube.com/shorts/...`\n\n"
        "*Limits:*\n"
        f"• Max video duration: {config.MAX_VIDEO_DURATION_MINUTES} minutes\n"
        "• Videos over 50 MB are automatically re\\-encoded\n\n"
        "*Admin commands:*\n"
        "• `/update` — Update yt\\-dlp to the latest version",
        parse_mode="MarkdownV2",
    )


@authorized_only
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /update command — update yt-dlp to the latest version."""
    status_msg = await update.message.reply_text("🔄 Updating yt-dlp...")

    try:
        process = await asyncio.create_subprocess_exec(
            "pip", "install", "--upgrade", "yt-dlp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        # Get new version
        version_proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        version_out, _ = await version_proc.communicate()
        version = version_out.decode().strip()

        await status_msg.edit_text(f"✅ yt-dlp updated successfully!\nVersion: `{version}`", parse_mode="Markdown")
        logger.info("yt-dlp updated to version %s", version)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Update failed: {exc}")
        logger.exception("Failed to update yt-dlp")


@authorized_only
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /download command — download a video by URL."""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/download <youtube_url>`",
            parse_mode="Markdown",
        )
        return

    url = context.args[0]
    if not YOUTUBE_URL_PATTERN.match(url):
        await update.message.reply_text("⚠️ That doesn't look like a YouTube URL.")
        return

    await _process_download(update, context, url)


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------


@authorized_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text messages — detect YouTube URLs and download."""
    if not update.message or not update.message.text:
        return

    match = YOUTUBE_URL_PATTERN.search(update.message.text)
    if match:
        url = match.group(0)
        await _process_download(update, context, url)


# ---------------------------------------------------------------------------
# Core download logic
# ---------------------------------------------------------------------------


async def _process_download(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
) -> None:
    """Download a YouTube video, optionally re-encode, and send to the user."""
    status_msg = await update.message.reply_text("⏳ Downloading video...")
    logger.info("Download requested: %s (user: %s)", url, update.effective_user.id)

    try:
        # Download in a thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: download_video(
                url=url,
                download_dir=config.DOWNLOAD_DIR,
                cookies_file=config.YOUTUBE_COOKIES_FILE,
                max_duration_minutes=config.MAX_VIDEO_DURATION_MINUTES,
            ),
        )

        filepath = result.filepath
        filesize = result.filesize
        max_size_bytes = config.TELEGRAM_MAX_FILE_SIZE_MB * 1024 * 1024

        # Re-encode if too large
        if filesize > max_size_bytes:
            size_mb = filesize / 1024 / 1024
            await status_msg.edit_text(
                f"🔄 Video is too large ({size_mb:.1f} MB). "
                "Re-encoding to fit Telegram's limit..."
            )
            filepath = await loop.run_in_executor(
                None,
                lambda: reencode_to_fit(filepath, result.duration),
            )

        # Upload to Telegram
        await status_msg.edit_text("📤 Uploading to Telegram...")

        with open(filepath, "rb") as video_file:
            kwargs = {
                "video": video_file,
                "caption": result.title,
                "duration": result.duration,
                "supports_streaming": True,
            }
            # Attach thumbnail if available
            if result.thumbnail_path and os.path.isfile(result.thumbnail_path):
                kwargs["thumbnail"] = open(result.thumbnail_path, "rb")

            try:
                await update.message.reply_video(**kwargs)
            finally:
                # Close thumbnail file if opened
                thumb = kwargs.get("thumbnail")
                if thumb and hasattr(thumb, "close"):
                    thumb.close()

        # Delete status message
        try:
            await status_msg.delete()
        except Exception:
            pass  # Not critical if deletion fails

        logger.info("Video sent successfully: %s", result.title)

        # Upload to S3 in the background
        s3 = _get_s3()
        if s3:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: s3.upload_file(filepath),
                )
            except Exception:
                logger.exception("Failed to upload to S3 (non-critical)")

        # Clean up thumbnail
        if result.thumbnail_path and os.path.isfile(result.thumbnail_path):
            try:
                os.remove(result.thumbnail_path)
            except OSError:
                pass

    except VideoDurationError as exc:
        await status_msg.edit_text(
            f"⚠️ {exc}\n\n"
            f"Maximum allowed duration: {config.MAX_VIDEO_DURATION_MINUTES} minutes."
        )
    except VideoTooLongError:
        await status_msg.edit_text(
            "⚠️ Video is too long to compress within Telegram's 50 MB limit.\n"
            "Try a shorter video."
        )
    except ReencodeError as exc:
        logger.exception("Re-encode failed")
        await status_msg.edit_text(
            f"❌ Failed to re-encode video: {exc}\n"
            "Please try a shorter video."
        )
    except DownloadError as exc:
        logger.exception("Download failed")
        await status_msg.edit_text(f"❌ Download failed: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error during download")
        await status_msg.edit_text(
            "❌ An unexpected error occurred. Please try again."
        )


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


def register_handlers(application) -> None:
    """Register all bot handlers with the application."""
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(CommandHandler("update", update_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    logger.info("Handlers registered")
