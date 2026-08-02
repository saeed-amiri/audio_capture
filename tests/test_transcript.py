import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT_DIR = ROOT / "apps" / "worker-transcript"
sys.path.insert(0, str(TRANSCRIPT_DIR))

transcript = importlib.import_module("transcript")
transcript_helpers = importlib.import_module("transcript_helpers")


class _FakeDownloadError(Exception):
    pass


def _make_fake_yt_dlp(*, subtitle_content: str | None = None, should_fail: bool = False):
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
            if subtitle_content is not None:
                outtmpl = self.options["outtmpl"]
                lang = (self.options.get("subtitleslangs") or ["en"])[0]
                suffix = ".vtt"
                path = Path(outtmpl.replace("%(title)s", "My_Video").replace("%(ext)s", f"{lang}{suffix}"))
                path.write_text(subtitle_content, encoding="utf-8")

    return types.SimpleNamespace(
        YoutubeDL=_FakeYoutubeDL,
        utils=types.SimpleNamespace(DownloadError=_FakeDownloadError),
    )


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


class TranscriptWorkerTests(unittest.TestCase):
    def test_build_transcript_manifest_marks_existing_transcript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            transcript_path = item_dir / "transcript.txt"
            transcript_path.write_text("hello", encoding="utf-8")

            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            result = transcript.build_transcript_manifest(
                manifest_path=manifest_path,
                output_dir=jobs_dir,
                config={"transcript": {"output_text_file": "transcript.txt"}},
            )

            self.assertEqual(result.items[0].status, "transcribed")
            self.assertEqual(result.items[0].transcript_path, str(transcript_path))

    def test_build_transcript_manifest_uses_subtitles_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)
            subtitle_path = item_dir / "captions.vtt"
            subtitle_path.write_text("WEBVTT", encoding="utf-8")

            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            result = transcript.build_transcript_manifest(
                manifest_path=manifest_path,
                output_dir=jobs_dir,
                config={"transcript": {"output_text_file": "transcript.txt"}},
            )

            self.assertEqual(result.items[0].status, "transcribed")
            self.assertTrue((item_dir / "transcript.txt").exists())

    def test_build_transcript_manifest_accepts_conversion_result_payloads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "jobs"
            output_dir.mkdir()
            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            payload = {
                "manifest_path": str(manifest_path),
                "output_dir": str(output_dir),
                "items": [
                    {
                        "index": 1,
                        "video_id": "unknown",
                        "title": "My_Video",
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "folder_name": "0001__unknown__My_Video",
                        "input_path": "input",
                        "output_path": "output",
                        "status": "converted",
                        "removed_original": False,
                    }
                ],
            }
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")
            item_dir = output_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)

            config = {
                "transcript": {
                    "output_text_file": "transcript.txt",
                    "prefer_manual_subtitles": False,
                    "fallback_to_auto_subtitles": False,
                }
            }
            result = transcript.build_transcript_manifest(
                manifest_path=manifest_path,
                output_dir=output_dir,
                config=config,
            )

            self.assertEqual(result.items[0].status, "skipped")

    def test_fetches_manual_subtitles_from_url_when_missing_locally(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)

            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            config = {
                "transcript": {"output_text_file": "transcript.txt"},
                "download": {"subtitle_languages": ["en"]},
            }
            with patch.object(
                transcript_helpers, "yt_dlp", _make_fake_yt_dlp(subtitle_content="WEBVTT\nhello")
            ):
                result = transcript.build_transcript_manifest(
                    manifest_path=manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "transcribed")
            self.assertEqual((item_dir / "transcript.txt").read_text(encoding="utf-8"), "hello")

    def test_falls_back_to_auto_subtitles_when_manual_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)

            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            config = {
                "transcript": {
                    "output_text_file": "transcript.txt",
                    "fallback_to_auto_subtitles": True,
                },
                "download": {"subtitle_languages": ["en"]},
            }

            call_count = {"n": 0}
            real_fake = _make_fake_yt_dlp(subtitle_content="WEBVTT\nauto")

            class _SequencedYoutubeDL(real_fake.YoutubeDL):
                def download(self, urls):
                    call_count["n"] += 1
                    if call_count["n"] == 1:
                        raise real_fake.utils.DownloadError("no manual subtitles")
                    return super().download(urls)

            fake_module = types.SimpleNamespace(
                YoutubeDL=_SequencedYoutubeDL, utils=real_fake.utils
            )
            with patch.object(transcript_helpers, "yt_dlp", fake_module):
                result = transcript.build_transcript_manifest(
                    manifest_path=manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "transcribed")
            self.assertEqual(call_count["n"], 2)

    def test_reports_failure_when_yt_dlp_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs"
            item_dir = jobs_dir / "0001__unknown__My_Video"
            item_dir.mkdir(parents=True)

            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            _write_manifest(manifest_path, folder_name=item_dir.name)

            config = {
                "transcript": {
                    "output_text_file": "transcript.txt",
                    "fallback_to_auto_subtitles": False,
                }
            }
            with patch.object(transcript_helpers, "yt_dlp", None):
                result = transcript.build_transcript_manifest(
                    manifest_path=manifest_path,
                    output_dir=jobs_dir,
                    config=config,
                )

            self.assertEqual(result.items[0].status, "failed")
            self.assertEqual(result.items[0].error, "yt-dlp is not installed")

    def test_write_transcript_manifest_writes_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "jobs"
            output_dir.mkdir()
            manifest_path = Path(tmpdir) / "conversion_manifest.json"
            _write_manifest(manifest_path, folder_name="0001__unknown__My_Video")

            config = {
                "transcript": {
                    "output_text_file": "transcript.txt",
                    "prefer_manual_subtitles": False,
                    "fallback_to_auto_subtitles": False,
                }
            }
            result = transcript.build_transcript_manifest(
                manifest_path=manifest_path,
                output_dir=output_dir,
                config=config,
            )
            written_path = transcript.write_transcript_manifest(result, output_dir / "manifest.json")

            self.assertTrue(written_path.exists())
            payload = json.loads(written_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["status"], "skipped")


class ExtractPlainTextFromSubtitlesTests(unittest.TestCase):
    def test_strips_header_timing_and_inline_tags(self):
        vtt_content = (
            "WEBVTT\n"
            "Kind: captions\n"
            "Language: en\n"
            "\n"
            "00:00:02.070 --> 00:00:06.690 align:start position:0%\n"
            "hello<00:00:02.500><c> world</c>\n"
            "\n"
            "00:00:06.690 --> 00:00:09.000 align:start position:0%\n"
            "hello world\n"
            "goodbye\n"
        )

        result = transcript_helpers.extract_plain_text_from_subtitles(vtt_content)

        self.assertEqual(result, "hello world\ngoodbye")

    def test_returns_empty_string_for_header_only_content(self):
        result = transcript_helpers.extract_plain_text_from_subtitles("WEBVTT\n")

        self.assertEqual(result, "")
