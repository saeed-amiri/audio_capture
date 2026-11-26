# Folder Architecture

This layout supports channel jobs and single-video jobs with the same pipeline.

## Root

- apps/: application services and workers
- docker/: one subdirectory per service, each containing its Dockerfile
- docker-compose.yml: compose definition in root
- config/: runtime constants shared by all services
- .github/workflows/: standard GitHub Actions CI/CD workflows
- data/: persistent outputs
- ops/: operational scripts and backups
- docs/: architecture and runbooks

## Config Layout

- config/settings.yaml: default runtime config
- config/settings.local.example.yaml: optional override template

All containers mount config read-only at /app/config and use CONFIG_FILE=/app/config/settings.yaml.

## Docker Layout

- docker/api/Dockerfile
- docker/ui-streamlit/Dockerfile
- docker/worker-discovery/Dockerfile
- docker/worker-download/Dockerfile
- docker/worker-convert/Dockerfile
- docker/worker-metadata/Dockerfile
- docker/worker-telegram-prep/Dockerfile
- docker/worker-transcript/Dockerfile

## Services

- apps/api
- apps/ui-streamlit
- apps/worker-discovery
- apps/worker-download
- apps/worker-convert
- apps/worker-telegram-prep
- apps/worker-transcript
- apps/worker-metadata

## Data

- data/jobs/<job_id>/manifest
- data/jobs/<job_id>/items/<item_folder>/raw
- data/jobs/<job_id>/items/<item_folder>/meta
- data/jobs/<job_id>/items/<item_folder>/converted
- data/jobs/<job_id>/items/<item_folder>/publish
- data/jobs/<job_id>/items/<item_folder>/logs
- data/jobs/<job_id>/reports
- data/shared/cache
- data/shared/tmp

## Transcript Worker Scope

The transcript worker tries to collect subtitle/transcript artifacts for each item when available from YouTube and stores them under:

- data/jobs/<job_id>/items/<item_folder>/meta/subtitles.<lang>.vtt
- data/jobs/<job_id>/items/<item_folder>/meta/transcript.txt

## Metadata Worker Scope

The metadata worker reads `conversion_manifest.json` and tags each converted audio file (ID3 tags plus cover art) with FFmpeg. It uses one manifest as the source of truth:

- data/jobs/metadata_manifest.json: rewritten on every run, reviewed/edited by the user, then re-read and applied
- data/jobs/<item_folder>/<output_name>: tagged file (default `Title-Artist.mp3`); the source file is kept
- data/jobs/<item_folder>/metadata_manifest.json: copy of the reviewed entry, written after tagging

The compose service mounts `${HOME}/Musik` read-only at the same path so cover images stored there are visible inside the container.
