"""
Verify profile destination settings resolve explicit environment references.

This test needs no external services or credentials. It uses fake values and
reads a temporary TOML configuration through the project's actual config loader.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from rss_syphon import config  # noqa: E402


class EnvironmentReferenceTests(unittest.TestCase):
    """Check nested module settings without contacting destination services."""

    def test_profile_destinations_use_environment_values(self):
        """Resolve per-profile destinations and global credentials independently."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile_dir = root / "profiles" / "security"
            profile_dir.mkdir(parents=True)
            (root / "syphon.toml").write_text(
                '[system]\nprofiles_dir = "./profiles"\n'
                '[modules]\nenabled = []\n'
                '[modules.slack]\nslack_token = "env:SLACK_TOKEN"\n'
                '[modules.notion]\nnotion_token = "env:NOTION_TOKEN"\n'
                '[modules.zendesk]\nzendesk_token = "env:ZENDESK_TOKEN"\n'
                '[modules.splunk]\nsplunk_api_user = "env:SPLUNK_API_USER"\n',
                encoding="utf-8",
            )
            (profile_dir / "profile.toml").write_text(
                '[jobs.news]\nlookback_days = 3\n'
                '[outputs]\nnews = ["slack", "notion", "zendesk"]\n'
                '[modules.slack.channels]\nnews = "env:SLACK_NEWS_CHANNEL_ID"\n'
                '[modules.notion.databases]\nnews = "env:NOTION_NEWS_DATABASE_ID"\n'
                '[modules.zendesk]\nbase_url = "env:ZENDESK_BASE_URL"\n'
                'email = "env:ZENDESK_EMAIL"\n'
                'group_id = "env:ZENDESK_GROUP_ID"\n'
                '[modules.splunk.splunk_host]\n'
                'base_url = "env:SPLUNK_BASE_URL"\nscheme = "https"\nport = 8089\n',
                encoding="utf-8",
            )
            values = {
                "SLACK_TOKEN": "fake-slack-token",
                "SLACK_NEWS_CHANNEL_ID": "C0000000001",
                "NOTION_TOKEN": "fake-notion-token",
                "NOTION_NEWS_DATABASE_ID": "fake-notion-database",
                "ZENDESK_TOKEN": "fake-zendesk-token",
                "ZENDESK_BASE_URL": "https://example.zendesk.com",
                "ZENDESK_EMAIL": "security@example.com",
                "ZENDESK_GROUP_ID": "12345678",
                "SPLUNK_API_USER": "fake-splunk-user",
                "SPLUNK_BASE_URL": "splunk.example.internal",
            }

            # The application reads the process environment; a .env file must
            # be exported or injected by the container runtime separately.
            with patch.dict(os.environ, values):
                result = config.load_config("security", project_root=root)

        modules = result["modules"]
        self.assertEqual(modules["slack"]["slack_token"], values["SLACK_TOKEN"])
        self.assertEqual(modules["slack"]["channels"]["news"], values["SLACK_NEWS_CHANNEL_ID"])
        self.assertEqual(modules["notion"]["databases"]["news"], values["NOTION_NEWS_DATABASE_ID"])
        self.assertEqual(modules["zendesk"]["zendesk_token"], values["ZENDESK_TOKEN"])
        self.assertEqual(modules["zendesk"]["base_url"], values["ZENDESK_BASE_URL"])
        self.assertEqual(modules["zendesk"]["email"], values["ZENDESK_EMAIL"])
        self.assertEqual(modules["zendesk"]["group_id"], values["ZENDESK_GROUP_ID"])
        self.assertEqual(modules["splunk"]["splunk_host"], {
            "base_url": values["SPLUNK_BASE_URL"], "scheme": "https", "port": 8089,
        })


if __name__ == "__main__":
    unittest.main()