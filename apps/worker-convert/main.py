import argparse
import logging
from pathlib import Path

from convert import convert_from_manifest, create_conversion_manifest

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert downloaded audio from a discovery manifest")
    parser.add_argument("manifest", help="Path to the discovery manifest JSON file")
    parser.add_argument(
        "--output-dir",
        default="data/jobs",
        help="Directory that contains item folders to convert",
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help="Path to write conversion result JSON (default: <output-dir>/conversion_manifest.json)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    result = convert_from_manifest(manifest_path, output_dir=output_dir)
    manifest_output = (
        Path(args.manifest_output)
        if args.manifest_output
        else output_dir / "conversion_manifest.json"
    )
    create_conversion_manifest(result, manifest_output)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
