"""Unit tests for video aspect ratio handling and thumbnail optimization."""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Provide default env vars so bot.config doesn't raise ValueError during test imports
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "mock_test_token")
os.environ.setdefault("ALLOWED_USERNAMES", "testuser")
os.environ.setdefault("S3_ENABLED", "false")

from bot.downloader import (
    DownloadResult,
    download_video,
    generate_thumbnail_from_video,
    get_video_dimensions,
    prepare_thumbnail,
)
from bot.handlers import _process_download


class TestVideoDimensions(unittest.IsolatedAsyncioTestCase):
    """Test video dimensions detection and thumbnail handling."""

    def test_download_result_with_dimensions(self):
        result = DownloadResult(
            filepath="/tmp/video.mp4",
            title="Widescreen Video",
            duration=120,
            filesize=10485760,
            thumbnail_path="/tmp/thumb.jpg",
            width=1280,
            height=720,
        )
        self.assertEqual(result.width, 1280)
        self.assertEqual(result.height, 720)

    @patch("subprocess.run")
    def test_get_video_dimensions_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.stdout = "1920x1080\n"
        mock_run.return_value = mock_proc

        w, h = get_video_dimensions("/tmp/fake_video.mp4")
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)

    @patch("subprocess.run")
    def test_get_video_dimensions_failure(self, mock_run):
        mock_run.side_effect = Exception("ffprobe error")
        w, h = get_video_dimensions("/tmp/bad_video.mp4")
        self.assertIsNone(w)
        self.assertIsNone(h)

    @patch("bot.downloader.get_video_dimensions")
    @patch("os.path.isfile")
    @patch("subprocess.run")
    def test_prepare_thumbnail_crops_hqdefault(self, mock_run, mock_isfile, mock_get_dims):
        mock_isfile.return_value = True
        mock_get_dims.return_value = (480, 360)

        # For a 16:9 video (1280x720) and 480x360 thumbnail
        prepare_thumbnail("/tmp/thumb.jpg", video_width=1280, video_height=720)

        # Verify ffmpeg was invoked with crop filter for 480x360
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        self.assertIn("crop=480:270:0:45", cmd_str)
        self.assertIn("scale=", cmd_str)

    @patch("bot.downloader.yt_dlp.YoutubeDL")
    @patch("bot.downloader._find_downloaded_file")
    @patch("bot.downloader.prepare_thumbnail")
    @patch("os.path.getsize")
    @patch("os.path.isfile")
    def test_download_video_returns_dimensions(
        self, mock_isfile, mock_getsize, mock_prep_thumb, mock_find_file, mock_ydl_class
    ):
        mock_isfile.return_value = True
        mock_getsize.return_value = 15000000
        mock_find_file.side_effect = lambda directory, video_id, ext: f"/tmp/{video_id}.{ext}"
        mock_prep_thumb.side_effect = lambda path, w, h: path

        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.side_effect = [
            {"id": "vid123", "title": "Test Video", "duration": 180, "width": 1280, "height": 720},
            {"id": "vid123", "title": "Test Video", "duration": 180, "width": 1280, "height": 720},
        ]

        result = download_video("https://youtube.com/watch?v=vid123", download_dir="/tmp")
        self.assertEqual(result.width, 1280)
        self.assertEqual(result.height, 720)
        self.assertEqual(result.filepath, "/tmp/vid123.mp4")

    @patch("bot.handlers.download_video")
    @patch("os.path.isfile")
    @patch("builtins.open")
    async def test_process_download_passes_dimensions_to_reply_video(
        self, mock_open, mock_isfile, mock_download_video
    ):
        mock_isfile.return_value = False  # No thumbnail
        mock_download_video.return_value = DownloadResult(
            filepath="/tmp/test.mp4",
            title="Aspect Test",
            duration=60,
            filesize=1000,
            width=1280,
            height=720,
        )

        update = MagicMock()
        update.effective_user.id = 12345
        status_msg = AsyncMock()
        update.message.reply_text = AsyncMock(return_value=status_msg)
        update.message.reply_video = AsyncMock()

        context = MagicMock()

        await _process_download(update, context, "https://youtube.com/watch?v=aspect123")

        update.message.reply_video.assert_called_once()
        kwargs = update.message.reply_video.call_args[1]
        self.assertEqual(kwargs.get("width"), 1280)
        self.assertEqual(kwargs.get("height"), 720)
