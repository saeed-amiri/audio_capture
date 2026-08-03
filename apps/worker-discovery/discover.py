"""Discover videos from a YouTube URL and write a discovery manifest.

Flow:
1. `detect_source_type` classifies the URL as single/search/playlist/channel.
2. `find_next_index` scans the manifest's output directory for existing item
   folders (named "<index>__<video_id>__<title>") and picks the next free
   index, so folders created across separate discovery runs stay ordered
   and never collide.
3. For "single"/"search" URLs, the real title is resolved via yt-dlp, falling
   back to scraping the page HTML if yt-dlp is unavailable or fails.
4. `build_manifest_entry` turns each resolved (or placeholder) item into a
   validated `ManifestEntry` (including a `discovered_at` timestamp), using
   `config/settings.yaml` naming rules.
5. `create_manifest` writes the entries to a JSON manifest file on disk.
6. `discover_from_url` ties the above together and returns a `DiscoveryResult`
   summarizing the source type, URL, items, and manifest path.
"""

import json
import logging
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from discover_helpers import (
    DiscoveryResult,
    ManifestEntry,
    build_item_folder_name,
    build_manifest_entry,
    find_next_index,
    normalize_source_type,
    normalize_source_url,
    sanitize_title,
)

__all__ = [
    "build_item_folder_name",
    "build_manifest_entry",
    "detect_source_type",
    "discover_from_url",
    "normalize_source_url",
    "sanitize_title",
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
LOGGER = logging.getLogger("discovery-worker")


def detect_source_type(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    query = urllib.parse.parse_qs(parsed.query)

    if "youtube.com" in host or "www.youtube.com" in host or "youtu.be" in host:
        if "/playlist" in path:
            return "playlist"
        if "/channel/" in path or path.startswith("/@"):
            return "channel"
        if path.startswith("/results") and "search_query" in query:
            return "search"
        if "v" in query or path.startswith("/watch"):
            return "single"

    return "single (guessed)"



def _extract_title_from_html(html: str) -> str | None:
    for pattern in [
        r'<meta property="og:title" content="([^"]+)"',
        r'<meta name="title" content="([^"]+)"',
        r"<title>(.*?)</title>",
    ]:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title:
                return title
    return None


def _build_yt_dlp_options(*, extract_flat: bool = False) -> Any:
    options: dict[str, Any] = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
    }
    if extract_flat:
        options["extract_flat"] = True
    return options


def _fetch_page_html(url: str) -> str | None:
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, ValueError):
        return None


def _get_video_title(url: str) -> str:
    if yt_dlp is not None:
        try:
            with yt_dlp.YoutubeDL(_build_yt_dlp_options()) as downloader:
                info = downloader.extract_info(url, download=False)
        except (ValueError, TypeError, KeyError):
            info = None
        else:
            if isinstance(info, dict):
                title = info.get("title")
                if isinstance(title, str) and title.strip():
                    return title.strip()

    html = _fetch_page_html(url)
    if html is None:
        return "unknown"

    return _extract_title_from_html(html) or "unknown"


def _get_search_result_title(url: str) -> str:
    if yt_dlp is not None:
        try:
            with yt_dlp.YoutubeDL(_build_yt_dlp_options(extract_flat=True)) as downloader:
                info = downloader.extract_info(url, download=False)
        except (ValueError, TypeError, KeyError):
            info = None
        else:
            if isinstance(info, dict):
                for entry in info.get("entries") or []:
                    if isinstance(entry, dict):
                        title = entry.get("title")
                        if isinstance(title, str) and title.strip():
                            return title.strip()

    html = _fetch_page_html(url)
    if html is None:
        return "unknown"

    for pattern in [r'href="/watch\?v=([^"&]+)"', r'/watch\?v=([^"&]+)']:
        match = re.search(pattern, html)
        if match:
            watch_url = f"https://www.youtube.com/watch?v={match.group(1)}"
            title = _get_video_title(watch_url)
            if title != "unknown":
                return title

    return "unknown"


def _get_playlist_items(url: str) -> dict[str, Any] | None:
    if yt_dlp is not None:
        try:
            with yt_dlp.YoutubeDL(_build_yt_dlp_options(extract_flat=True)) as downloader:
                info = downloader.extract_info(url, download=False)
        except (ValueError, TypeError, KeyError):
            info = None
        else:
            if isinstance(info, dict):
                entries = info.get("entries") or []
                if isinstance(entries, list):
                    return {
                        "title": info.get("title") or "playlist",
                        "entries": [
                            {
                                "id": entry.get("id") if isinstance(entry, dict) else None,
                                "title": entry.get("title") if isinstance(entry, dict) else None,
                                "url": entry.get("url") if isinstance(entry, dict) else None,
                            }
                            for entry in entries
                            if isinstance(entry, dict)
                        ],
                    }

    return None


def create_manifest(items: list[ManifestEntry], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump([item.model_dump() for item in items], handle, ensure_ascii=False, indent=2)
    return output_path


def _build_single_video_items(
    index: int, url: str, config: dict[str, Any]
) -> list[ManifestEntry]:
    title = sanitize_title(_get_video_title(url), config=config)
    return [
        build_manifest_entry(
            index, "unknown", title, url, config=config, source_type="single"
        )
    ]


def _build_search_result_items(
    index: int, url: str, config: dict[str, Any]
) -> list[ManifestEntry]:
    title = sanitize_title(_get_search_result_title(url), config=config)
    return [
        build_manifest_entry(
            index, "unknown", title, url, config=config, source_type="search"
        )
    ]


def _build_playlist_items(index: int, url: str, config: dict[str, Any]) -> list[ManifestEntry]:
    playlist_info = _get_playlist_items(url)
    if not isinstance(playlist_info, dict):
        return _build_placeholder_items(index, url, "playlist", config)

    playlist_title = str(playlist_info.get("title") or "playlist").strip() or "playlist"
    safe_playlist_title = sanitize_title(playlist_title, config=config)
    entries = playlist_info.get("entries") or []
    if not isinstance(entries, list):
        return _build_placeholder_items(index, url, "playlist", config)

    items: list[ManifestEntry] = []
    for offset, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or entry.get("video_id") or "unknown")
        title = str(entry.get("title") or "untitled")
        entry_url = str(entry.get("url") or url)
        entry_index = index + offset - 1
        entry_folder_name = f"{safe_playlist_title}/{build_item_folder_name(entry_index, video_id, title, config=config)}"
        item = build_manifest_entry(
            entry_index,
            video_id,
            title,
            entry_url,
            config=config,
            source_type="playlist",
        )
        item.folder_name = entry_folder_name
        items.append(item)

    return items or _build_placeholder_items(index, url, "playlist", config)


def _build_channel_items(index: int, url: str, config: dict[str, Any]) -> list[ManifestEntry]:
    channel_info = _get_playlist_items(url)
    if not isinstance(channel_info, dict):
        return _build_placeholder_items(index, url, "channel", config)

    channel_title = str(channel_info.get("title") or "channel").strip() or "channel"
    safe_channel_title = sanitize_title(channel_title, config=config)
    entries = channel_info.get("entries") or []
    if not isinstance(entries, list):
        return _build_placeholder_items(index, url, "channel", config)

    items: list[ManifestEntry] = []
    for offset, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or entry.get("video_id") or "unknown")
        title = str(entry.get("title") or "untitled")
        entry_url = str(entry.get("url") or url)
        entry_index = index + offset - 1
        entry_folder_name = f"{safe_channel_title}/{build_item_folder_name(entry_index, video_id, title, config=config)}"
        item = build_manifest_entry(
            entry_index,
            video_id,
            title,
            entry_url,
            config=config,
            source_type="channel",
        )
        item.folder_name = entry_folder_name
        items.append(item)

    return items or _build_placeholder_items(index, url, "channel", config)


def _build_placeholder_items(
    index: int, url: str, source_type: str, config: dict[str, Any]
) -> list[ManifestEntry]:
    return [
        build_manifest_entry(
            index,
            "unknown",
            "placeholder_title",
            url,
            config=config,
            source_type=source_type,
        )
    ]


def _build_items_for_source(
    source_type: str, url: str, config: dict[str, Any], index: int
) -> list[ManifestEntry]:
    if source_type == "single":
        return _build_single_video_items(index, url, config)
    if source_type == "search":
        return _build_search_result_items(index, url, config)
    if source_type == "playlist":
        return _build_playlist_items(index, url, config)
    if source_type == "channel":
        return _build_channel_items(index, url, config)
    return _build_placeholder_items(index, url, source_type, config)


def discover_from_url(
    url: str,
    output_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> DiscoveryResult:
    effective_config = config or load_config()
    source_type = detect_source_type(url)
    normalized_url = normalize_source_url(url)

    LOGGER.info("Starting discovery for %s", normalized_url)
    LOGGER.info("Detected source type: %s", source_type)

    output = output_path or (ROOT / "data" / "jobs" / "discovery_manifest.json")
    start_index = find_next_index(output.parent)
    LOGGER.info("Next available item index: %d", start_index)

    items = _build_items_for_source(
        source_type, normalized_url, effective_config, start_index
    )

    create_manifest(items, output)
    LOGGER.info("Created manifest with %d item(s) at %s", len(items), output)

    return DiscoveryResult(
        source_type=normalize_source_type(source_type),
        source_url=normalized_url,
        items=items,
        manifest_path=str(output),
    )
