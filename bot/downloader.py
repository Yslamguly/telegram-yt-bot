"""YouTube video downloader using yt-dlp with ffmpeg re-encoding support."""

import logging
import os
import subprocess
from dataclasses import dataclass

import yt_dlp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DownloadError(Exception):
    """Generic download failure."""


class VideoDurationError(DownloadError):
    """Video exceeds the maximum allowed duration."""

    def __init__(self, duration_seconds: int, max_seconds: int) -> None:
        self.duration_minutes = duration_seconds / 60
        self.max_minutes = max_seconds / 60
        super().__init__(
            f"Video is {self.duration_minutes:.0f} min long "
            f"(max {self.max_minutes:.0f} min)"
        )


class VideoTooLongError(DownloadError):
    """Video is too long to re-encode within Telegram's file-size limit."""

    def __init__(self) -> None:
        super().__init__(
            "Video is too long to compress within Telegram's 50 MB limit"
        )


class ReencodeError(Exception):
    """ffmpeg re-encoding failure."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DownloadResult:
    """Result of a successful video or audio download."""

    filepath: str
    title: str
    duration: int  # seconds
    filesize: int  # bytes
    thumbnail_path: str | None = None
    artist: str | None = None
    width: int | None = None
    height: int | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def download_video(
    url: str,
    download_dir: str,
    cookies_file: str | None = None,
    max_duration_minutes: int = 30,
) -> DownloadResult:
    """Download a YouTube video using yt-dlp.

    Args:
        url: YouTube video URL.
        download_dir: Directory to save the downloaded file.
        cookies_file: Optional path to a Netscape cookies file.
        max_duration_minutes: Reject videos longer than this.

    Returns:
        A ``DownloadResult`` with metadata and local file path.

    Raises:
        VideoDurationError: If the video is too long.
        DownloadError: On any yt-dlp failure.
    """
    max_duration_seconds = max_duration_minutes * 60

    # -- Base yt-dlp options ------------------------------------------------
    ydl_opts: dict = {
        "format": (
            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720]+bestaudio/"
            "best[height<=720]"
        ),
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(download_dir, "%(id)s.%(ext)s"),
        "writethumbnail": True,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "postprocessors": [
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "jpg",
            }
        ],
        "js_runtimes": {
            "deno": {},
            "node": {},
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "web"]
            }
        },
    }

    if cookies_file and os.path.isfile(cookies_file) and os.path.getsize(cookies_file) > 0:
        ydl_opts["cookiefile"] = cookies_file
        logger.info("Using YouTube cookies from %s (%d bytes)", cookies_file, os.path.getsize(cookies_file))
    else:
        logger.warning("No valid YouTube cookies found at %s — yt-dlp will proceed without cookies", cookies_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # --- Pre-flight: check duration without downloading ------------
            logger.info("Extracting info for %s", url)
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise DownloadError(f"Could not extract info for {url}")

            duration = int(info.get("duration") or 0)
            title = info.get("title", "Unknown")

            if duration > max_duration_seconds:
                raise VideoDurationError(duration, max_duration_seconds)

            # --- Download --------------------------------------------------
            logger.info("Downloading: %s (%d s)", title, duration)
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError(f"Download returned no info for {url}")

            # Locate the downloaded file
            video_id = info["id"]
            filepath = _find_downloaded_file(download_dir, video_id, "mp4")
            if filepath is None:
                raise DownloadError(
                    f"Downloaded file not found for video {video_id}"
                )

            filesize = os.path.getsize(filepath)

            # Determine video width and height
            width = info.get("width")
            height = info.get("height")
            if not width or not height:
                probed_w, probed_h = get_video_dimensions(filepath)
                width = width or probed_w
                height = height or probed_h

            # Locate and prepare thumbnail
            thumbnail_path = _find_downloaded_file(
                download_dir, video_id, "jpg"
            )
            if thumbnail_path and os.path.isfile(thumbnail_path):
                thumbnail_path = prepare_thumbnail(thumbnail_path, width, height)
            elif not thumbnail_path:
                thumbnail_path = generate_thumbnail_from_video(filepath)

            logger.info(
                "Download complete: %s (%.1f MB, %sx%s)",
                filepath,
                filesize / 1024 / 1024,
                width or "?",
                height or "?",
            )

            return DownloadResult(
                filepath=filepath,
                title=title,
                duration=duration,
                filesize=filesize,
                thumbnail_path=thumbnail_path,
                width=width,
                height=height,
            )

    except (VideoDurationError, DownloadError):
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc)) from exc
    except Exception as exc:
        raise DownloadError(f"Unexpected error: {exc}") from exc


def download_audio(
    url: str,
    download_dir: str,
    cookies_file: str | None = None,
    max_duration_minutes: int = 60,
) -> DownloadResult:
    """Download audio from a YouTube video as MP3 using yt-dlp.

    Args:
        url: YouTube video URL.
        download_dir: Directory to save the downloaded file.
        cookies_file: Optional path to a Netscape cookies file.
        max_duration_minutes: Reject videos longer than this.

    Returns:
        A ``DownloadResult`` with metadata and local MP3 file path.

    Raises:
        VideoDurationError: If the media is too long.
        DownloadError: On any yt-dlp failure.
    """
    max_duration_seconds = max_duration_minutes * 60

    # -- Base yt-dlp options for audio --------------------------------------
    ydl_opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(download_dir, "%(id)s.%(ext)s"),
        "writethumbnail": True,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "jpg",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
        ],
        "js_runtimes": {
            "deno": {},
            "node": {},
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "web"]
            }
        },
    }

    if cookies_file and os.path.isfile(cookies_file) and os.path.getsize(cookies_file) > 0:
        ydl_opts["cookiefile"] = cookies_file
        logger.info("Using YouTube cookies from %s (%d bytes)", cookies_file, os.path.getsize(cookies_file))
    else:
        logger.warning("No valid YouTube cookies found at %s — yt-dlp will proceed without cookies", cookies_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # --- Pre-flight: check duration without downloading ------------
            logger.info("Extracting audio info for %s", url)
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise DownloadError(f"Could not extract info for {url}")

            duration = int(info.get("duration") or 0)
            title = info.get("title", "Unknown")
            artist = info.get("artist") or info.get("uploader") or info.get("channel") or "Unknown"

            if duration > max_duration_seconds:
                raise VideoDurationError(duration, max_duration_seconds)

            # --- Download & extract audio ----------------------------------
            logger.info("Downloading audio: %s by %s (%d s)", title, artist, duration)
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError(f"Download returned no info for {url}")

            # Locate the downloaded MP3 file
            video_id = info["id"]
            filepath = _find_downloaded_file(download_dir, video_id, "mp3")
            if filepath is None:
                raise DownloadError(
                    f"Downloaded audio file not found for video {video_id}"
                )

            filesize = os.path.getsize(filepath)

            # Locate thumbnail
            thumbnail_path = _find_downloaded_file(
                download_dir, video_id, "jpg"
            )

            logger.info(
                "Audio download complete: %s (%.1f MB)",
                filepath,
                filesize / 1024 / 1024,
            )

            return DownloadResult(
                filepath=filepath,
                title=title,
                duration=duration,
                filesize=filesize,
                thumbnail_path=thumbnail_path,
                artist=artist,
            )

    except (VideoDurationError, DownloadError):
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc)) from exc
    except Exception as exc:
        raise DownloadError(f"Unexpected error: {exc}") from exc


def reencode_to_fit(
    filepath: str,
    duration: int,
    max_size_mb: int = 49,
) -> str:
    """Re-encode a video so its file size fits under *max_size_mb*.

    Uses two-pass H.264 encoding via ffmpeg to hit a target bitrate
    calculated from the desired output size and the video duration.

    Args:
        filepath: Path to the input video file.
        duration: Video duration in seconds.
        max_size_mb: Maximum output file size in megabytes.

    Returns:
        Path to the re-encoded file.

    Raises:
        VideoTooLongError: If the required video bitrate is too low for
            acceptable quality (< 200 kbps).
        ReencodeError: If ffmpeg fails.
    """
    if duration <= 0:
        raise ReencodeError("Cannot re-encode: video duration is 0")

    # Calculate target bitrate (kbps)
    total_bitrate_kbps = (max_size_mb * 8 * 1024) / duration
    audio_bitrate_kbps = 128
    video_bitrate_kbps = int(total_bitrate_kbps - audio_bitrate_kbps)

    if video_bitrate_kbps < 200:
        raise VideoTooLongError()

    output_path = filepath.replace(".mp4", "_reencoded.mp4")
    logger.info(
        "Re-encoding %s → target video bitrate %d kbps",
        filepath,
        video_bitrate_kbps,
    )

    try:
        # Pass 1
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", filepath,
                "-c:v", "libx264",
                "-b:v", f"{video_bitrate_kbps}k",
                "-pass", "1",
                "-an",
                "-f", "null",
                "/dev/null",
            ],
            check=True,
            capture_output=True,
        )

        # Pass 2
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", filepath,
                "-c:v", "libx264",
                "-b:v", f"{video_bitrate_kbps}k",
                "-pass", "2",
                "-c:a", "aac",
                "-b:a", f"{audio_bitrate_kbps}k",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise ReencodeError(f"ffmpeg failed: {stderr}") from exc
    finally:
        # Clean up ffmpeg log files from two-pass encoding
        for logfile in ("ffmpeg2pass-0.log", "ffmpeg2pass-0.log.mbtree"):
            if os.path.isfile(logfile):
                os.remove(logfile)

    # Remove original and replace
    os.remove(filepath)
    logger.info(
        "Re-encode complete: %s (%.1f MB)",
        output_path,
        os.path.getsize(output_path) / 1024 / 1024,
    )
    return output_path


def reencode_audio_to_fit(
    filepath: str,
    duration: int,
    max_size_mb: int = 49,
) -> str:
    """Re-encode an MP3 audio file so its file size fits under *max_size_mb*.

    Args:
        filepath: Path to the input audio file.
        duration: Audio duration in seconds.
        max_size_mb: Maximum output file size in megabytes.

    Returns:
        Path to the re-encoded audio file.

    Raises:
        ReencodeError: If ffmpeg fails.
    """
    if duration <= 0:
        raise ReencodeError("Cannot re-encode: audio duration is 0")

    # Target bitrate in kbps
    target_bitrate_kbps = int((max_size_mb * 8 * 1024) / duration)
    # Clamp minimum bitrate to 64 kbps (intelligible for speech/music)
    target_bitrate_kbps = max(64, min(target_bitrate_kbps, 192))

    output_path = filepath.replace(".mp3", "_compressed.mp3")
    logger.info(
        "Re-encoding audio %s → target bitrate %d kbps",
        filepath,
        target_bitrate_kbps,
    )

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", filepath,
                "-c:a", "libmp3lame",
                "-b:a", f"{target_bitrate_kbps}k",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        raise ReencodeError(f"ffmpeg audio re-encode failed: {stderr}") from exc

    # Remove original and replace
    os.remove(filepath)
    logger.info(
        "Audio re-encode complete: %s (%.1f MB)",
        output_path,
        os.path.getsize(output_path) / 1024 / 1024,
    )
    return output_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_video_dimensions(filepath: str) -> tuple[int | None, int | None]:
    """Extract width and height of a video or image file using ffprobe.

    Args:
        filepath: Path to the video or image file.

    Returns:
        (width, height) tuple or (None, None) if detection fails.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            filepath,
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        if "x" in output:
            parts = output.split("x")
            return int(parts[0]), int(parts[1])
    except Exception as exc:
        logger.warning("Could not probe dimensions for %s: %s", filepath, exc)
    return None, None


def prepare_thumbnail(
    thumbnail_path: str,
    video_width: int | None = None,
    video_height: int | None = None,
) -> str | None:
    """Optimize a thumbnail for Telegram.

    Ensures dimensions do not exceed 320x320 px and removes 4:3 letterboxing
    if the video is widescreen (16:9) but the thumbnail is 4:3 (e.g., YouTube's hqdefault).

    Args:
        thumbnail_path: Path to the original thumbnail image.
        video_width: Video width in pixels (if known).
        video_height: Video height in pixels (if known).

    Returns:
        Path to the optimized thumbnail file, or the original path on failure.
    """
    if not thumbnail_path or not os.path.isfile(thumbnail_path):
        return None

    thumb_w, thumb_h = get_video_dimensions(thumbnail_path)
    if not thumb_w or not thumb_h:
        return thumbnail_path

    out_path = thumbnail_path.rsplit(".", 1)[0] + "_opt.jpg"
    vf_filters = []

    # If video is widescreen (~16:9 or wider) and thumbnail is 4:3 (480x360 or similar with black bars)
    if video_width and video_height and video_height > 0 and thumb_h > 0:
        video_ratio = video_width / video_height
        thumb_ratio = thumb_w / thumb_h
        # YouTube hqdefault.jpg is 480x360 with 45px black bars on top and bottom
        if video_ratio > 1.6 and thumb_w == 480 and thumb_h == 360:
            vf_filters.append("crop=480:270:0:45")
        elif video_ratio > 1.6 and abs(thumb_ratio - (4 / 3)) < 0.05:
            # Crop 4:3 letterbox bars (remove top/bottom 12.5% padding)
            new_h = int(thumb_w / (16 / 9))
            y_offset = (thumb_h - new_h) // 2
            vf_filters.append(f"crop={thumb_w}:{new_h}:0:{y_offset}")

    # Scale to maximum 320px on the longest side (Telegram requirement)
    vf_filters.append("scale='if(gt(iw,ih),min(320,iw),-2)':'if(gt(iw,ih),-2,min(320,ih))'")

    cmd = [
        "ffmpeg", "-y",
        "-i", thumbnail_path,
        "-vf", ",".join(vf_filters),
        "-q:v", "2",
        out_path,
    ]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            os.replace(out_path, thumbnail_path)
            return thumbnail_path
    except Exception as exc:
        logger.warning("Failed to optimize thumbnail %s: %s", thumbnail_path, exc)
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass

    return thumbnail_path


def generate_thumbnail_from_video(video_path: str) -> str | None:
    """Generate a thumbnail from a video file if none was downloaded.

    Args:
        video_path: Path to the video file.

    Returns:
        Path to the generated JPEG thumbnail or None on failure.
    """
    thumb_path = video_path.rsplit(".", 1)[0] + "_thumb.jpg"
    cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:01",
        "-i", video_path,
        "-vframes", "1",
        "-vf", "scale='if(gt(iw,ih),min(320,iw),-2)':'if(gt(iw,ih),-2,min(320,ih))'",
        "-q:v", "2",
        thumb_path,
    ]
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
    except Exception as exc:
        logger.warning("Could not generate fallback thumbnail for %s: %s", video_path, exc)
    return None


def _find_downloaded_file(
    directory: str, video_id: str, extension: str
) -> str | None:
    """Find a downloaded file by video ID and extension."""
    for fname in os.listdir(directory):
        if fname.startswith(video_id) and fname.endswith(f".{extension}"):
            return os.path.join(directory, fname)
    return None
