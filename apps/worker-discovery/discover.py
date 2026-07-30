import json
import logging
import re
import sys
import urllib.parse
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

config_loader = import_module("config.config_loader")
load_config = config_loader.load_config
validate_required_mapping_fields = config_loader.validate_required_mapping_fields

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


def sanitize_title(title: str, config: dict[str, Any] | None = None) -> str:
    if not title:
        return "untitled"

    title = title.strip()
    title = title.replace("ß", "ss")
    title = title.replace("ä", "a")
    title = title.replace("ö", "o")
    title = title.replace("ü", "u")
    title = title.replace("Ä", "A")
    title = title.replace("Ö", "O")
    title = title.replace("Ü", "U")
    title = title.replace("ï", "i")
    title = title.replace("ë", "e")

    replacement = "_"
    if config:
        naming = config.get("naming", {})
        replacement = naming.get("replace_whitespace_with", replacement)

    title = re.sub(r"[^A-Za-z0-9]+", replacement, title)
    title = re.sub(rf"{re.escape(replacement)}+", replacement, title).strip(replacement)
    return title or "untitled"


def build_item_folder_name(
    index: int,
    video_id: str,
    title: str,
    config: dict[str, Any] | None = None,
) -> str:
    effective_config = config or load_config()
    validate_required_mapping_fields(
        effective_config,
        "naming",
        {"item_folder_pattern", "safe_title_max_length", "replace_whitespace_with"},
        Path("config/settings.yaml"),
    )
    naming = effective_config.get("naming", {})
    pattern = naming.get("item_folder_pattern", "{index:04d}__{video_id}__{safe_title}")
    safe_title = sanitize_title(title, config=effective_config)
    safe_title = safe_title[: naming.get("safe_title_max_length", 80)]
    return pattern.format(
        index=index,
        video_id=video_id,
        safe_title=safe_title,
        title=title,
    )


def normalize_source_url(url: str) -> str:
    return url.strip()


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


def build_manifest_entry(
    index: int,
    video_id: str,
    title: str,
    url: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_config = config or load_config()
    return {
        "index": index,
        "video_id": video_id,
        "title": title,
        "url": url,
        "folder_name": build_item_folder_name(
            index, video_id, title, config=effective_config
        ),
        "source_type": "single",
    }


def create_manifest(items: list[dict[str, Any]], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(items, handle, ensure_ascii=False, indent=2)
    return output_path


def discover_from_url(
    url: str,
    output_path: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_config = config or load_config()
    source_type = detect_source_type(url)
    normalized_url = normalize_source_url(url)

    LOGGER.info("Starting discovery for %s", normalized_url)
    LOGGER.info("Detected source type: %s", source_type)

    if source_type == "single":
        video_id = "unknown"
        title = _get_video_title(normalized_url)
        title = sanitize_title(title, config=effective_config)
        item = build_manifest_entry(
            1, video_id, title, normalized_url, config=effective_config
        )
        items = [item]
    elif source_type == "search":
        title = _get_search_result_title(normalized_url)
        title = sanitize_title(title, config=effective_config)
        item = build_manifest_entry(
            1, "unknown", title, normalized_url, config=effective_config
        )
        items = [item]
    else:
        items = [
            build_manifest_entry(
                1,
                "unknown",
                "placeholder_title",
                normalized_url,
                config=effective_config,
            )
        ]

    output = output_path or (ROOT / "data" / "jobs" / "discovery_manifest.json")
    create_manifest(items, output)
    LOGGER.info("Created manifest with %d item(s) at %s", len(items), output)

    return {
        "source_type": source_type,
        "source_url": normalized_url,
        "items": items,
        "manifest_path": str(output),
    }
