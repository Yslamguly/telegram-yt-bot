"""Bot configuration loaded from environment variables."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Bot configuration loaded from environment variables."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    ALLOWED_USER_IDS: list[int] = field(default_factory=list)

    # Downloads
    DOWNLOAD_DIR: str = "/tmp/yt-downloads"
    MAX_VIDEO_DURATION_MINUTES: int = 30
    TELEGRAM_MAX_FILE_SIZE_MB: int = 50

    # Cleanup
    CLEANUP_INTERVAL_MINUTES: int = 60
    MAX_FILE_AGE_MINUTES: int = 60

    # AWS S3
    S3_ENABLED: bool = True
    S3_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"

    # YouTube cookies
    YOUTUBE_COOKIES_FILE: str | None = None

    # Logging
    LOG_LEVEL: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

        raw_ids = os.environ.get("ALLOWED_USER_IDS", "")
        if not raw_ids:
            raise ValueError("ALLOWED_USER_IDS environment variable is required")

        allowed_ids = [int(uid.strip()) for uid in raw_ids.split(",") if uid.strip()]

        s3_enabled = os.environ.get("S3_ENABLED", "true").lower() in ("true", "1", "yes")
        s3_bucket = os.environ.get("S3_BUCKET_NAME", "")
        if s3_enabled and not s3_bucket:
            raise ValueError("S3_BUCKET_NAME is required when S3_ENABLED is true")

        cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "/app/cookies/cookies.txt")
        if cookies_file and not Path(cookies_file).is_file():
            logging.warning(
                "YouTube cookies file not found at %s — downloads may be blocked by YouTube",
                cookies_file,
            )
            cookies_file = None

        download_dir = os.environ.get("DOWNLOAD_DIR", "/tmp/yt-downloads")
        Path(download_dir).mkdir(parents=True, exist_ok=True)

        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

        return cls(
            TELEGRAM_BOT_TOKEN=token,
            ALLOWED_USER_IDS=allowed_ids,
            DOWNLOAD_DIR=download_dir,
            MAX_VIDEO_DURATION_MINUTES=int(
                os.environ.get("MAX_VIDEO_DURATION_MINUTES", "30")
            ),
            TELEGRAM_MAX_FILE_SIZE_MB=50,
            CLEANUP_INTERVAL_MINUTES=int(
                os.environ.get("CLEANUP_INTERVAL_MINUTES", "60")
            ),
            MAX_FILE_AGE_MINUTES=int(os.environ.get("MAX_FILE_AGE_MINUTES", "60")),
            S3_ENABLED=s3_enabled,
            S3_BUCKET_NAME=s3_bucket,
            AWS_REGION=os.environ.get("AWS_REGION", "us-east-1"),
            YOUTUBE_COOKIES_FILE=cookies_file,
            LOG_LEVEL=log_level,
        )


# ---------- Module-level singleton ----------

config = Config.from_env()

# Configure root logger
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
