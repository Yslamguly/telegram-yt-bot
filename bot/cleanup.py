"""Periodic cleanup of old downloaded files."""

import logging
import os
import time

from telegram.ext import Application

logger = logging.getLogger(__name__)


def cleanup_old_files(download_dir: str, max_age_minutes: int) -> int:
    """Delete files in *download_dir* older than *max_age_minutes*.

    Args:
        download_dir: The directory to scan.
        max_age_minutes: Delete files older than this many minutes.

    Returns:
        Number of files deleted.
    """
    if not os.path.isdir(download_dir):
        return 0

    now = time.time()
    max_age_seconds = max_age_minutes * 60
    deleted = 0

    for filename in os.listdir(download_dir):
        filepath = os.path.join(download_dir, filename)
        if not os.path.isfile(filepath):
            continue

        file_age = now - os.path.getmtime(filepath)
        if file_age > max_age_seconds:
            try:
                os.remove(filepath)
                deleted += 1
                logger.info(
                    "Cleaned up: %s (age: %.0f min)",
                    filename,
                    file_age / 60,
                )
            except OSError:
                logger.exception("Failed to delete %s", filepath)

    return deleted


def schedule_cleanup(
    application: Application,
    download_dir: str,
    interval_minutes: int,
    max_age_minutes: int,
) -> None:
    """Schedule periodic file cleanup using the bot's job queue.

    Args:
        application: The ``python-telegram-bot`` Application instance.
        download_dir: Directory to clean.
        interval_minutes: How often to run the cleanup (in minutes).
        max_age_minutes: Delete files older than this (in minutes).
    """

    async def _cleanup_job(context) -> None:  # noqa: ANN001
        deleted = cleanup_old_files(download_dir, max_age_minutes)
        if deleted:
            logger.info("Cleanup complete — deleted %d file(s)", deleted)

    job_queue = application.job_queue
    if job_queue is None:
        logger.warning(
            "Job queue is not available — automatic cleanup is disabled. "
            "Install python-telegram-bot[job-queue] to enable it."
        )
        return

    job_queue.run_repeating(
        _cleanup_job,
        interval=interval_minutes * 60,
        first=60,  # first run 60 s after startup
        name="cleanup",
    )
    logger.info(
        "Cleanup scheduled — every %d min, deleting files older than %d min",
        interval_minutes,
        max_age_minutes,
    )
