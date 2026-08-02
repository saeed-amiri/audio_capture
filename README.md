# audio_capture

Pipeline for discovering, downloading, converting, transcribing, and preparing
YouTube audio for Telegram delivery. Each stage is an independent worker that
reads/writes JSON files under `data/jobs/` and shares configuration from
`config/settings.yaml`.

## Configuration

All workers read `config/settings.yaml` by default. Override the path with the
`CONFIG_FILE` environment variable, or pass an explicit path where supported.

Relevant settings for the workers below (`config/settings.yaml`):

```yaml
naming:
  item_folder_pattern: "{index:04d}__{video_id}__{safe_title}"
  safe_title_max_length: 80
  replace_whitespace_with: "_"

download:
  retry_count: 3
  retry_backoff_seconds: 5
  overwrite_existing: false   # if true, existing item folders are recreated instead of skipped
  audio_format_selector: bestaudio
  write_thumbnail: true
  write_info_json: true
  write_description: true
  write_subtitles: true
  subtitle_languages: [de, en]

conversion:
  enabled: false
  target_format: mp3
  bitrate_kbps: 192
  remove_original_format: false  # if true, delete source audio after successful conversion

transcript:
  enabled: true
  prefer_manual_subtitles: true
  fallback_to_auto_subtitles: true
  output_text_file: transcript.txt
```

## worker-discovery

Resolves a YouTube URL (single video, search results, playlist, or channel)
into a discovery manifest: a JSON array of items with `index`, `video_id`,
`title`, `url`, `folder_name`, `source_type`, and `overwrite_existing`
(copied from `download.overwrite_existing` at discovery time).

Source: [apps/worker-discovery](apps/worker-discovery)

### Run with Docker directly

```bash
docker build -f docker/worker-discovery/Dockerfile -t audio-capture-discovery .

docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config:/app/config:ro" \
  -e CONFIG_FILE=/app/config/settings.yaml \
  audio-capture-discovery \
  python /app/apps/worker-discovery/main.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

The manifest is written to `data/jobs/discovery_manifest.json` by default.
Pass `--output /app/data/jobs/<name>.json` to change it.

### Run with Docker Compose

```bash
docker compose run --rm worker-discovery "https://www.youtube.com/watch?v=VIDEO_ID"
```

## worker-download

Reads a discovery manifest and downloads each item's audio via yt-dlp
(plus optional thumbnail/description/subtitles), writing into
`data/jobs/<folder_name>/`. Existing folders are skipped with a warning
unless the manifest item's `overwrite_existing` flag is set, in which case
the folder is recreated.

Source: [apps/worker-download](apps/worker-download)

### Run with Docker directly

```bash
docker build -f docker/worker-download/Dockerfile -t audio-capture-download .

docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config:/app/config:ro" \
  -e CONFIG_FILE=/app/config/settings.yaml \
  audio-capture-download \
  python /app/apps/worker-download/main.py /app/data/jobs/discovery_manifest.json
```

Pass `--output-dir /app/data/jobs` to change where items are downloaded to
(defaults to `data/jobs`).

### Run with Docker Compose

```bash
docker compose run --rm worker-download /app/data/jobs/discovery_manifest.json
```

## worker-convert

Reads a discovery manifest and converts each downloaded item's source audio
inside the same item folder (`data/jobs/<folder_name>/`) into the configured
target format.

By default, the source audio file is kept. Set
`conversion.remove_original_format: true` to delete the source file after a
successful conversion.

Source: [apps/worker-convert](apps/worker-convert)

### Run with Docker directly

```bash
docker build -f docker/worker-convert/Dockerfile -t audio-capture-convert .

docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config:/app/config:ro" \
  -e CONFIG_FILE=/app/config/settings.yaml \
  audio-capture-convert \
  python /app/apps/worker-convert/main.py /app/data/jobs/discovery_manifest.json
```

Pass `--output-dir /app/data/jobs` to point at a different jobs directory.
By default, worker-convert also writes a summary JSON file to
`<output-dir>/conversion_manifest.json`.
Override this with `--manifest-output /app/data/jobs/my_conversion_manifest.json`.

### Run with Docker Compose

```bash
docker compose run --rm worker-convert /app/data/jobs/discovery_manifest.json
```

## worker-transcript

Reads a conversion manifest and produces a transcript file for each item folder.
For each item it looks for:

1. an existing transcript file (already transcribed, skipped)
2. existing subtitle files in the item folder (`.vtt`, `.srt`, `.txt`), written into the
   transcript file as-is
3. otherwise, it fetches captions directly from the item's source URL via yt-dlp:
   manual subtitles first (if `transcript.prefer_manual_subtitles` is enabled), then
   auto-generated captions as a fallback (if `transcript.fallback_to_auto_subtitles` is
   enabled), using `download.subtitle_languages` for the language preference

The worker writes a summary JSON file to `<output-dir>/transcript_manifest.json`.

Source: [apps/worker-transcript](apps/worker-transcript)

### Run with Docker directly

```bash
docker build -f docker/worker-transcript/Dockerfile -t audio-capture-transcript .

docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config:/app/config:ro" \
  -e CONFIG_FILE=/app/config/settings.yaml \
  audio-capture-transcript \
  python /app/apps/worker-transcript/main.py /app/data/jobs/conversion_manifest.json
```

Pass `--output-dir /app/data/jobs` to point at a different jobs directory.
Override the output manifest with `--manifest-output /app/data/jobs/my_transcript_manifest.json`.

### Run with Docker Compose

```bash
docker compose run --rm worker-transcript /app/data/jobs/conversion_manifest.json
```

## Typical end-to-end flow

```bash
docker compose run --rm worker-discovery "https://www.youtube.com/watch?v=VIDEO_ID"
docker compose run --rm worker-download /app/data/jobs/discovery_manifest.json
docker compose run --rm worker-convert /app/data/jobs/discovery_manifest.json
docker compose run --rm worker-transcript /app/data/jobs/conversion_manifest.json
```

## Local development (without Docker)

```bash
uv sync
uv run python apps/worker-discovery/main.py "https://www.youtube.com/watch?v=VIDEO_ID"
uv run python apps/worker-download/main.py data/jobs/discovery_manifest.json
uv run python apps/worker-convert/main.py data/jobs/conversion_manifest.json
uv run python apps/worker-transcript/main.py data/jobs/conversion_manifest.json
uv run pytest -q tests/
uv run ruff check .
```
