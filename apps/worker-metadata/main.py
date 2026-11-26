import argparse
import json
from pathlib import Path

from metadata import metadata_from_conversion_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ffmpeg metadata manifests for converted audio files")
    parser.add_argument("manifest", help="Path to the conversion manifest JSON file")
    parser.add_argument(
        "--output-dir",
        default="data/jobs",
        help="Directory that contains the converted item folders",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Skip the interactive review/edit prompt before embedding metadata into the MP3s.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    result = metadata_from_conversion_manifest(
        manifest_path,
        output_dir=output_dir,
        interactive=not args.no_prompt,
    )
    summary = {
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir),
        "items": [
            {
                "index": item.get("item_index"),
                "folder_name": item.get("folder_name"),
                "audio_path": item["audio_path"],
                "cover_path": item.get("cover_path"),
                "metadata_count": len(item["metadata"]),
            }
            for item in result
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
