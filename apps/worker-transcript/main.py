"""Main entry point for the transcript worker."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WORKER_DIR = Path(__file__).resolve().parent
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from transcript import build_transcript_manifest, write_transcript_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate transcript metadata from converted items")
    parser.add_argument("manifest", nargs="?", help="Path to the conversion manifest JSON file")
    parser.add_argument(
        "--output-dir",
        default="data/jobs",
        help="Directory that contains item folders with converted media",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="Path to write transcript result JSON (default: <output-dir>/transcript_manifest.json)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest) if args.manifest else None
    output_dir = Path(args.output_dir)
    result = build_transcript_manifest(manifest_path=manifest_path, output_dir=output_dir)
    manifest_output = (
        Path(args.manifest_output)
        if args.manifest_output
        else output_dir / "transcript_manifest.json"
    )
    write_transcript_manifest(result, manifest_output)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
