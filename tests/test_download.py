import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_DIR = ROOT / "apps" / "worker-download"
CONFIG_DIR = ROOT / "config"
sys.path.insert(0, str(DOWNLOAD_DIR))
sys.path.insert(0, str(CONFIG_DIR))

config_loader = importlib.import_module("config_loader")
download = importlib.import_module("download")


class _FakeDownloadError(Exception):
    pass


def _make_fake_yt_dlp(*, should_fail: bool = False):
    class _FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def download(self, urls):
            if should_fail:
                raise _FakeDownloadError("boom")

    return types.SimpleNamespace(
        YoutubeDL=_FakeYoutubeDL,
        utils=types.SimpleNamespace(DownloadError=_FakeDownloadError),
    )


def _write_manifest(path: Path, *, overwrite_existing: bool = False) -> None:
    items = [
        {
            "index": 1,
            "video_id": "unknown",
            "title": "My_Video",
            "url": "https://www.youtube.com/watch?v=abc123",
            "folder_name": "0001__unknown__My_Video",
            "source_type": "single",
            "overwrite_existing": overwrite_existing,
        }
    ]
    with path.open("w", encoding="utf-8") as handle:
        json.dump(items, handle)


class DownloadHelpersTests(unittest.TestCase):
    def test_load_manifest_reads_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path)

            items = download.load_manifest(manifest_path)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "My_Video")

    def test_load_manifest_rejects_non_list_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            with manifest_path.open("w", encoding="utf-8") as handle:
                json.dump({"not": "a list"}, handle)

            with self.assertRaises(ValueError):
                download.load_manifest(manifest_path)

    def test_download_from_manifest_skips_existing_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, overwrite_existing=False)
            output_dir = Path(tmpdir) / "jobs"
            item_dir = output_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            (item_dir / "audio.mp3").write_text("already there")

            result = download.download_from_manifest(
                manifest_path, output_dir=output_dir, config={"download": {}}
            )

            self.assertEqual(result.items[0].status, "skipped")
            self.assertTrue((item_dir / "audio.mp3").exists())

    def test_download_from_manifest_recreates_existing_item_when_overwrite_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path, overwrite_existing=True)
            output_dir = Path(tmpdir) / "jobs"
            item_dir = output_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            (item_dir / "stale.mp3").write_text("stale")

            config = {"download": {"retry_count": 1, "retry_backoff_seconds": 0}}
            with patch.object(download, "yt_dlp", _make_fake_yt_dlp()):
                result = download.download_from_manifest(
                    manifest_path, output_dir=output_dir, config=config
                )

            self.assertEqual(result.items[0].status, "downloaded")
            self.assertFalse((item_dir / "stale.mp3").exists())

    def test_download_from_manifest_downloads_item(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path)
            output_dir = Path(tmpdir) / "jobs"

            config = {
                "download": {
                    "retry_count": 1,
                    "retry_backoff_seconds": 0,
                }
            }
            with patch.object(download, "yt_dlp", _make_fake_yt_dlp()):
                result = download.download_from_manifest(
                    manifest_path, output_dir=output_dir, config=config
                )

            self.assertEqual(result.items[0].status, "downloaded")
            self.assertTrue((output_dir / "0001__unknown__My_Video").exists())

    def test_download_from_manifest_reports_failure_after_retries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path)
            output_dir = Path(tmpdir) / "jobs"

            config = {
                "download": {
                    "retry_count": 1,
                    "retry_backoff_seconds": 0,
                }
            }
            with patch.object(download, "yt_dlp", _make_fake_yt_dlp(should_fail=True)):
                result = download.download_from_manifest(
                    manifest_path, output_dir=output_dir, config=config
                )

            self.assertEqual(result.items[0].status, "failed")
            self.assertIn("boom", result.items[0].error)

    def test_download_from_manifest_uses_sanitized_file_stems(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            items = [
                {
                    "index": 1,
                    "video_id": "unknown",
                    "title": "My/Video: Hörspiel!",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "folder_name": "0001__unknown__My_Video",
                    "source_type": "single",
                    "overwrite_existing": False,
                }
            ]
            manifest_path.write_text(json.dumps(items), encoding="utf-8")
            output_dir = Path(tmpdir) / "jobs"

            config = {"download": {"retry_count": 1, "retry_backoff_seconds": 0}}
            with patch.object(download, "yt_dlp", _make_fake_yt_dlp()):
                result = download.download_from_manifest(
                    manifest_path, output_dir=output_dir, config=config
                )

            self.assertEqual(result.items[0].status, "downloaded")
            self.assertTrue((output_dir / "0001__unknown__My_Video" / "My_Video_Horspiel.mp3").exists())

    def test_download_from_manifest_without_yt_dlp_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            _write_manifest(manifest_path)
            output_dir = Path(tmpdir) / "jobs"

            with patch.object(download, "yt_dlp", None):
                result = download.download_from_manifest(
                    manifest_path, output_dir=output_dir, config={"download": {}}
                )

            self.assertEqual(result.items[0].status, "failed")
            self.assertEqual(result.items[0].error, "yt-dlp is not installed")


if __name__ == "__main__":
    unittest.main()
