"""Convert downloaded audio files for items listed in a discovery manifest.

Flow:
1. `load_manifest` reads the discovery manifest JSON produced by the discovery
   worker.
2. For each item, `_convert_single_item` scans the item's existing download
   folder under `data/jobs/<folder_name>/`, picks one convertible audio file,
   and writes the converted file into the same folder using the configured
   target format and bitrate.
3. If `conversion.remove_original_format` is true, the original source audio
   file is removed only after a successful conversion. By default this is
   false, so the original source file remains in place.
4. `convert_from_manifest` ties the above together and returns a
   `ConversionResult` summarizing the manifest path, output directory, and
   per-item conversion status.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from convert_helpers import (
    ConversionResult,
    ConvertedItem,
    build_conversion_input,
    build_item_output_dir,
    find_convertible_audio_file,
    find_existing_target_file,
    load_manifest,
    normalize_item_file_names,
)

__all__ = ["convert_from_manifest", "create_conversion_manifest", "load_manifest"]

# isort: off
# ROOT must be added to sys.path before importing config; keep these together
# so Ruff's import-sorter never hoists the import above the path mutation.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config_loader import load_config  # noqa: E402
# isort: on

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
LOGGER = logging.getLogger("convert-worker")


def _skip_item(
    item: dict[str, Any], input_path: Path, output_path: Path
) -> ConvertedItem:
    return ConvertedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        input_path=str(input_path),
        output_path=str(output_path),
        status="skipped",
        removed_original=False,
    )


def _skip_item_disabled(item: dict[str, Any], item_output_dir: Path) -> ConvertedItem:
    return ConvertedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        input_path=str(item_output_dir),
        output_path=str(item_output_dir),
        status="skipped",
        removed_original=False,
    )


def _fail_item(
    item: dict[str, Any], item_output_dir: Path, error: str
) -> ConvertedItem:
    return ConvertedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        input_path=str(item_output_dir),
        output_path=str(item_output_dir),
        status="failed",
        removed_original=False,
        error=error,
    )


def _build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    bitrate_kbps: int,
) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-b:a",
        f"{bitrate_kbps}k",
        str(output_path),
    ]


def _run_ffmpeg(command: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    stderr = (result.stderr or "").strip()
    return result.returncode, stderr


def _build_target_file_path(item: dict[str, Any], item_output_dir: Path, target_format: str) -> Path:
    folder_name = str(item.get("folder_name", ""))
    parts = folder_name.split("__", 2)
    if len(parts) == 3 and parts[2]:
        base_name = parts[2]
    else:
        title = str(item.get("title", "untitled"))
        base_name = "_".join(title.split()) or "untitled"

    return item_output_dir / f"{base_name}.{target_format}"


def _convert_single_item(
    item: dict[str, Any], output_dir: Path, config: dict[str, Any]
) -> ConvertedItem:
    item_output_dir = build_item_output_dir(output_dir, item["folder_name"])
    if not item_output_dir.exists():
        return _fail_item(item, item_output_dir, f"Item folder does not exist: {item_output_dir}")

    normalize_item_file_names(item_output_dir)

    conversion_input = build_conversion_input(config)
    existing_target = find_existing_target_file(
        item_output_dir, conversion_input.target_format
    )
    input_path = find_convertible_audio_file(
        item_output_dir, conversion_input.target_format
    )

    if existing_target is not None and input_path is None:
        LOGGER.info("Already converted, skipping: %s", existing_target)
        return _skip_item(item, existing_target, existing_target)

    if input_path is None:
        return _fail_item(
            item,
            item_output_dir,
            (
                "No convertible audio source file found in "
                f"{item_output_dir} for target format "
                f"'{conversion_input.target_format}'"
            ),
        )

    output_path = _build_target_file_path(
        item,
        item_output_dir,
        conversion_input.target_format,
    )
    command = _build_ffmpeg_command(
        input_path=input_path,
        output_path=output_path,
        bitrate_kbps=conversion_input.bitrate_kbps,
    )

    return_code, stderr = _run_ffmpeg(command)
    if return_code != 0:
        error = stderr or "ffmpeg conversion failed"
        return _fail_item(item, item_output_dir, error)

    removed_original = False
    if conversion_input.remove_original_format and input_path != output_path:
        input_path.unlink(missing_ok=True)
        removed_original = True

    LOGGER.info("Converted %s to %s", input_path.name, output_path.name)
    return ConvertedItem(
        index=item["index"],
        video_id=item["video_id"],
        title=item["title"],
        url=item["url"],
        folder_name=item["folder_name"],
        input_path=str(input_path),
        output_path=str(output_path),
        status="converted",
        removed_original=removed_original,
    )


def create_conversion_manifest(result: ConversionResult, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(result.model_dump(), handle, ensure_ascii=False, indent=2)
    return output_path


def convert_from_manifest(
    manifest_path: Path,
    output_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> ConversionResult:
    effective_config = config or load_config()
    items = load_manifest(manifest_path)
    resolved_output_dir = output_dir or (ROOT / "data" / "jobs")

    conversion_cfg = effective_config.get("conversion", {})
    if not conversion_cfg.get("enabled", False):
        LOGGER.warning("Conversion is disabled by config (conversion.enabled=false)")
        skipped_items = [
            _skip_item_disabled(
                item,
                build_item_output_dir(resolved_output_dir, item["folder_name"]),
            )
            for item in items
        ]
        return ConversionResult(
            manifest_path=str(manifest_path),
            output_dir=str(resolved_output_dir),
            items=skipped_items,
        )

    LOGGER.info("Starting conversion for manifest %s", manifest_path)
    LOGGER.info("Converting %d item(s) in %s", len(items), resolved_output_dir)

    converted_items = [
        _convert_single_item(item, resolved_output_dir, effective_config)
        for item in items
    ]

    converted_count = sum(1 for item in converted_items if item.status == "converted")
    LOGGER.info(
        "Finished conversion: %d converted, %d total", converted_count, len(items)
    )

    return ConversionResult(
        manifest_path=str(manifest_path),
        output_dir=str(resolved_output_dir),
        items=converted_items,
    )
