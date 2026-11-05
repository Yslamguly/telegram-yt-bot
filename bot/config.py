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
    ALLOWED_USERNAMES: list[str] = field(default_factory=list)

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

        allowed_ids: list[int] = []
        allowed_usernames: list[str] = []

        # Parse from ALLOWED_USER_IDS, ALLOWED_USERNAMES, and ALLOWED_USERS
        raw_inputs = [
            os.environ.get("ALLOWED_USER_IDS", ""),
            os.environ.get("ALLOWED_USERNAMES", ""),
            os.environ.get("ALLOWED_USERS", ""),
        ]
        combined_raw = ",".join(filter(None, raw_inputs))
        for item in combined_raw.split(","):
            cleaned = item.strip()
            if not cleaned:
                continue
            without_at = cleaned.lstrip("@")
            if without_at.isdigit() or (without_at.startswith("-") and without_at[1:].isdigit()):
                allowed_ids.append(int(without_at))
            else:
                allowed_usernames.append(without_at.lower())

        allowed_ids = list(dict.fromkeys(allowed_ids))
        allowed_usernames = list(dict.fromkeys(allowed_usernames))

        if not allowed_ids and not allowed_usernames:
            raise ValueError(
                "At least one of ALLOWED_USER_IDS or ALLOWED_USERNAMES environment variable is required"
            )

        s3_enabled = os.environ.get("S3_ENABLED", "true").lower() in ("true", "1", "yes")
        s3_bucket = os.environ.get("S3_BUCKET_NAME", "")
        if s3_enabled and not s3_bucket:
            raise ValueError("S3_BUCKET_NAME is required when S3_ENABLED is true")

        cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "/app/cookies/cookies.txt")
        if cookies_file and not Path(cookies_file).is_file():
            logging.warning(
                "YouTube cookies file not found at %s at startup — will check dynamically at runtime",
                cookies_file,
            )

        download_dir = os.environ.get("DOWNLOAD_DIR", "/tmp/yt-downloads")
        Path(download_dir).mkdir(parents=True, exist_ok=True)

        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

        return cls(
            TELEGRAM_BOT_TOKEN=token,
            ALLOWED_USER_IDS=allowed_ids,
            ALLOWED_USERNAMES=allowed_usernames,
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
