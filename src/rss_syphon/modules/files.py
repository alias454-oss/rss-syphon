"""
Write raw RSS-Syphon results to stdout or a daily JSON snapshot.
Optionally write a plain-text report for each job.

This is a production output integration with the same dispatch() signature as
Slack, Notion, and Zendesk. The caller decides whether it is enabled and routed.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)


def dispatch(run_type, message_params, matched, errors=None, check_stale_keywords=None):
    """
    Write one result record through the configured file destination.

    :param run_type: Feed job name, such as news or cve.
    :param message_params: File destination and path configuration.
    :param matched: Keyword-matched articles or generated results.
    :param errors: Feed errors, if any.
    :param check_stale_keywords: Existing stale-keyword warning value.
    :return: JSON output path for file mode or None for stdout.
    :raises OSError: When the selected output file cannot be written.
    """
    if not message_params.get("files_enabled", False):
        logger.debug("File output is disabled.")
        return None

    # Preserve the original local output record contract. Files are an
    # explicitly configured destination, not a side effect of failed routing.
    now = datetime.now(timezone.utc)
    record = {
        "timestamp": now.isoformat(),
        "run_type": run_type,
        "matched": matched,
        "errors": errors,
        "check_stale_keywords": check_stale_keywords,
    }

    # An exported override retains the prior local-file behavior for scripts
    # that already use RSS_LOCAL_OUTPUT_FILE.
    override = os.getenv("RSS_LOCAL_OUTPUT_FILE")
    destination = "file" if override else message_params.get("destination", "stdout")
    if destination == "stdout":
        print(json.dumps(record, indent=2, ensure_ascii=False, default=str))
        return None

    if destination != "file":
        raise ValueError(f"Unsupported file destination: {destination}")

    path = Path(override or message_params["path"])
    report_enabled = message_params.get("report", False)
    if not override or report_enabled:
        # Keep different jobs' results separate without requiring a path for
        # every new job. Report filenames also use the job name.
        if not isinstance(run_type, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", run_type):
            raise ValueError(f"Invalid job type for file output: {run_type!r}")
    stamp = datetime.now().strftime("%m-%d-%Y")
    if not override:
        # Keep one snapshot per job and day; the configured path supplies the directory.
        path = path.with_name(f"{run_type}-{stamp}.json")

    path.parent.mkdir(parents=True, exist_ok=True)
    if override:
        # The explicit legacy override still appends NDJSON to its exact filename.
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    else:
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    logger.info("Saved '%s' results to '%s'", run_type, path)

    if report_enabled:
        # Keep daily job reports alongside JSON snapshots without collecting them across jobs.
        report_path = path.with_name(f"{run_type}-report-{stamp}.txt")
        report_path.write_text(_build_report(record), encoding="utf-8")
        logger.info("Saved '%s' report to '%s'", run_type, report_path)

    return path


def _build_report(record):
    """Format one job's results as a readable plain-text report."""
    matched = record["matched"]
    articles = matched.get("articles", [])
    keywords = matched.get("keywords", {})
    errors = record["errors"] or []

    lines = [
        f"RSS-Syphon Report: {record['run_type']}",
        f"Generated: {record['timestamp']}",
        f"Matched articles: {len(articles)}",
        "",
        "Articles",
        "--------",
    ]

    if articles:
        for number, article in enumerate(articles, start=1):
            lines.extend([
                f"{number}. {article.get('title', '')}",
                f"   Link: {article.get('link', '')}",
                f"   Keyword(s): {article.get('keywords', '')}",
                f"   Feed: {article.get('rss_feed_name', '')}",
                "",
            ])
    else:
        lines.extend(["No matched articles.", ""])

    lines.extend(["Keyword Counts", "--------------"])
    if keywords:
        for keyword, count in sorted(keywords.items()):
            lines.append(f"{keyword}: {count}")
    else:
        lines.append("No keyword matches.")

    lines.extend(["", "Feed Errors", "-----------"])
    if errors:
        lines.extend(str(error) for error in errors)
    else:
        lines.append("None")

    if record["check_stale_keywords"] is not None:
        lines.extend([
            "",
            f"Keyword list last updated: {record['check_stale_keywords']}",
        ])

    return "\n".join(lines) + "\n"
