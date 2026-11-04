"""Entry point for the Telegram YouTube Downloader Bot."""

import logging

from telegram.ext import ApplicationBuilder

from bot.cleanup import schedule_cleanup
from bot.config import config
from bot.handlers import register_handlers

logger = logging.getLogger(__name__)


def main() -> None:
    """Build the bot application and start polling."""
    logger.info("Starting Telegram YouTube Downloader Bot")
    logger.info("Allowed users: %s", config.ALLOWED_USER_IDS)
    logger.info("Download dir: %s", config.DOWNLOAD_DIR)
    logger.info("S3 enabled: %s", config.S3_ENABLED)

    # Build the application
    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Register command and message handlers
    register_handlers(application)

    # Schedule periodic cleanup
    schedule_cleanup(
        application,
        download_dir=config.DOWNLOAD_DIR,
        interval_minutes=config.CLEANUP_INTERVAL_MINUTES,
        max_age_minutes=config.MAX_FILE_AGE_MINUTES,
    )

    # Start polling
    logger.info("Bot is running in polling mode...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
