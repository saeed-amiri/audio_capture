import argparse
import logging
from pathlib import Path

from download import download_from_manifest

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download audio from a discovery manifest")
    parser.add_argument("manifest", help="Path to the discovery manifest JSON file")
    parser.add_argument(
        "--output-dir",
        default="data/jobs",
        help="Directory to download items into",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    result = download_from_manifest(manifest_path, output_dir=output_dir)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
