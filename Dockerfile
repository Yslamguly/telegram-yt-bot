FROM python:3.12-slim

# Install system dependencies (ffmpeg and Node.js)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Deno JS runtime (recommended by yt-dlp for EJS challenges)
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY bot/ bot/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create downloads directory
RUN mkdir -p /tmp/yt-downloads

ENTRYPOINT ["./entrypoint.sh"]
