# Changelog

Local development history for RSS-Syphon. Entries describe changes, not
necessarily tagged releases.

## Unreleased

### 2026-10-26 — Profile-based collection and output refactor

- Split executable configuration (`rss_syphon/config.py`) from validated
  feed and keyword datasets (`rss_syphon/data.py`).
- Added a sanitized `syphon.conf` template and profile directories containing
  `profile.toml`, `feeds.toml`, and `keywords.toml`. The active `syphon.toml`
  remains local and excluded from Git; shared credentials use environment references.
- Reorganized the CLI as `src/rss_syphon/cli.py` with a lightweight
  `src/syphon.py` wrapper and optional `python -m rss_syphon` invocation.
- Consolidated output integrations under `rss_syphon/modules/` with name-based,
  lazy dispatch. Globally disabled outputs are skipped without blocking other
  destinations.
- Preserved RSS processing behavior, keyword filtering, and the Splunk keyword
  retrieval helper. Splunk keyword retrieval remains available for explicit
  integration but is not invoked by the standard job runner.
- Added URL-based article deduplication while retaining matched keywords and
  source attribution.
- Added explicit local JSON output with one dated snapshot per job and an
  optional matching text report. Repeated daily runs replace those files.
  The explicit `RSS_LOCAL_OUTPUT_FILE` override retains append-only NDJSON.
- Retained the `LOG_LEVEL`, `LOG_FORMAT`, and `RSS_PROFILE` environment
  overrides and added profile, routing, and output regression tests.
- Added `pyproject.toml` and a hashed `requirements.txt` lock for Python
  3.12 and 3.13. Updated Docker to Python 3.13 on Debian Bookworm.
- Moved workflow diagram sources and images to `docs/`; the optional diagram
  tool dependencies are separate from runtime dependencies.

## 2025-06-28

### Brotli HTTP compression

- Added the `brotli` package for compressed HTTP responses.

### Environment variable booleans

- Added `str_to_bool` so values returned by `os.getenv()` such as `"true"` and
  `"false"` become actual Python booleans rather than truthy strings.

### RSS feed processing

- Added `lookback_days` to `run_feed_check` and `prepare_feed_message` to
  support processing older articles.
- Added defensive checks for feed-type existence and feed-result types.
- Improved `aiohttp` headers and `asyncio` usage when fetching feeds.
- Improved regex escaping for keywords and ignored terms.
- Improved date-parsing and feed-processing error handling and logging.
- Cleaned up imports and logging timer calculation.
