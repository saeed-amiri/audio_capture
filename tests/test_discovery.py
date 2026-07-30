import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_DIR = ROOT / "apps" / "worker-discovery"
CONFIG_DIR = ROOT / "config"
sys.path.insert(0, str(DISCOVERY_DIR))
sys.path.insert(0, str(CONFIG_DIR))

config_loader = importlib.import_module("config_loader")
discover = importlib.import_module("discover")


class DiscoveryHelpersTests(unittest.TestCase):
    def test_detect_source_type_single_url(self):
        self.assertEqual(
            discover.detect_source_type("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "single",
        )

    def test_detect_source_type_playlist_url(self):
        self.assertEqual(
            discover.detect_source_type(
                "https://www.youtube.com/playlist?list=PL123456"
            ),
            "playlist",
        )

    def test_detect_source_type_channel_url(self):
        self.assertEqual(
            discover.detect_source_type(
                "https://www.youtube.com/@FreundederSonne-1000H%C3%B6rspiele"
            ),
            "channel",
        )

    def test_sanitize_title(self):
        self.assertEqual(
            discover.sanitize_title("Freunde der Sonne - Folge 01: Hörspiel!"),
            "Freunde_der_Sonne_Folge_01_Horspiel",
        )

    def test_build_item_folder_name(self):
        self.assertEqual(
            discover.build_item_folder_name(1, "abc123", "My Hörspiel"),
            "0001__abc123__My_Horspiel",
        )

    def test_discover_from_url_uses_real_title_for_single_video(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "manifest.json"
            with patch(
                "discover._get_video_title", return_value="Actual YouTube Title"
            ):
                result = discover.discover_from_url(
                    "https://www.youtube.com/watch?v=abc123",
                    output_path=output_path,
                )
            self.assertEqual(result["items"][0]["title"], "Actual_YouTube_Title")
            self.assertIn("Actual_YouTube_Title", result["items"][0]["folder_name"])

    def test_fetch_page_html_handles_explicit_lookup_errors(self):
        with patch("discover.urlopen", side_effect=ValueError("boom")):
            self.assertIsNone(discover._fetch_page_html("https://example.com"))

    def test_build_item_folder_name_uses_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "settings.yaml"
            config_path.write_text(
                "app:\n  name: test\npaths:\n  jobs_root: /tmp/jobs\n"
                "naming:\n  item_folder_pattern: '{index:02d}-{video_id}-{safe_title}'\n"
                "  safe_title_max_length: 20\n"
                "  replace_whitespace_with: '-'\n",
                encoding="utf-8",
            )
            config = config_loader.load_config(config_path=config_path)
            self.assertEqual(
                discover.build_item_folder_name(
                    3, "abc123", "My Great Hörspiel", config=config
                ),
                "03-abc123-My-Great-Horspiel",
            )

    def test_load_config_works_without_pyyaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "settings.yaml"
            config_path.write_text(
                "app:\n  name: fallback\npaths:\n  jobs_root: /tmp/jobs\n",
                encoding="utf-8",
            )
            original_yaml = config_loader.yaml
            try:
                config_loader.yaml = None
                config = config_loader.load_config(config_path=config_path)
            finally:
                config_loader.yaml = original_yaml
            self.assertEqual(config["app"]["name"], "fallback")

    def test_discovery_requires_naming_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "settings.yaml"
            config_path.write_text(
                "app:\n  name: test\npaths:\n  jobs_root: /tmp/jobs\n"
                "naming:\n  item_folder_pattern: '{index:04d}__{video_id}__{safe_title}'\n",
                encoding="utf-8",
            )
            config = config_loader.load_config(
                config_path=config_path,
                required_sections={"app", "paths"},
            )
            with self.assertRaises(ValueError):
                discover.build_item_folder_name(
                    1, "abc123", "My Hörspiel", config=config
                )


if __name__ == "__main__":
    unittest.main()
