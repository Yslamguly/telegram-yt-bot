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


def is_user_authorized(user) -> bool:
    """Check if a Telegram user is authorized by ID or username."""
    if user is None:
        return False
    if user.id in config.ALLOWED_USER_IDS:
        return True
    if user.username and user.username.lower() in [u.lower() for u in config.ALLOWED_USERNAMES]:
        return True
    return False


def authorized_only(func):
    """Decorator that restricts handler access to whitelisted users (by ID or username)."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not is_user_authorized(user):
            logger.warning(
                "Unauthorized access attempt by user %s (@%s, ID: %s)",
                user.full_name if user else "unknown",
                user.username if user else "none",
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
        "• `/update` — Update yt\\-dlp to latest version\n"
        "• `/cookies` — Check or update YouTube cookies\n"
        "• `/users` — View authorized users\n"
        "• `/authorize` — Whitelist a new user by username or ID",
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
        "• `/update` — Update yt\\-dlp to the latest version\n"
        "• `/cookies` — View cookies status or upload a new `cookies.txt`\n"
        "• `/users` — View all authorized usernames and IDs\n"
        "• `/authorize <@username or ID>` — Add a user to whitelist\n"
        "• `/deauthorize <@username or ID>` — Remove a user from whitelist",
        parse_mode="MarkdownV2",
    )


@authorized_only
async def cookies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /cookies command — show cookie file status or explain how to update."""
    target_path = config.YOUTUBE_COOKIES_FILE or "/app/cookies/cookies.txt"
    if os.path.isfile(target_path) and os.path.getsize(target_path) > 0:
        size = os.path.getsize(target_path)
        mtime = os.path.getmtime(target_path)
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        await update.message.reply_text(
            f"🍪 *YouTube Cookies Status: Active*\n\n"
            f"• File: `{target_path}`\n"
            f"• Size: `{size:,} bytes`\n"
            f"• Last updated: `{dt}`\n\n"
            f"💡 *To update:* Simply send your new `cookies.txt` file as a document into this chat.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"🍪 *YouTube Cookies Status: Missing*\n\n"
            f"No cookies file found at `{target_path}`.\n\n"
            f"💡 *How to get cookies:*\n"
            f"1. Install extension *\"Get cookies.txt LOCALLY\"* ([Chrome](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) / [Firefox](https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/))\n"
            f"2. Open YouTube while logged in (use a burner account)\n"
            f"3. Click the extension icon and export as `cookies.txt`\n"
            f"4. Send the `cookies.txt` file as a document directly into this chat",
            parse_mode="Markdown",
        )


@authorized_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document uploads — accept cookies.txt to update cookies without SSH."""
    doc = update.message.document
    if not doc:
        return

    file_name = doc.file_name or ""
    if not file_name.lower().endswith(".txt"):
        return

    status_msg = await update.message.reply_text("📥 Processing uploaded cookies file...")
    try:
        tg_file = await doc.get_file()
        file_bytes = await tg_file.download_as_bytearray()

        content = file_bytes.decode("utf-8", errors="ignore")
        # Validate that it looks like a cookies file
        if "Netscape HTTP Cookie File" not in content and "youtube.com" not in content:
            await status_msg.edit_text(
                "⚠️ *Invalid cookies file*\n\n"
                "The uploaded file does not look like a Netscape format cookies file from YouTube.\n"
                "Please make sure it starts with `# Netscape HTTP Cookie File` and contains YouTube cookies.",
                parse_mode="Markdown",
            )
            return

        target_path = config.YOUTUBE_COOKIES_FILE or "/app/cookies/cookies.txt"
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(file_bytes)

        size = len(file_bytes)
        logger.info("Cookies updated via Telegram upload: %s (%d bytes)", target_path, size)
        await status_msg.edit_text(
            f"✅ *Cookies updated successfully!*\n\n"
            f"• File: `{os.path.basename(target_path)}`\n"
            f"• Size: `{size:,} bytes`\n"
            f"• Saved to: `{target_path}`\n\n"
            f"The bot will use these cookies immediately for future downloads.",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.exception("Failed to save uploaded cookies file")
        await status_msg.edit_text(f"❌ Failed to save cookies: {exc}")


@authorized_only
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /update command — update yt-dlp to the latest version."""
    status_msg = await update.message.reply_text("🔄 Updating yt-dlp...")

    try:
        process = await asyncio.create_subprocess_exec(
            "pip", "install", "--upgrade", "yt-dlp[default]",
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
async def authorize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /authorize <@username or user_id> — whitelist a user at runtime."""
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "• `/authorize @username` — allow a user by username\n"
            "• `/authorize <user_id>` — allow a user by numeric ID\n"
            "• `/users` — view all authorized users",
            parse_mode="Markdown",
        )
        return

    target = context.args[0].strip()
    clean_target = target.lstrip("@").lower()

    if clean_target.isdigit() or (clean_target.startswith("-") and clean_target[1:].isdigit()):
        uid = int(clean_target)
        if uid not in config.ALLOWED_USER_IDS:
            config.ALLOWED_USER_IDS.append(uid)
            logger.info("User ID %d authorized by %s", uid, update.effective_user.id)
            await update.message.reply_text(f"✅ User ID `{uid}` has been authorized.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ User ID `{uid}` is already authorized.", parse_mode="Markdown")
    else:
        if clean_target not in [u.lower() for u in config.ALLOWED_USERNAMES]:
            config.ALLOWED_USERNAMES.append(clean_target)
            logger.info("Username @%s authorized by %s", clean_target, update.effective_user.id)
            await update.message.reply_text(f"✅ Username `@{clean_target}` has been authorized.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ Username `@{clean_target}` is already authorized.", parse_mode="Markdown")


@authorized_only
async def deauthorize_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /deauthorize <@username or user_id> — remove a user from whitelist."""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/deauthorize <@username or user_id>`",
            parse_mode="Markdown",
        )
        return

    target = context.args[0].strip().lstrip("@").lower()

    if target.isdigit() or (target.startswith("-") and target[1:].isdigit()):
        uid = int(target)
        if uid in config.ALLOWED_USER_IDS:
            config.ALLOWED_USER_IDS.remove(uid)
            logger.info("User ID %d deauthorized by %s", uid, update.effective_user.id)
            await update.message.reply_text(f"✅ User ID `{uid}` has been removed.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ User ID `{uid}` was not in the authorized list.", parse_mode="Markdown")
    else:
        matching = [u for u in config.ALLOWED_USERNAMES if u.lower() == target]
        if matching:
            for m in matching:
                config.ALLOWED_USERNAMES.remove(m)
            logger.info("Username @%s deauthorized by %s", target, update.effective_user.id)
            await update.message.reply_text(f"✅ Username `@{target}` has been removed.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ Username `@{target}` was not in the authorized list.", parse_mode="Markdown")


@authorized_only
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /users — list all authorized usernames and IDs."""
    ids_str = ", ".join(f"`{i}`" for i in config.ALLOWED_USER_IDS) or "_None_"
    users_str = ", ".join(f"`@{u}`" for u in config.ALLOWED_USERNAMES) or "_None_"

    await update.message.reply_text(
        f"👥 *Authorized Access List*\n\n"
        f"• *Usernames:* {users_str}\n"
        f"• *User IDs:* {ids_str}\n\n"
        f"💡 Use `/authorize <@username or ID>` to add\n"
        f"💡 Use `/deauthorize <@username or ID>` to remove",
        parse_mode="Markdown",
    )


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
        err_text = str(exc)
        err_lower = err_text.lower()
        if (
            "confirm you're not a bot" in err_lower
            or "confirm you’re not a bot" in err_lower
            or "sign in to confirm" in err_lower
            or "use --cookies" in err_lower
        ):
            await status_msg.edit_text(
                "❌ *Download failed: YouTube Bot Verification Required*\n\n"
                "YouTube blocked this download with: _\"Sign in to confirm you're not a bot\"_.\n\n"
                "💡 *How to get & update cookies:*\n"
                "1. Install browser extension *\"Get cookies.txt LOCALLY\"* ([Chrome](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) / [Firefox](https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/))\n"
                "2. Open YouTube while logged in (use a secondary/burner account)\n"
                "3. Click the extension icon and export as `cookies.txt`\n"
                "4. **Attach and send the `cookies.txt` file directly into this chat**\n\n"
                "Check `/cookies` to verify status anytime.",
                parse_mode="Markdown",
            )
        else:
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
    application.add_handler(CommandHandler("cookies", cookies_command))
    application.add_handler(CommandHandler("authorize", authorize_command))
    application.add_handler(CommandHandler("auth", authorize_command))
    application.add_handler(CommandHandler("deauthorize", deauthorize_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    logger.info("Handlers registered")
