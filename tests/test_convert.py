import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CONVERT_DIR = ROOT / "apps" / "worker-convert"
sys.path.insert(0, str(CONVERT_DIR))

convert = importlib.import_module("convert")


def _write_manifest(path: Path, *, folder_name: str) -> None:
    items = [
        {
            "index": 1,
            "video_id": "unknown",
            "title": "My_Video",
            "url": "https://www.youtube.com/watch?v=abc123",
            "folder_name": folder_name,
            "source_type": "single",
        }
    ]
    with path.open("w", encoding="utf-8") as handle:
        json.dump(items, handle)


class ConvertWorkerTests(unittest.TestCase):
    def test_convert_disabled_skips_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            input_path = item_dir / "audio.webm"
            input_path.write_text("raw", encoding="utf-8")

            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            config = {
                "conversion": {
                    "enabled": False,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                }
            }
            with patch.object(convert, "_run_ffmpeg") as mocked_ffmpeg:
                result = convert.convert_from_manifest(
                    manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            mocked_ffmpeg.assert_not_called()
            self.assertEqual(result.items[0].status, "skipped")
            self.assertTrue(input_path.exists())

    def test_convert_keeps_output_in_same_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            input_path = item_dir / "audio.webm"
            input_path.write_text("raw", encoding="utf-8")

            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            def _fake_run_ffmpeg(command: list[str]) -> tuple[int, str]:
                Path(command[-1]).write_text("converted", encoding="utf-8")
                return 0, ""

            config = {
                "conversion": {
                    "enabled": True,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                }
            }
            with patch.object(convert, "_run_ffmpeg", side_effect=_fake_run_ffmpeg):
                result = convert.convert_from_manifest(
                    manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "converted")
            self.assertEqual(Path(result.items[0].output_path).parent, item_dir)
            self.assertTrue(Path(result.items[0].output_path).name.endswith("My_Video.mp3"))

    def test_remove_original_format_defaults_to_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            input_path = item_dir / "audio.webm"
            input_path.write_text("raw", encoding="utf-8")

            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            def _fake_run_ffmpeg(command: list[str]) -> tuple[int, str]:
                Path(command[-1]).write_text("converted", encoding="utf-8")
                return 0, ""

            config = {
                "conversion": {
                    "enabled": True,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                }
            }
            with patch.object(convert, "_run_ffmpeg", side_effect=_fake_run_ffmpeg):
                result = convert.convert_from_manifest(
                    manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "converted")
            self.assertFalse(result.items[0].removed_original)
            self.assertTrue(input_path.exists())

    def test_remove_original_format_true_deletes_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            input_path = item_dir / "audio.webm"
            output_path = item_dir / "My_Video.mp3"
            input_path.write_text("raw", encoding="utf-8")

            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            def _fake_run_ffmpeg(command: list[str]) -> tuple[int, str]:
                Path(command[-1]).write_text("converted", encoding="utf-8")
                return 0, ""

            config = {
                "conversion": {
                    "enabled": True,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                    "remove_original_format": True,
                }
            }
            with patch.object(convert, "_run_ffmpeg", side_effect=_fake_run_ffmpeg):
                result = convert.convert_from_manifest(
                    manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "converted")
            self.assertTrue(result.items[0].removed_original)
            self.assertFalse(input_path.exists())
            self.assertTrue(output_path.exists())

    def test_convert_skips_when_target_format_already_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            target_path = item_dir / "My_Video.mp3"
            target_path.write_text("already", encoding="utf-8")

            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            config = {
                "conversion": {
                    "enabled": True,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                }
            }
            result = convert.convert_from_manifest(
                manifest_path,
                output_dir=jobs_dir,
                config=config,
            )

            self.assertEqual(result.items[0].status, "skipped")
            self.assertEqual(result.items[0].output_path, str(target_path))

    def test_convert_renames_spaced_source_file_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            spaced_input = item_dir / "Audio File Name.webm"
            spaced_input.write_text("raw", encoding="utf-8")

            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            def _fake_run_ffmpeg(command: list[str]) -> tuple[int, str]:
                Path(command[-1]).write_text("converted", encoding="utf-8")
                return 0, ""

            config = {
                "conversion": {
                    "enabled": True,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                }
            }
            with patch.object(convert, "_run_ffmpeg", side_effect=_fake_run_ffmpeg):
                result = convert.convert_from_manifest(
                    manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "converted")
            self.assertFalse(spaced_input.exists())
            self.assertTrue((item_dir / "Audio_File_Name.webm").exists())

    def test_create_conversion_manifest_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            source_path = item_dir / "audio.webm"
            source_path.write_text("raw", encoding="utf-8")

            manifest_path = Path(tmpdir) / "discovery_manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            def _fake_run_ffmpeg(command: list[str]) -> tuple[int, str]:
                Path(command[-1]).write_text("converted", encoding="utf-8")
                return 0, ""

            config = {
                "conversion": {
                    "enabled": True,
                    "target_format": "mp3",
                    "bitrate_kbps": 192,
                }
            }
            with patch.object(convert, "_run_ffmpeg", side_effect=_fake_run_ffmpeg):
                result = convert.convert_from_manifest(
                    manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            conversion_manifest_path = jobs_dir / "conversion_manifest.json"
            written_path = convert.create_conversion_manifest(
                result, conversion_manifest_path
            )

            self.assertEqual(written_path, conversion_manifest_path)
            self.assertTrue(conversion_manifest_path.exists())
            payload = json.loads(conversion_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["output_dir"], str(jobs_dir))
            self.assertEqual(len(payload["items"]), 1)


if __name__ == "__main__":
    unittest.main()
