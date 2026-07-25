#!/bin/bash

MAX_JOBS=4
RUNNING=0

# Check if the file exists
if [ ! -f "video_urls.txt" ]; then
    echo "Error: video_urls.txt not found!"
    exit 1
fi

sanitize_title() {
    local s="$1"

    # 1. Convert umlauts and accents → ASCII
    # s="$(echo "$s" | iconv -f utf8 -t ascii//TRANSLIT)"

    # 2. Remove everything except letters, numbers, and spaces
    s="$(echo "$s" | sed 's/[^A-Za-z0-9 ]/ /g')"

    # 3. Collapse multiple spaces → one space
    s="$(echo "$s" | tr -s ' ')"

    # 4. Trim leading/trailing spaces
    s="$(echo "$s" | sed 's/^ *//; s/ *$//')"

    # 5. Replace spaces with underscores
    s="${s// /_}"

    echo "$s"
}



process_item() {
    local url=$1

    title=$(yt-dlp --print "%(title)s" "$url" 2>/dev/null)
    echo "$title"
    dir_name=$(sanitize_title "$title")
    echo $dir_name
}

while IFS= read -r url || [ -n "$url" ]; do
    process_item "$url" &
    ((RUNNING++))

    if (( RUNNING >= MAX_JOBS )); then
        wait -n   # wait for one job to finish
        ((RUNNING--))
    fi

done < "video_urls.txt"

wait   # wait for remaining jobs

echo "All done!"