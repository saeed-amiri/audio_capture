"""Metadata preparation and FFmpeg embedding for converted media files."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config_loader import load_config  # noqa: E402

FFMPEG_METADATA_KEYS = [
    "title",
    "artist",
    "album_artist",
    "album",
    "genre",
    "date",
    "year",
    "track",
    "disc",
    "composer",
    "copyright",
    "description",
    "comment",
    "language",
    "lang",
    "source",
    "url",
    "website",
    "publisher",
    "performer",
    "narrator",
    "author",
    "writer",
    "lyrics",
    "conductor",
    "subtitle",
    "mood",
]


def normalize_metadata_key(key: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")
    if not cleaned:
        return ""
    aliases = {
        "albumartist": "album_artist",
        "album_artist": "album_artist",
        "artist": "artist",
        "description": "description",
        "date": "date",
        "genre": "genre",
        "lang": "language",
        "language": "language",
        "source": "source",
        "url": "source",
        "website": "website",
        "narrator": "narrator",
        "encodedby": "encoded_by",
        "encoder": "encoder",
        "publisher": "publisher",
        "comment": "comment",
        "title": "title",
        "year": "year",
    }
    return aliases.get(cleaned, cleaned)


def _ffprobe_metadata(audio_path: Path) -> dict[str, str]:
    if not audio_path.exists():
        return {}

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(audio_path),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return {}

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}

    discovered: dict[str, str] = {}
    format_tags = payload.get("format", {}).get("tags", {}) or {}
    for key, value in format_tags.items():
        canonical = normalize_metadata_key(str(key))
        if canonical and canonical in FFMPEG_METADATA_KEYS:
            discovered[canonical] = str(value)

    for stream in payload.get("streams", []) or []:
        tags = stream.get("tags", {}) or {}
        for key, value in tags.items():
            canonical = normalize_metadata_key(str(key))
            if canonical and canonical in FFMPEG_METADATA_KEYS:
                if canonical not in discovered or not discovered[canonical]:
                    discovered[canonical] = str(value)

    if "language" not in discovered and "lang" in discovered:
        discovered["language"] = discovered["lang"]
    if "lang" not in discovered and "language" in discovered:
        discovered["lang"] = discovered["language"]

    return discovered


def find_cover_image(item_dir: Path) -> Path | None:
    if not item_dir.exists():
        return None

    preferred = [".webp", ".png", ".jpg", ".jpeg"]
    for suffix in preferred:
        matches = sorted(item_dir.glob(f"*{suffix}"))
        if matches:
            return matches[0]
    return None


def build_metadata_map(
    audio_path: Path | str | None = None,
    source_url: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    cover_path: Path | str | None = None,
    language: str | None = None,
    narrator: str | None = None,
    metadata_override: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    values: dict[str, str | None] = {key: None for key in FFMPEG_METADATA_KEYS}
    values["cover_path"] = str(cover_path) if cover_path else None
    if audio_path is not None:
        extracted = _ffprobe_metadata(Path(audio_path))
        for key, value in extracted.items():
            if key in values:
                values[key] = value
    if source_url:
        values["source"] = source_url
        values["url"] = source_url
    if title:
        values["title"] = title
    if artist:
        values["artist"] = artist
    if language:
        values["language"] = language
        values["lang"] = language
    if narrator:
        values["narrator"] = narrator
    if cover_path:
        values["cover_path"] = str(cover_path)

    if metadata_override:
        for key, value in metadata_override.items():
            canonical = normalize_metadata_key(str(key))
            if not canonical:
                continue
            if canonical == "cover_path":
                values["cover_path"] = str(value)
                continue
            values[canonical] = str(value) if value is not None else None

    return {key: value for key, value in values.items() if value is not None and str(value).strip()}


def build_ffmpeg_metadata_args(metadata_map: dict[str, Any]) -> list[str]:
    args: list[str] = []
    reserved_keys = {"encoder", "encoded_by"}
    for key in FFMPEG_METADATA_KEYS:
        if key not in metadata_map or key in reserved_keys:
            continue
        value = metadata_map[key]
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if key in {"source", "url", "website"}:
            args.extend(["-metadata", f"{key}={text}"])
        elif key == "cover_path":
            continue
        else:
            args.extend(["-metadata", f"{key}={text}"])
    return args


def build_ffmpeg_cover_args(metadata_map: dict[str, Any]) -> list[str]:
    cover_path = metadata_map.get("cover_path")
    if not cover_path:
        return []

    title = metadata_map.get("title") or metadata_map.get("album") or "Cover"
    artist = metadata_map.get("artist") or metadata_map.get("narrator") or "Unknown"
    comment = metadata_map.get("comment") or metadata_map.get("source") or "Attached cover"
    return [
        "-metadata:s:v:0",
        f"title={title}",
        "-metadata:s:v:0",
        f"artist={artist}",
        "-metadata:s:v:0",
        f"comment={comment}",
    ]


def prepare_cover_for_metadata(cover_path: str | Path | None, *, output_dir: Path | None = None) -> Path | None:
    if not cover_path:
        return None

    source = Path(cover_path)
    if not source.exists():
        return None

    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"}:
        return source

    target_dir = output_dir or source.parent
    target = target_dir / f"{source.stem}.jpg"
    if target.exists():
        return target

    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(target),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode == 0 and target.exists():
        return target

    fallback = target_dir / f"{source.stem}.png"
    fallback_command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-frames:v",
        "1",
        str(fallback),
    ]
    fallback_result = subprocess.run(fallback_command, check=False, capture_output=True, text=True)
    if fallback_result.returncode == 0 and fallback.exists():
        return fallback

    return None


def _filename_part(value: Any) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", str(value or "")).strip()
    return re.sub(r"\s+", "_", cleaned)


def default_output_name(metadata_map: dict[str, Any], audio_path: Path) -> str:
    """Default form: Title-Artist.mp3, spaces replaced by underscores."""
    parts = [_filename_part(metadata_map.get(key)) for key in ("title", "artist")]
    stem = "-".join(part for part in parts if part)
    return (stem or audio_path.stem) + (audio_path.suffix or ".mp3")


def resolve_output_path(manifest: dict[str, Any]) -> Path:
    audio_path = Path(manifest["audio_path"])
    name = Path(str(manifest.get("output_name") or "")).name
    if not name:
        name = default_output_name(manifest["metadata"], audio_path)
    elif not Path(name).suffix:
        name += audio_path.suffix
    return audio_path.with_name(name)


def create_metadata_manifest(
    item: dict[str, Any],
    output_dir: Path,
    source_url: str | None = None,
    cover_path: Path | str | None = None,
    metadata_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item_output_dir = output_dir / str(item.get("folder_name", ""))
    audio_path = Path(item.get("output_path") or item.get("input_path") or item_output_dir)
    if not cover_path:
        cover_path = find_cover_image(item_output_dir)

    metadata = build_metadata_map(
        audio_path=audio_path,
        source_url=source_url or item.get("url"),
        title=str(item.get("title") or ""),
        artist=None,
        cover_path=cover_path,
        metadata_override=metadata_override,
    )

    manifest = {
        "item_index": int(item.get("index", 0) or 0),
        "folder_name": item.get("folder_name"),
        "video_id": item.get("video_id"),
        "title": metadata.get("title") or item.get("title"),
        "source_url": metadata.get("source") or source_url or item.get("url"),
        "audio_path": str(audio_path),
        "output_name": default_output_name(metadata, audio_path),
        "cover_path": str(cover_path) if cover_path else None,
        "ffmpeg_metadata_fields": FFMPEG_METADATA_KEYS,
        "metadata": metadata,
    }

    return manifest


def write_root_manifest(output_dir: Path, manifests: list[dict[str, Any]]) -> Path:
    """Overwrite the single metadata manifest with exactly the items of this run."""
    path = output_dir / "metadata_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"output_dir": str(output_dir), "items": manifests}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_reviewed_manifests(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Edited metadata manifest '{path}' is not valid JSON: {exc}") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not all(
        isinstance(i, dict) and i.get("audio_path") and isinstance(i.get("metadata"), dict) for i in items
    ):
        raise ValueError(f"Edited metadata manifest '{path}' needs an 'items' list with 'audio_path' and 'metadata'")
    return items


def build_ffmpeg_command(
    audio_path: Path,
    output_path: Path,
    metadata_map: dict[str, Any],
) -> list[str]:
    input_path = Path(audio_path)
    cover_path = metadata_map.get("cover_path")
    command: list[str] = ["ffmpeg", "-y", "-i", str(input_path)]
    if cover_path:
        command.extend(["-i", str(cover_path)])
        command.extend([
            "-map",
            "0:a:0",
            "-map",
            "1:v:0",
            "-map_metadata",
            "0",
            "-c:a",
            "copy",
            "-c:v",
            "mjpeg",
            "-write_id3v2",
            "1",
            "-id3v2_version",
            "3",
            "-disposition:v:0",
            "attached_pic",
        ])
    else:
        command.extend([
            "-map",
            "0:a:0",
            "-map_metadata",
            "0",
            "-write_id3v2",
            "1",
            "-id3v2_version",
            "3",
        ])

    command.extend(build_ffmpeg_metadata_args(metadata_map))
    command.extend(build_ffmpeg_cover_args(metadata_map))
    command.append(str(output_path))
    return command


def review_metadata_manifest(
    manifest_path: Path,
    *,
    prompt_text: str | None = None,
    interactive: bool | None = None,
) -> bool:
    """Ask the user to review or edit the metadata manifest before embedding tags."""
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        return True

    path = str(manifest_path)
    print(f"\nMetadata manifest created: {path}")
    print("Press Enter or type 'y' to continue, 'n' to skip, or 'e' to edit it now.")
    answer = input(prompt_text or "Apply metadata now? [Y/n/e]: ").strip().lower()

    if answer in {"", "y", "yes"}:
        return True
    if answer in {"n", "no"}:
        return False
    if answer in {"e", "edit"}:
        editor = os.environ.get("EDITOR") or "nano"
        subprocess.run(f"{editor} {path}", shell=True, check=False)
        follow_up = input("Finished editing? Press Enter or type 'y' to continue, 'n' to skip: ").strip().lower()
        if follow_up in {"", "y", "yes"}:
            return True
        return False
    return True


def apply_metadata_to_file(manifest: dict[str, Any]) -> dict[str, Any]:
    audio_path = Path(manifest["audio_path"])
    cover_path = manifest["metadata"].get("cover_path")
    prepared_cover = prepare_cover_for_metadata(cover_path, output_dir=audio_path.parent)
    if prepared_cover:
        manifest["metadata"]["cover_path"] = str(prepared_cover)
        manifest["cover_path"] = str(prepared_cover)

    target_path = resolve_output_path(manifest)
    temp_path = target_path.with_name(f"{target_path.stem}.metadata{target_path.suffix}")
    command = build_ffmpeg_command(audio_path, temp_path, manifest["metadata"])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg metadata application failed")

    temp_path.replace(target_path)
    return manifest


def copy_manifest_to_target_dir(manifest: dict[str, Any]) -> Path:
    path = resolve_output_path(manifest).parent / "metadata_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_conversion_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    with manifest_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError(f"Manifest '{manifest_path}' must be a conversion manifest containing an 'items' list")
    return payload["items"]


def metadata_from_conversion_manifest(
    manifest_path: Path,
    output_dir: Path | None = None,
    config: dict[str, Any] | None = None,
    interactive: bool = True,
) -> list[dict[str, Any]]:
    effective_config = config or load_config()
    items = read_conversion_manifest(manifest_path)
    resolved_output_dir = Path(output_dir or effective_config.get("paths", {}).get("jobs_root", "data/jobs"))

    manifests = [
        create_metadata_manifest(
            item=item,
            output_dir=resolved_output_dir,
            source_url=item.get("url"),
            cover_path=find_cover_image(resolved_output_dir / str(item.get("folder_name", ""))),
        )
        for item in items
    ]
    root_path = write_root_manifest(resolved_output_dir, manifests)
    generated_names = {m["audio_path"]: m["output_name"] for m in manifests}

    if interactive:
        if not review_metadata_manifest(root_path, interactive=True):
            return manifests
        manifests = load_reviewed_manifests(root_path)
        # A name left at its generated default follows edited title/artist.
        for reviewed in manifests:
            generated_name = generated_names.get(reviewed["audio_path"])
            if generated_name is not None and reviewed.get("output_name") in (None, "", generated_name):
                reviewed["output_name"] = default_output_name(reviewed["metadata"], Path(reviewed["audio_path"]))
        write_root_manifest(resolved_output_dir, manifests)

    for manifest in manifests:
        apply_metadata_to_file(manifest)
        copy_manifest_to_target_dir(manifest)
    return manifests
