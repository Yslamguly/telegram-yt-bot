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

### 4. Set Up YouTube Cookies (Recommended)
YouTube often requires bot verification on cloud/datacenter IPs. You can provide cookies using either method:
- **Via Telegram Chat (Easiest):** After starting the bot, send `/cookies` to check status, or simply drag-and-drop your `cookies.txt` file directly into your Telegram chat with the bot.
- **Via File System:** Save the file as `cookies/cookies.txt` in the project directory before running `docker compose up -d`.

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
| `/cookies` | View current cookies status and instructions |
| `/users` | View all authorized usernames and IDs |
| `/authorize <@username or ID>` | Add a user to whitelist at runtime |
| `/deauthorize <@username or ID>` | Remove a user from whitelist at runtime |

## Managing YouTube Cookies

YouTube blocks anonymous automated requests on datacenter IPs with `"Sign in to confirm you're not a bot"`. Supplying authenticated cookies bypasses this block.

### Best Practice: Use a "Burner" Google Account
> [!IMPORTANT]
> **Never use your primary personal Google account.**
> Use a secondary "throwaway" Google account to export cookies. If YouTube ever flags automated downloading sessions, your primary email, drive, and personal data remain completely safe and unaffected.

### How to Export Cookies
1. Log into YouTube using a secondary/burner Google account in your web browser.
2. Install the extension **"Get cookies.txt LOCALLY"** ([Chrome](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) / [Firefox](https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/)).
3. Click the extension icon on an active YouTube tab and export in **Netscape** format as `cookies.txt`.

### How to Check and Update Cookies via Telegram (No SSH Needed)
You do not need to log into your server or restart Docker when cookies expire:

1. **Check Status:** Send `/cookies` in your chat with the bot.
   - The bot displays whether cookies are active, the file size, and the timestamp of the last update.
2. **Update Cookies:**
   - Attach and send your exported `cookies.txt` file as a document directly into the Telegram chat.
   - The bot validates the Netscape format and YouTube tokens.
   - If valid, it saves the file to `/app/cookies/cookies.txt` and replies with a confirmation.
   - The new cookies take effect immediately for all subsequent downloads.

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | (required) | Bot token from @BotFather |
| `ALLOWED_USERNAMES` | `""` | Comma-separated allowed usernames (e.g. `alice, @bob`) |
| `ALLOWED_USER_IDS` | `""` | Comma-separated allowed user IDs (at least one ID or username required) |
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
- Refresh YouTube cookies: Export from your browser and send `cookies.txt` as a document directly into the Telegram chat (or check `/cookies`).

### Video too large
- The bot auto re-encodes to fit Telegram's 50 MB limit
- Very long videos may not compress enough — reduce `MAX_VIDEO_DURATION_MINUTES`

### Bot not responding
- Check logs: `docker compose logs -f`
- Verify `TELEGRAM_BOT_TOKEN` is correct
- Verify your user ID is in `ALLOWED_USER_IDS`

## License
MIT
