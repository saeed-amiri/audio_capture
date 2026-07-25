#!/bin/bash

CHANNEL_URL="$1"
OUTPUT="videos.json"

if [ -z "$CHANNEL_URL" ]; then
    echo "Usage: ./fetch_channel_info.sh <channel_url>"
    exit 1
fi

yt-dlp --flat-playlist -J "$CHANNEL_URL" > playlist.json

# Extract video URLs from playlist
jq -r '.entries[].url' playlist.json > video_urls.txt

echo "[" > "$OUTPUT"
FIRST=true

while read -r VIDEO_ID; do
    VIDEO_URL="https://www.youtube.com/watch?v=$VIDEO_ID"
    META=$(yt-dlp -J "$CHANNEL_URL")

    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$OUTPUT"
    fi

    echo "$META" >> "$OUTPUT"
done < video_urls.txt

echo "]" >> "$OUTPUT"

echo "Saved full metadata to $OUTPUT"
