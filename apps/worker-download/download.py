"""Download audio for each item listed in a discovery manifest.

Flow:
1. `load_manifest` reads the discovery manifest JSON produced by the
   discovery worker. Each item carries its own `overwrite_existing` flag,
   resolved by the discovery worker from `download.overwrite_existing` in
   `config/settings.yaml` at discovery time.
2. For each manifest item, `_download_single_item` resolves the item's
   output folder. If the folder already exists, it is skipped (and a
   warning is logged and printed) unless the item's `overwrite_existing`
   flag is set, in which case the folder is recreated. Otherwise the audio
   (plus optional thumbnail/description/subtitle files) is downloaded via
   yt-dlp, retrying up to `download.retry_count` times with
   `download.retry_backoff_seconds` between attempts.
3. `download_from_manifest` ties the above together and returns a
   `DownloadResult` summarizing the manifest path, output directory, and
   per-item download status.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any

from download_helpers import (
    DownloadedItem,
    DownloadResult,
    build_item_output_dir,
    build_yt_dlp_download_options,
    clear_existing_output_dir,
    item_already_downloaded,
    load_manifest,
)

__all__ = [
    "download_from_manifest",
    "load_manifest",
]

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None

# isort: off
# ROOT must be added to sys.path before importing config; keep these together
# so Ruff's import-sorter never hoists the import above the path mutation.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config_loader import load_config  # noqa: E402
# isort: on

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
LOGGER = logging.getLogger("download-worker")


def _skip_item(item: dict[str, Any], item_output_dir: Path) -> DownloadedItem:
    return DownloadedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        output_path=str(item_output_dir),
        status="skipped",
    )


def _handle_existing_output_dir(
    item: dict[str, Any], item_output_dir: Path
) -> DownloadedItem | None:
    """Check an already-populated output folder and decide what to do.

    Returns a "skipped" `DownloadedItem` if the folder should be left as is,
    or None if the caller should proceed with a fresh download (recreating
    the folder first when it already existed).
    """
    if not item_already_downloaded(item_output_dir):
        return None

    if not item.get("overwrite_existing", False):
        message = f"Folder already exists, skipping: {item_output_dir}"
        LOGGER.warning(message)
        print(f"[WARN] {message}")
        return _skip_item(item, item_output_dir)

    message = f"Folder already exists, recreating (overwrite_existing=True): {item_output_dir}"
    LOGGER.warning(message)
    print(f"[WARN] {message}")
    clear_existing_output_dir(item_output_dir)
    return None


def _fail_item(
    item: dict[str, Any], item_output_dir: Path, error: str
) -> DownloadedItem:
    return DownloadedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        output_path=str(item_output_dir),
        status="failed",
        error=error,
    )


def _download_with_retries(
    url: str, options: Any, retry_count: int, retry_backoff_seconds: float
) -> str | None:
    """Attempt the yt-dlp download, retrying on failure.

    Returns the error message on failure, or None on success.
    """
    last_error: str | None = None
    for attempt in range(1, retry_count + 1):
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([url])
        except (yt_dlp.utils.DownloadError, OSError, ValueError) as exc:
            last_error = str(exc)
            LOGGER.warning(
                "Attempt %d/%d failed for %s: %s", attempt, retry_count, url, exc
            )
            if attempt < retry_count:
                time.sleep(retry_backoff_seconds)
            continue
        else:
            return None

    return last_error


def _download_single_item(
    item: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> DownloadedItem:
    item_output_dir = build_item_output_dir(output_dir, item["folder_name"])
    download_cfg = config.get("download", {})

    skip_result = _handle_existing_output_dir(item, item_output_dir)
    if skip_result is not None:
        return skip_result

    if yt_dlp is None:
        LOGGER.error("yt-dlp is not installed, cannot download %s", item["url"])
        return _fail_item(item, item_output_dir, "yt-dlp is not installed")

    item_output_dir.mkdir(parents=True, exist_ok=True)
    options = build_yt_dlp_download_options(item_output_dir, config)
    error = _download_with_retries(
        item["url"],
        options,
        retry_count=download_cfg.get("retry_count", 3),
        retry_backoff_seconds=download_cfg.get("retry_backoff_seconds", 5),
    )

    if error is not None:
        return _fail_item(item, item_output_dir, error)

    LOGGER.info("Downloaded %s to %s", item["title"], item_output_dir)
    return DownloadedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        output_path=str(item_output_dir),
        status="downloaded",
    )


def download_from_manifest(
    manifest_path: Path,
    output_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> DownloadResult:
    effective_config = config or load_config()
    items = load_manifest(manifest_path)
    resolved_output_dir = output_dir or (ROOT / "data" / "jobs")

    LOGGER.info("Starting download for manifest %s", manifest_path)
    LOGGER.info("Downloading %d item(s) to %s", len(items), resolved_output_dir)

    downloaded_items = [
        _download_single_item(item, resolved_output_dir, effective_config)
        for item in items
    ]

    downloaded_count = sum(
        1 for item in downloaded_items if item.status == "downloaded"
    )
    LOGGER.info(
        "Finished download: %d downloaded, %d total", downloaded_count, len(items)
    )

    return DownloadResult(
        manifest_path=str(manifest_path),
        output_dir=str(resolved_output_dir),
        items=downloaded_items,
    )
