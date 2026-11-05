"""Unit tests for YouTube audio extraction and handler logic."""

import os
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Provide default env vars so bot.config doesn't raise ValueError during test imports
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "mock_test_token")
os.environ.setdefault("ALLOWED_USERNAMES", "testuser")
os.environ.setdefault("S3_ENABLED", "false")

from bot.downloader import (
    DownloadResult,
    VideoDurationError,
    download_audio,
    reencode_audio_to_fit,
)
from bot.handlers import (
    YOUTUBE_URL_PATTERN,
    audio_command,
    download_command,
    register_handlers,
)



class TestDownloaderAudio(unittest.TestCase):
    """Test audio downloader functions."""

    def test_download_result_dataclass(self):
        result = DownloadResult(
            filepath="/tmp/test.mp3",
            title="Test Song",
            duration=180,
            filesize=5000000,
            thumbnail_path="/tmp/test.jpg",
            artist="Test Artist",
        )
        self.assertEqual(result.filepath, "/tmp/test.mp3")
        self.assertEqual(result.title, "Test Song")
        self.assertEqual(result.duration, 180)
        self.assertEqual(result.artist, "Test Artist")

    @patch("bot.downloader.yt_dlp.YoutubeDL")
    @patch("bot.downloader._find_downloaded_file")
    @patch("os.path.getsize")
    def test_download_audio_success(self, mock_getsize, mock_find_file, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        mock_ydl.extract_info.side_effect = [
            {"id": "abc1234", "title": "Great Song", "artist": "Cool Artist", "duration": 200},
            {"id": "abc1234", "title": "Great Song", "artist": "Cool Artist", "duration": 200},
        ]
        mock_find_file.side_effect = lambda directory, video_id, ext: f"/tmp/{video_id}.{ext}"
        mock_getsize.return_value = 4500000

        result = download_audio(
            url="https://www.youtube.com/watch?v=abc1234",
            download_dir="/tmp",
            max_duration_minutes=30,
        )

        self.assertEqual(result.title, "Great Song")
        self.assertEqual(result.artist, "Cool Artist")
        self.assertEqual(result.filepath, "/tmp/abc1234.mp3")
        self.assertEqual(result.thumbnail_path, "/tmp/abc1234.jpg")
        self.assertEqual(result.filesize, 4500000)

    @patch("bot.downloader.yt_dlp.YoutubeDL")
    def test_download_audio_duration_exceeded(self, mock_ydl_class):
        mock_ydl = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl

        mock_ydl.extract_info.return_value = {
            "id": "long123",
            "title": "Too Long Video",
            "duration": 4000,
        }

        with self.assertRaises(VideoDurationError):
            download_audio(
                url="https://www.youtube.com/watch?v=long123",
                download_dir="/tmp",
                max_duration_minutes=30,
            )

    @patch("subprocess.run")
    @patch("os.remove")
    @patch("os.path.getsize")
    def test_reencode_audio_to_fit(self, mock_getsize, mock_remove, mock_run):
        mock_getsize.return_value = 35000000

        output = reencode_audio_to_fit(
            filepath="/tmp/music.mp3",
            duration=3600,
            max_size_mb=49,
        )

        self.assertEqual(output, "/tmp/music_compressed.mp3")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("ffmpeg", cmd)
        self.assertIn("libmp3lame", cmd)
        mock_remove.assert_called_once_with("/tmp/music.mp3")


class TestAudioHandlers(unittest.IsolatedAsyncioTestCase):
    """Test Telegram handler logic for audio commands."""

    def test_youtube_url_pattern(self):
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtube.com/watch?v=dQw4w9WgXcQ&feature=share",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://youtube.com/shorts/dQw4w9WgXcQ?feature=share",
        ]
        for url in urls:
            match = YOUTUBE_URL_PATTERN.search(url)
            self.assertIsNotNone(match, f"Failed matching {url}")

    @patch("bot.handlers._process_audio_download", new_callable=AsyncMock)
    async def test_audio_command_with_arg(self, mock_process):
        update = MagicMock()
        update.effective_user.id = 123456
        update.effective_user.username = "testuser"
        context = MagicMock()
        context.args = ["https://youtu.be/dQw4w9WgXcQ"]

        with patch("bot.handlers.is_user_authorized", return_value=True):
            await audio_command(update, context)

        mock_process.assert_called_once_with(
            update, context, "https://youtu.be/dQw4w9WgXcQ"
        )

    @patch("bot.handlers._process_audio_download", new_callable=AsyncMock)
    async def test_audio_command_from_reply(self, mock_process):
        update = MagicMock()
        update.effective_user.id = 123456
        update.effective_user.username = "testuser"
        update.message.reply_to_message.text = "Check this out https://youtu.be/dQw4w9WgXcQ"
        context = MagicMock()
        context.args = []

        with patch("bot.handlers.is_user_authorized", return_value=True):
            await audio_command(update, context)

        mock_process.assert_called_once_with(
            update, context, "https://youtu.be/dQw4w9WgXcQ"
        )

    @patch("bot.handlers._process_audio_download", new_callable=AsyncMock)
    async def test_audio_command_missing_url(self, mock_process):
        update = MagicMock()
        update.effective_user.id = 123456
        update.effective_user.username = "testuser"
        update.message.reply_to_message = None
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []

        with patch("bot.handlers.is_user_authorized", return_value=True):
            await audio_command(update, context)

        mock_process.assert_not_called()
        update.message.reply_text.assert_called_once()
        self.assertIn("Usage: `/audio <youtube_url>`", update.message.reply_text.call_args[0][0])

    def test_handler_registration(self):
        app = MagicMock()
        register_handlers(app)
        registered_commands = [
            call[0][0].commands for call in app.add_handler.call_args_list if hasattr(call[0][0], "commands")
        ]
        flattened_commands = [cmd for group in registered_commands for cmd in group]
        self.assertIn("audio", flattened_commands)
        self.assertIn("mp3", flattened_commands)
        self.assertIn("download", flattened_commands)


if __name__ == "__main__":
    unittest.main()
