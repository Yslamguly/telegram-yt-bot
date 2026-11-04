#!/bin/bash
set -e

echo "========================================"
echo " Telegram YouTube Downloader Bot"
echo "========================================"
echo ""
echo "Updating yt-dlp to latest version..."
pip install --upgrade --quiet yt-dlp
echo "yt-dlp version: $(yt-dlp --version)"
echo ""
echo "Starting bot..."
exec python -m bot.main
