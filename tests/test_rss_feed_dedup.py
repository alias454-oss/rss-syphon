"""
Verify that overlapping RSS feeds do not duplicate matched articles.

These tests exercise local aggregation without fetching network resources.
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# Keep the existing src/ script layout importable during test discovery.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rss_syphon.feed import prepare_feed_message


class FeedDedupTests(unittest.TestCase):
    """Check article identity, keyword totals, and source provenance."""

    @staticmethod
    def article(title, summary, link=None, days_old=0):
        """
        Construct a feed entry with a valid publication date.

        :param title: Article title.
        :param summary: Text searched for keywords.
        :param link: Optional article URL.
        :param days_old: Publication age in days.
        :return: Feed entry dictionary.
        """
        entry = {
            "title": title,
            "summary": summary,
            "published_parsed": (datetime.now() - timedelta(days=days_old)).timetuple(),
        }
        if link is not None:
            entry["link"] = link
        return entry

    def test_duplicate_url_preserves_both_sources(self):
        """One article returned by two feeds is counted only once."""
        url = "https://example.com/advisory/1"
        feeds = [
            ({"entries": [self.article("Linux advisory", "linux", url)]}, "general"),
            ({"entries": [self.article("Linux advisory", "linux", url)]}, "specialized"),
        ]

        matched, errors, date_errors, old_articles = prepare_feed_message(
            feeds, ["linux"], [], lookback_days=1
        )

        self.assertEqual(len(matched["articles"]), 1)
        self.assertEqual(matched["titles"], ["linux advisory"])
        self.assertEqual(matched["keywords"], {"linux": 1})
        self.assertEqual(matched["articles"][0]["rss_feed_name"], "general")
        self.assertEqual(matched["articles"][0]["rss_feed_names"], ["general", "specialized"])
        self.assertEqual((errors, date_errors, old_articles), ([], [], []))

    def test_duplicate_url_merges_distinct_keywords(self):
        """Count the union of matching keywords for the retained URL."""
        url = "https://example.com/advisory/2"
        feeds = [
            ({"entries": [self.article("Advisory", "linux", url)]}, "original"),
            ({"entries": [self.article("Advisory", "openssl", url)]}, "updated"),
        ]

        matched, _, _, _ = prepare_feed_message(feeds, ["linux", "openssl"], [], lookback_days=1)

        self.assertEqual(matched["keywords"], {"linux": 1, "openssl": 1})
        self.assertEqual(len(matched["articles"]), 1)
        self.assertIn("'linux'", matched["articles"][0]["keywords"])
        self.assertIn("'openssl'", matched["articles"][0]["keywords"])

    def test_multiple_keywords_are_counted_once_each(self):
        """Repeated multi-keyword articles preserve unique per-keyword totals."""
        url = "https://example.com/advisory/3"
        feeds = [
            ({"entries": [self.article("Advisory", "linux and openssl", url)]}, "general"),
            ({"entries": [self.article("Advisory", "linux and openssl", url)]}, "specialized"),
        ]

        matched, _, _, _ = prepare_feed_message(feeds, ["linux", "openssl"], [], lookback_days=1)

        self.assertEqual(len(matched["articles"]), 1)
        self.assertEqual(matched["keywords"], {"linux": 1, "openssl": 1})
        self.assertEqual(matched["articles"][0]["rss_feed_names"], ["general", "specialized"])

    def test_identical_titles_with_different_urls_are_retained(self):
        """Different publisher URLs must not collapse into one article."""
        feeds = [
            ({"entries": [self.article("Same title", "linux", "https://a.example/news")]}, "a"),
            ({"entries": [self.article("Same title", "linux", "https://b.example/news")]}, "b"),
        ]

        matched, _, _, _ = prepare_feed_message(feeds, ["linux"], [], lookback_days=1)

        self.assertEqual(len(matched["articles"]), 2)
        self.assertEqual(matched["keywords"], {"linux": 2})
        self.assertEqual([item["rss_feed_names"] for item in matched["articles"]], [["a"], ["b"]])

    def test_articles_without_urls_remain_independent(self):
        """Do not merge unrelated entries merely because URLs are absent."""
        feeds = [
            ({"entries": [self.article("Same title", "linux")]}, "a"),
            ({"entries": [self.article("Same title", "linux")]}, "b"),
        ]

        matched, _, _, _ = prepare_feed_message(feeds, ["linux"], [], lookback_days=1)

        self.assertEqual(len(matched["articles"]), 2)
        self.assertEqual(matched["keywords"], {"linux": 2})

    def test_feed_errors_and_date_filtering_remain_unchanged(self):
        """Deduplication must not alter existing errors or lookback behavior."""
        feeds = [
            ({"entries": [self.article("Old advisory", "linux", days_old=7)]}, "old"),
            ("Error: API call Failed for missing => 404", "missing"),
        ]

        matched, errors, date_errors, old_articles = prepare_feed_message(
            feeds, ["linux"], [], lookback_days=1
        )

        self.assertEqual(matched, {"titles": [], "articles": [], "keywords": {}})
        self.assertEqual(errors, ["missing"])
        self.assertEqual(date_errors, [])
        self.assertEqual(len(old_articles), 1)


if __name__ == "__main__":
    unittest.main()
