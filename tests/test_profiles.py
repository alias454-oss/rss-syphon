"""
Offline regression tests for profile loading and the explicit files output.

Tests use standard-library stubs and do not contact feeds or integrations.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rss_syphon import cli as runner, config as rss_config, data as rss_data  # noqa: E402
from rss_syphon.modules import files  # noqa: E402


def load_profile(name: str | None = None, **kwargs) -> dict:
    """Load configuration once, then prepare datasets through their own layer."""
    return rss_data.load_data(rss_config.load_config(name, **kwargs))


class FakeFeeds:
    """Capture feed processing calls without importing feedparser/aiohttp."""

    def __init__(self):
        """Initialize the collected feed names and keyword settings."""
        self.requested = []
        self.searches = []

    def check_last_modified(self, value):
        """Preserve the provided keyword freshness marker."""
        return value

    def validate_feed_list(self, feeds):
        """Record the feed names and return all supplied feeds."""
        self.requested.extend(item["name"] for item in feeds)
        return feeds

    def fetch_feed_results(self, feeds):
        """Return synthetic results instead of making HTTP requests."""
        return feeds

    def process_feeds(self, results, feeds):
        """Pass synthetic results through the processing stage."""
        return results

    def prepare_feed_message(self, feeds, search, ignored, hard_ignore, lookback):
        """Capture filtering arguments and preserve the four-value return shape."""
        self.searches.append((search, ignored, hard_ignore, lookback))
        return {"articles": [{"title": "test"}]}, [], [], []


class ProfileTests(unittest.TestCase):
    """Validate existing data contracts and newly explicit output behavior."""

    def setUp(self):
        """Load the security profile for each test."""
        self.security = load_profile("security")

    def test_config_and_data_have_separate_responsibilities(self):
        """Data loading reads datasets without reloading executable config."""
        settings = rss_config.load_config("security")
        self.assertEqual(settings["_profile_root"], REPO / "profiles/security")
        self.assertNotIn("feeds", settings)
        self.assertNotIn("keywords", settings)
        with patch.object(rss_config, "load_config", side_effect=AssertionError("reload")):
            loaded = rss_data.load_data(settings)
        self.assertEqual(loaded["feeds"], self.security["feeds"])
        self.assertEqual(loaded["keywords"], self.security["keywords"])

    def test_empty_profiles_do_not_require_dataset_files(self):
        """Profiles with no jobs can omit feeds and keywords entirely."""
        with tempfile.TemporaryDirectory() as folder:
            settings = {**rss_config.load_config("security"),
                        "jobs": {}, "_profile_root": Path(folder)}
            loaded = rss_data.load_data(settings)
        self.assertEqual(loaded["feeds"], {})
        self.assertEqual(loaded["keywords"], {})

    def test_malformed_dataset_fails_cleanly(self):
        """Invalid dataset TOML must not be silently treated as empty data."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "keywords.toml").write_text('[keywords]\nignored = "bad-type"\n', encoding="utf-8")
            settings = {**rss_config.load_config("security"), "jobs": {}, "_profile_root": root}
            with self.assertRaisesRegex(ValueError, "ignored"):
                rss_data.load_data(settings)

    def test_module_dict_shapes_match_existing_interfaces(self):
        """Existing output modules can consume the nested parameter dictionaries."""
        modules = self.security["modules"]
        self.assertIn("slack_token", modules["slack"])
        self.assertIn("news", modules["slack"]["channels"])
        self.assertIn("error", modules["notion"]["databases"])
        self.assertIn("zendesk_token", modules["zendesk"])
        self.assertEqual(modules["splunk"]["splunk_host"]["port"], 8089)

    def test_empty_profile_skips_feed_jobs(self):
        """A profile with no declared jobs does not fetch feeds."""
        profile = {**self.security, "jobs": {}, "outputs": {}}
        with patch.object(runner, "run_feed_check") as fetch:
            runner.run_profile(profile)
            fetch.assert_not_called()

    def test_logging_overrides_preserved(self):
        """Original LOG_LEVEL and LOG_FORMAT environment settings take precedence."""
        with patch.dict(os.environ, {"LOG_LEVEL": "WARNING", "LOG_FORMAT": "%(message)s"}):
            profile = load_profile("security")
        self.assertEqual(profile["logging"]["level"], "WARNING")
        self.assertEqual(profile["logging"]["format"], "%(message)s")

    def test_main_config_owns_global_settings(self):
        """Only syphon.toml decides the global module capabilities and paths."""
        global_config = rss_config.load_system()
        self.assertEqual(global_config["enabled_modules"], ["files"])
        self.assertEqual(global_config["profiles_dir"], REPO / "profiles")
        self.assertEqual(global_config["root_data_dir"], REPO / "output")
        self.assertFalse(self.security["modules"]["slack"]["slack_enabled"])
        self.assertTrue(self.security["modules"]["files"]["files_enabled"])
        self.assertEqual(self.security["modules"]["files"]["path"], str(REPO / "output/security/security.ndjson"))

    def test_configured_profile_directory_is_not_hardcoded(self):
        """The loader resolves arbitrary relative and absolute profile directories."""
        for absolute in (False, True):
            with self.subTest(absolute=absolute), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                dogfish = root / "dogfish"
                (dogfish / "example").mkdir(parents=True)
                (dogfish / "example/profile.toml").write_text(
                    '[system]\nname = "example"\n[jobs]\n', encoding="utf-8")
                path = str(dogfish) if absolute else "./dogfish"
                (root / "syphon.toml").write_text(
                    f'[system]\nprofiles_dir = "{path}"\n'
                    'default_profile = "example"\n'
                    '[modules]\nenabled = []\n',
                    encoding="utf-8",
                )
                selected = load_profile(project_root=root)
                self.assertEqual(selected["name"], "example")
                self.assertEqual(selected["jobs"], {})

    def test_missing_profile_directory_is_not_guessed(self):
        """No Python-side profile directory fallback may override syphon.toml."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "syphon.toml").write_text(
                '[system]\ndefault_profile = "security"\n[modules]\nenabled = []\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "profiles_dir"):
                rss_config.load_config(project_root=root)

    def test_disabled_global_module_skips_without_import_or_failure(self):
        """Portable routes may mention modules disabled by the main config."""
        with patch.object(runner, "import_module") as importer:
            modules = runner.load_modules(self.security)
        importer.assert_called_once_with("rss_syphon.modules.files")
        self.assertIn("files", modules)
        self.assertNotIn("slack", modules)

        calls = []
        files_module = types.SimpleNamespace(dispatch=lambda *args: calls.append(args))
        with self.assertLogs(runner.logger, level="INFO") as captured:
            runner.dispatch_router(
                "news", {"articles": []}, profile_data=self.security,
                output_modules={"files": files_module},
            )
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("slack" in line and "globally" in line for line in captured.output))

    def test_new_modules_need_no_registry_edit(self):
        """A conventionally named new output loads from its own package."""
        portable = {**self.security, "enabled_modules": ["dogfish"],
                    "outputs": {"news": ["dogfish"]}}
        with patch.object(runner, "import_module", return_value=object()) as importer:
            modules = runner.load_modules(portable)
        importer.assert_called_once_with("rss_syphon.modules.dogfish")
        self.assertIn("dogfish", modules)

    def test_profile_cannot_replace_global_credentials(self):
        """Credentials remain global even when a portable profile carries them."""
        merged = rss_config._merge_module_settings(
            "slack", {"slack_token": "global", "base_url": "https://default.example"},
            {"slack_token": "profile", "base_url": "https://profile.example"},
        )
        self.assertEqual(merged["slack_token"], "global")
        self.assertEqual(merged["base_url"], "https://profile.example")

    def test_config_only_cli_requires_no_site_packages_or_secrets(self):
        """Help and validation do not import optional provider/feed libraries."""
        script = REPO / "src" / "syphon.py"
        for flag in ("--help", "--check-config"):
            with self.subTest(flag=flag):
                result = subprocess.run(
                    [sys.executable, "-S", str(script), flag],
                    cwd=REPO, capture_output=True, text=True, check=False, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        module_call = subprocess.run(
            [sys.executable, "-S", "-m", "rss_syphon", "--check-config"],
            cwd=REPO / "src", capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(module_call.returncode, 0, module_call.stderr)

    def test_environment_credentials_are_not_printed(self):
        """Inspection lists job names, never resolved environment values."""
        token = "do-not-print-this-token"
        with patch.dict(os.environ, {"SLACK_TOKEN": token}), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(runner.main(["--check-config"]), 0)
        self.assertNotIn(token, out.getvalue())

    def test_stdout_is_an_explicit_files_output(self):
        """Keep the original JSON stdout record contract through files.dispatch."""
        params = {**self.security["modules"]["files"], "destination": "stdout"}
        with patch.dict(os.environ, {"RSS_LOCAL_OUTPUT_FILE": ""}), redirect_stdout(io.StringIO()) as out:
            files.dispatch("news", params, {"articles": []}, ["feed-error"], "2026-09-28")
        result = json.loads(out.getvalue())
        self.assertEqual(result["run_type"], "news")
        self.assertEqual(result["errors"], ["feed-error"])
        self.assertEqual(result["check_stale_keywords"], "2026-09-28")

    def test_files_output_overwrites_daily_json(self):
        """Production output keeps one dated JSON snapshot per job."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.ndjson"
            params = {"files_enabled": True, "destination": "file", "path": str(path)}
            with patch.dict(os.environ, {"RSS_LOCAL_OUTPUT_FILE": ""}):
                files.dispatch("news", params, {"articles": [{"title": "old"}]})
                files.dispatch("cve", params, {"articles": []})
                files.dispatch("new_job", params, {"articles": []})
                files.dispatch("news", params, {"articles": [{"title": "new"}]})

            self.assertFalse(path.exists())
            for run_type in ("news", "cve", "new_job"):
                outputs = list(Path(folder).glob(f"{run_type}-*.json"))
                self.assertEqual(len(outputs), 1)
                self.assertRegex(outputs[0].name, rf"^{run_type}-\d{{2}}-\d{{2}}-\d{{4}}\.json$")
                self.assertEqual(json.loads(outputs[0].read_text())["run_type"], run_type)
            news = json.loads(next(Path(folder).glob("news-*.json")).read_text())
            self.assertEqual(news["matched"]["articles"], [{"title": "new"}])

    def test_file_output_rejects_unsafe_job_names(self):
        """Untrusted job handles cannot change the configured output directory."""
        with tempfile.TemporaryDirectory() as folder:
            params = {"files_enabled": True, "destination": "file",
                      "path": str(Path(folder) / "results.ndjson")}
            with patch.dict(os.environ, {"RSS_LOCAL_OUTPUT_FILE": ""}):
                with self.assertRaisesRegex(ValueError, "Invalid job type"):
                    files.dispatch("../other", params, {"articles": []})

    def test_optional_reports_are_dated_by_job(self):
        """Each job gets daily JSON and text snapshots, overwritten on rerun."""
        with tempfile.TemporaryDirectory() as folder:
            profile_dir = Path(folder) / "security"
            params = {"files_enabled": True, "destination": "file", "report": True,
                      "path": str(profile_dir / "security.ndjson")}
            matched = {"articles": [{"title": "Example", "link": "https://example.com",
                                     "keywords": "'linux'", "rss_feed_name": "test"}],
                       "keywords": {"linux": 1}}

            with patch.dict(os.environ, {"RSS_LOCAL_OUTPUT_FILE": ""}):
                files.dispatch("news", params, matched, ["offline"], "2026-09-28")
                first_report = next(profile_dir.glob("news-report-*.txt"))
                self.assertIn("offline", first_report.read_text())
                self.assertIn("2026-09-28", first_report.read_text())
                files.dispatch("cve", params, {"articles": [], "keywords": {}})
                files.dispatch("news", params, matched)

            self.assertEqual(len(list(profile_dir.glob("news-*.json"))), 1)
            self.assertEqual(len(list(profile_dir.glob("cve-*.json"))), 1)
            self.assertEqual(json.loads(next(profile_dir.glob("news-*.json")).read_text())["errors"], None)
            news_reports = list(profile_dir.glob("news-report-*.txt"))
            self.assertEqual(len(news_reports), 1)
            self.assertEqual(len(list(profile_dir.glob("cve-report-*.txt"))), 1)
            self.assertRegex(news_reports[0].name, r"^news-report-\d{2}-\d{2}-\d{4}\.txt$")
            self.assertIn("Example", news_reports[0].read_text())
            self.assertIn("linux: 1", news_reports[0].read_text())

    def test_legacy_file_override_still_works(self):
        """The explicit environment override selects file output despite stdout config."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "override.ndjson"
            with patch.dict(os.environ, {"RSS_LOCAL_OUTPUT_FILE": str(path)}):
                files.dispatch("news", self.security["modules"]["files"], {"articles": []})
            self.assertEqual(json.loads(path.read_text())["run_type"], "news")

    def test_no_implicit_fallback_when_not_routed(self):
        """Do not print or write raw results if files was not explicitly routed."""
        profile = {**self.security, "outputs": {"news": ["slack"]}}
        with redirect_stdout(io.StringIO()) as out:
            runner.dispatch_router("news", {"articles": []}, profile_data=profile, output_modules={})
        self.assertEqual(out.getvalue(), "")

    def test_dispatch_signature_stays_compatible(self):
        """Retain the original five positional integration arguments."""
        calls = []
        module = types.SimpleNamespace(dispatch=lambda *args: calls.append(args))
        profile = {**self.security, "outputs": {"news": ["files"]}}
        runner.dispatch_router("news", {"articles": []}, [], "stale",
                               profile_data=profile, output_modules={"files": module})
        self.assertEqual(calls[0][0], "news")
        self.assertIs(calls[0][1], profile["modules"]["files"])
        self.assertEqual(calls[0][4], "stale")

    def test_feed_processing_keeps_original_keyword_logic(self):
        """Combine job and static keywords through the original processing functions."""
        feeds = FakeFeeds()
        stub = types.SimpleNamespace(feed=feeds)
        search = ["custom"]
        ignore = ["breach"]
        with patch.dict(sys.modules, {"rss_syphon": stub}):
            runner.run_feed_check("cve", search, ignore, lookback_days=8,
                                  profile_data=self.security)
        self.assertEqual(
            feeds.requested,
            [entry["name"] for entry in self.security["feeds"]["cve"]],
        )
        self.assertEqual(
            feeds.searches[0][0],
            search + self.security["keywords"].get("static_keywords", []),
        )
        self.assertEqual(
            feeds.searches[0][1],
            ignore + self.security["keywords"].get("ignored", []),
        )
        self.assertEqual(feeds.searches[0][3], 8)
        self.assertEqual(search, ["custom"])

    def test_invalid_profile_handle_has_clean_cli_error(self):
        """Reject profile traversal without dumping a Python traceback."""
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(runner.main(["--profile", "../outside", "--check-config"]), 1)
        self.assertIn("Invalid profile name", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())

    def test_config_paths_cannot_escape(self):
        """Reject absolute, parent traversal, and symlink escapes."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile_dir = root / "configs"
            profile_dir.mkdir()
            outside = root / "outside.md"
            outside.write_text("secret", encoding="utf-8")
            (profile_dir / "link.md").symlink_to(outside)
            for name in ("../outside.md", str(outside), "link.md"):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        rss_config._profile_path(profile_dir, name)


if __name__ == "__main__":
    unittest.main()
