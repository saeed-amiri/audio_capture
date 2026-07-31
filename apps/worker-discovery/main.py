import argparse
import logging
from pathlib import Path

from discover import discover_from_url

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover videos from a YouTube URL")
    parser.add_argument("url", help="YouTube channel, playlist, or single video URL")
    parser.add_argument(
        "--output",
        default="data/jobs/discovery_manifest.json",
        help="Path to the manifest JSON file",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    result = discover_from_url(args.url, output_path=output_path)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
