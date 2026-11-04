FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

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
