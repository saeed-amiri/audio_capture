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
