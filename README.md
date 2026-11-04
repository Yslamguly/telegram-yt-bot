# Telegram YouTube Downloader Bot

A Telegram bot that downloads YouTube videos and sends them directly to your chat.

## Features
- Send a YouTube link → receive the video in Telegram
- Auto-detects YouTube URLs or use `/download` command
- Auto re-encodes videos exceeding Telegram's 50 MB limit
- Stores videos temporarily in AWS S3
- Auto-updates yt-dlp on every restart
- YouTube cookies support to avoid blocking
- User whitelist for access control
- Periodic cleanup of old files

## Prerequisites
- Docker and Docker Compose
- A Telegram Bot Token (from @BotFather)
- AWS account with S3 access (optional)

## Quick Start

### 1. Get a Telegram Bot Token
1. Open Telegram and message @BotFather
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Find Your Telegram User ID
1. Message @userinfobot on Telegram
2. It will reply with your user ID

### 3. Set Up AWS S3 (Optional)
1. Create an S3 bucket in your preferred region
2. Add a lifecycle rule to delete objects after 1 day:
   - Go to bucket → Management → Lifecycle rules
   - Create rule: Apply to all objects
   - Action: Expire current versions after 1 day
3. Block all public access (default)
4. Create an IAM user with S3 access and get the credentials

### 4. Set Up YouTube Cookies (Optional but Recommended)
1. Install browser extension "Get cookies.txt LOCALLY" (Chrome/Firefox)
2. Visit youtube.com while logged in
3. Export cookies using the extension
4. Save the file as `cookies/cookies.txt` in the project directory

### 5. Configure
```bash
cp .env.example .env
# Edit .env with your settings
```

### 6. Run
```bash
docker compose up -d
```

### 7. Check Logs
```bash
docker compose logs -f
```

## Bot Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome message and usage info |
| `/help` | Show help and usage instructions |
| `/download <url>` | Download a YouTube video |
| `/update` | Update yt-dlp to the latest version |
| `/cookies` | Check YouTube cookies status or send a `cookies.txt` file |

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | (required) | Bot token from @BotFather |
| `ALLOWED_USER_IDS` | (required) | Comma-separated Telegram user IDs |
| `DOWNLOAD_DIR` | `/tmp/yt-downloads` | Temporary download directory |
| `MAX_VIDEO_DURATION_MINUTES` | `30` | Maximum video duration allowed |
| `CLEANUP_INTERVAL_MINUTES` | `60` | How often to run file cleanup |
| `MAX_FILE_AGE_MINUTES` | `60` | Delete files older than this |
| `S3_ENABLED` | `true` | Enable/disable S3 uploads |
| `S3_BUCKET_NAME` | (required if S3 enabled) | S3 bucket name |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_ACCESS_KEY_ID` | (from env/IAM) | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | (from env/IAM) | AWS secret key |
| `YOUTUBE_COOKIES_FILE` | `/app/cookies/cookies.txt` | Path to YouTube cookies file |
| `LOG_LEVEL` | `INFO` | Logging level |

## Troubleshooting

### Downloads failing
- Update yt-dlp: Send `/update` to the bot, or restart the container
- Refresh YouTube cookies: Re-export from your browser and copy to `cookies/cookies.txt`

### Video too large
- The bot auto re-encodes to fit Telegram's 50 MB limit
- Very long videos may not compress enough — reduce `MAX_VIDEO_DURATION_MINUTES`

### Bot not responding
- Check logs: `docker compose logs -f`
- Verify `TELEGRAM_BOT_TOKEN` is correct
- Verify your user ID is in `ALLOWED_USER_IDS`

## License
MIT
