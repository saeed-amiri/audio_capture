import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA_DIR = ROOT / "apps" / "worker-metadata"
sys.path.insert(0, str(METADATA_DIR))

import metadata


class MetadataWorkerTests(unittest.TestCase):
    def test_build_metadata_map_includes_common_ffmpeg_fields(self):
        result = metadata.build_metadata_map(
            audio_path=Path("/tmp/book.mp3"),
            source_url="https://www.youtube.com/watch?v=abc123",
            title="Winterwende",
            artist="Elisabeth Langgasser",
            cover_path=Path("/tmp/book.webp"),
            language="de",
            narrator="Elisabeth Langgasser",
        )
        self.assertIn("title", result)
        self.assertIn("artist", result)
        self.assertIn("source", result)
        self.assertIn("cover_path", result)
        self.assertEqual(result["language"], "de")
        self.assertEqual(result["source"], "https://www.youtube.com/watch?v=abc123")

    def test_metadata_manifest_includes_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            audio_path = output_dir / "audio.mp3"
            audio_path.write_bytes(b"fake mp3")
            cover_path = output_dir / "cover.webp"
            cover_path.write_bytes(b"fake webp")
            manifest = metadata.create_metadata_manifest(
                item={
                    "index": 1,
                    "folder_name": "0001__Demo_Book",
                    "title": "Demo Book",
                    "url": "https://example.com/book",
                    "output_path": str(audio_path),
                    "video_id": "abc123",
                },
                output_dir=output_dir,
                source_url="https://example.com/book",
                cover_path=cover_path,
                metadata_override={"title": "Demo Book", "artist": "Jane Doe", "language": "de"},
            )
            self.assertIn("metadata", manifest)
            self.assertIn("title", manifest["metadata"])
            self.assertEqual(manifest["metadata"]["artist"], "Jane Doe")
            self.assertEqual(manifest["cover_path"], str(cover_path))

    def _write_conversion(self, output_dir, folders):
        items = []
        for index, name in enumerate(folders, start=1):
            item_dir = output_dir / name
            item_dir.mkdir()
            audio = item_dir / "demo.mp3"
            audio.write_bytes(b"fake mp3")
            items.append(
                {
                    "index": index,
                    "folder_name": name,
                    "title": name,
                    "url": "https://example.com/" + name,
                    "output_path": str(audio),
                }
            )
        conversion = output_dir / "conversion_manifest.json"
        conversion.write_text(json.dumps({"items": items}), encoding="utf-8")
        return conversion

    def test_each_run_rewrites_root_manifest_instead_of_appending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            root = output_dir / "metadata_manifest.json"
            root.write_text(json.dumps({"items": [{"folder_name": "stale"}]}), encoding="utf-8")
            conversion = self._write_conversion(output_dir, ["a", "b"])

            with unittest.mock.patch.object(metadata, "apply_metadata_to_file"):
                for _ in range(2):
                    metadata.metadata_from_conversion_manifest(
                        conversion, output_dir=output_dir, config={}, interactive=False
                    )

            folders = [i["folder_name"] for i in json.loads(root.read_text(encoding="utf-8"))["items"]]
            self.assertEqual(folders, ["a", "b"])

    def test_edits_to_root_manifest_during_review_are_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            conversion = self._write_conversion(output_dir, ["a"])

            def fake_review(manifest_path, **kwargs):
                self.assertEqual(Path(manifest_path), output_dir / "metadata_manifest.json")
                data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                data["items"][0]["metadata"]["artist"] = "Edited Artist"
                Path(manifest_path).write_text(json.dumps(data), encoding="utf-8")
                return True

            applied = []
            with unittest.mock.patch.object(metadata, "review_metadata_manifest", fake_review), \
                    unittest.mock.patch.object(metadata, "apply_metadata_to_file", applied.append):
                metadata.metadata_from_conversion_manifest(
                    conversion, output_dir=output_dir, config={}, interactive=True
                )

            self.assertEqual(applied[0]["metadata"]["artist"], "Edited Artist")

    def test_invalid_edited_manifest_raises_without_applying(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            conversion = self._write_conversion(output_dir, ["a"])

            def fake_review(manifest_path, **kwargs):
                Path(manifest_path).write_text("{ not json", encoding="utf-8")
                return True

            applied = []
            with unittest.mock.patch.object(metadata, "review_metadata_manifest", fake_review), \
                    unittest.mock.patch.object(metadata, "apply_metadata_to_file", applied.append):
                with self.assertRaises(ValueError):
                    metadata.metadata_from_conversion_manifest(
                        conversion, output_dir=output_dir, config={}, interactive=True
                    )
            self.assertEqual(applied, [])

    def test_build_ffmpeg_metadata_args_keeps_cover_and_common_keys(self):
        args = metadata.build_ffmpeg_metadata_args(
            {
                "title": "Winterwende",
                "artist": "Elisabeth Langgasser",
                "source": "https://example.com/book",
                "language": "de",
                "narrator": "Elisabeth Langgasser",
                "cover_path": "/tmp/book.webp",
            }
        )
        self.assertIn("-metadata", args)
        self.assertIn("title=Winterwende", args)
        self.assertIn("language=de", args)
        self.assertIn("source=https://example.com/book", args)

    def test_prepare_cover_for_metadata_converts_webp_to_jpeg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "cover.webp"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=200x200:d=1",
                    "-frames:v",
                    "1",
                    str(source),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            converted = metadata.prepare_cover_for_metadata(source)
            self.assertIsNotNone(converted)
            self.assertEqual(converted.suffix.lower(), ".jpg")
            self.assertTrue(converted.exists())

    def test_reviewed_manifest_is_copied_into_each_target_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            conversion = self._write_conversion(output_dir, ["a", "b"])

            def fake_review(manifest_path, **kwargs):
                data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                data["items"][0]["metadata"]["artist"] = "Edited Artist"
                Path(manifest_path).write_text(json.dumps(data), encoding="utf-8")
                return True

            with unittest.mock.patch.object(metadata, "review_metadata_manifest", fake_review), \
                    unittest.mock.patch.object(metadata, "apply_metadata_to_file", lambda m: m):
                metadata.metadata_from_conversion_manifest(
                    conversion, output_dir=output_dir, config={}, interactive=True
                )

            copy_a = json.loads((output_dir / "a" / "metadata_manifest.json").read_text(encoding="utf-8"))
            copy_b = json.loads((output_dir / "b" / "metadata_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(copy_a["metadata"]["artist"], "Edited Artist")
            self.assertEqual(copy_a["folder_name"], "a")
            self.assertEqual(copy_b["folder_name"], "b")

    def test_default_output_name_is_title_dash_artist_with_underscores(self):
        name = metadata.default_output_name(
            {"title": "Winterwende", "artist": "Elisabeth Langgasser"}, Path("/x/source.mp3")
        )
        self.assertEqual(name, "Winterwende-Elisabeth_Langgasser.mp3")
        self.assertEqual(metadata.default_output_name({"title": "A/B: C"}, Path("/x/s.mp3")), "AB_C.mp3")

    def test_output_name_follows_edited_artist_unless_user_changed_it(self):
        for custom, expected in ((None, "Demo-Jane.mp3"), ("My_Name.mp3", "My_Name.mp3")):
            with tempfile.TemporaryDirectory() as tmpdir:
                output_dir = Path(tmpdir)
                conversion = self._write_conversion(output_dir, ["a"])

                def fake_review(manifest_path, **kwargs):
                    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                    data["items"][0]["metadata"]["title"] = "Demo"
                    data["items"][0]["metadata"]["artist"] = "Jane"
                    if custom:
                        data["items"][0]["output_name"] = custom
                    Path(manifest_path).write_text(json.dumps(data), encoding="utf-8")
                    return True

                applied = []
                with unittest.mock.patch.object(metadata, "review_metadata_manifest", fake_review), \
                        unittest.mock.patch.object(metadata, "apply_metadata_to_file", applied.append):
                    metadata.metadata_from_conversion_manifest(
                        conversion, output_dir=output_dir, config={}, interactive=True
                    )
                self.assertEqual(applied[0]["output_name"], expected)

    def test_apply_writes_tagged_file_under_output_name_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            source = folder / "source.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=1", str(source)],
                check=True, capture_output=True,
            )
            metadata.apply_metadata_to_file(
                {
                    "audio_path": str(source),
                    "output_name": "../Custom_Name",
                    "metadata": {"title": "T", "artist": "A"},
                }
            )
            tagged = folder / "Custom_Name.mp3"
            self.assertTrue(tagged.exists())
            self.assertTrue(source.exists())
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format_tags=artist", "-of", "csv=p=0", str(tagged)],
                check=True, capture_output=True, text=True,
            )
            self.assertEqual(probe.stdout.strip(), "A")

    def test_review_metadata_manifest_accepts_default_yes(self):
        with unittest.mock.patch("metadata.input", return_value=""):
            self.assertTrue(metadata.review_metadata_manifest(Path("/tmp/demo.json"), interactive=True))

    def test_review_metadata_manifest_declines_on_no(self):
        with unittest.mock.patch("metadata.input", return_value="n"):
            self.assertFalse(metadata.review_metadata_manifest(Path("/tmp/demo.json"), interactive=True))


if __name__ == "__main__":
    unittest.main()
