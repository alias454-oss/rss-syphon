"""
Run configured RSS feed jobs and dispatch results to selected output modules.

The existing feed processing and integration dispatch contracts are preserved.
"""

import argparse
import logging
import sys
from datetime import datetime
from importlib import import_module

from . import config, data

# Module paths follow src/<module>/<module>.py and are imported only when
# globally enabled and referenced by a profile. No registry needs updating.
# Each module must define a dispatch() function.

# Set default logging level and format after loading syphon.toml.
# LOG_LEVEL and LOG_FORMAT still override the TOML settings.

# Set logger name
logger = logging.getLogger(__name__)


def run_feed_check(feed_type, search_keywords=None, ignored_keywords=None, hard_ignore=False, lookback_days=3, *, profile_data=None):
    """
    Daily intel job to control and provide general company-wide awareness
    Can use multiple RSS feeds for different types of jobs

    :param feed_type: Feed section name
    :param search_keywords: Optional list of additional search keywords
    :param ignored_keywords: Optional list of additional keywords to ignore
    :param hard_ignore: Ignore any occurrence of an ignored keyword
    :param lookback_days: Defaults to today: Set a lookback for old article retrival on new deployments
    :param profile_data: Selected profile containing feed and keyword datasets
    :return: Matched RSS articles
    """
    import rss_syphon as syphon

    if profile_data is None:
        profile_data = data.load_data(config.load_config())

    # Defensive: Ensure lists if None
    if search_keywords is None:
        search_keywords = []
    if ignored_keywords is None:
        ignored_keywords = []

    # Extend with static keywords and ignored keywords from config
    search_keywords = list(search_keywords)
    ignored_keywords = list(ignored_keywords)
    search_keywords.extend(profile_data["keywords"].get("static_keywords", []))
    ignored_keywords.extend(profile_data["keywords"].get("ignored", []))

    # Defensive: Ensure feed_type exists in config
    feed_list = profile_data["feeds"].get(feed_type)
    if not feed_list:
        logger.error(f"Feed type '{feed_type}' is not defined in profile '{profile_data['name']}'")
        return {}, [], []

    # Validate feeds before processing
    feed_list = syphon.feed.validate_feed_list(feed_list)

    # Process RSS feeds searching for keyword data
    feed_data = syphon.feed.fetch_feed_results(feed_list)
    cleaned_feed = syphon.feed.process_feeds(feed_data, feed_list)

    # Get data that will be processed and sent
    matches, feed_errors, date_errors, old_articles = syphon.feed.prepare_feed_message(
        cleaned_feed, search_keywords, ignored_keywords, hard_ignore, lookback_days
    )

    return matches, feed_errors, old_articles


def dispatch_router(run_type, matched, errors=None, check_stale_keywords=None, *, profile_data=None, output_modules=None):
    """
    Send feed results dynamically to all configured output modules for a run type.

    Uses OUTPUT_ROUTING and OUTPUT_MODULES to call each module's dispatch() function
    if enabled in config. Handles logging and errors internally.

    Note:
        Some modules' dispatch() implementations may not require the 'errors' or
        'check_stale_keywords' arguments. These are always passed as optional parameters,
        and individual modules can choose to ignore them in their function signature.

    :param run_type: str
        The feed type, e.g., "news", "cve", etc.
    :param matched: dict or list
        Matched feed results for this run type.
    :param errors: Optional[list]
        List of feed errors encountered during checking. Not all modules use this.
    :param check_stale_keywords: Optional
        Timestamp or flag indicating stale keyword state. Not all modules use this.
    :param profile_data: Selected profile with output routes and module settings.
    :param output_modules: Imported, enabled output modules.
    """
    if profile_data is None:
        profile_data = data.load_data(config.load_config())
    if output_modules is None:
        output_modules = load_modules(profile_data)

    modules_to_call = profile_data["outputs"].get(run_type, [])
    for module_name in modules_to_call:
        out_module = output_modules.get(module_name)
        if not out_module:
            logger.info(f"Output '{module_name}' is not enabled globally; skipping route")
            continue

        # Get the params dict for this module from your config
        params = profile_data["modules"].get(module_name)
        if not params:
            logger.warning(f"No config params found for output '{module_name}'")
            continue

        # Check the global enable flag, supplied through the legacy params shape.
        enabled_key = f"{module_name}_enabled"
        if not params.get(enabled_key, False):
            logger.info(f"{module_name.capitalize()} output is disabled via config.")
            continue

        try:
            # Call the dispatch function dynamically
            send_func = getattr(out_module, "dispatch", None)
            if not send_func:
                logger.warning(f"{module_name.capitalize()} module does not implement dispatch()")
                continue

            send_func(run_type, params, matched, errors, check_stale_keywords)
            logger.info(f"Sent '{run_type}' results via '{module_name}'")
        except Exception as e:
            logger.error(f"Error sending '{run_type}' via '{module_name}': {e}")

    # Raw result handling belongs to the files output module. No implicit
    # fallback occurs when other integrations are disabled or fail.


def load_modules(profile_data: dict) -> dict:
    """
    Import routed output modules enabled by syphon.toml.

    :param profile_data: Profile containing global module permissions and routes.
    :return: Module objects keyed by their configured names.
    :raises RuntimeError: If an enabled module cannot be imported.
    """
    modules = {}
    routed = {name for destinations in profile_data["outputs"].values() for name in destinations}
    for name in profile_data["enabled_modules"]:
        if name not in routed:
            continue

        try:
            modules[name] = import_module(f"rss_syphon.modules.{name}")
        except ImportError as exc:
            raise RuntimeError(f"Cannot load enabled module '{name}': {exc}") from exc

        # Defensive sanity check:
        if modules[name] is None:
            raise RuntimeError(f"Module '{name}' is None. Check your imports!")
    return modules


def run_profile(profile_data: dict) -> None:
    """
    Execute only the jobs explicitly declared by the selected profile.

    :param profile_data: Loaded profile settings and feed data.
    :return: None. Output modules handle delivery.
    """
    # Keep track of script execution time
    begin_time = datetime.now()

    # Fail before feed collection if a routed, enabled output module is unavailable.
    modules = load_modules(profile_data)

    # Check for stale keywords
    update_keywords = None
    if profile_data["jobs"]:
        import rss_syphon as syphon

        last_modified = profile_data["keywords"].get("last_modified", "")
        update_keywords = syphon.feed.check_last_modified(last_modified)

    #########################################################
    # Check configured Feeds and send to destination if enabled
    #########################################################
    for run_type, job in profile_data["jobs"].items():
        matched, feed_errors, old_articles = run_feed_check(
            run_type,
            search_keywords=job.get("search_keywords"),
            ignored_keywords=job.get("ignored_keywords"),
            hard_ignore=job.get("hard_ignore", False),
            lookback_days=job.get("lookback_days", 3),
            profile_data=profile_data,
        )
        dispatch_router(run_type, matched, feed_errors, update_keywords,
                        profile_data=profile_data, output_modules=modules)

    # Log how long it took the script to run
    elapsed = datetime.now() - begin_time
    logger.info(f"Timer: RSS-Syphon Executed in {elapsed}")


def main(argv: list[str] | None = None) -> int:
    """
    Select a profile, configure logging, and run declared feed jobs.

    :param argv: CLI arguments or None for process arguments.
    :return: Exit code, zero on success and nonzero on failure.
    """
    parser = argparse.ArgumentParser(description="Run RSS-Syphon with a named profile")
    parser.add_argument("--profile", help="Profile name (default: RSS_PROFILE or syphon.toml)")
    parser.add_argument("--check-config", action="store_true", help="Validate configuration without fetching")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    verbosity.add_argument("--quiet", action="store_true", help="Show errors only")
    args = parser.parse_args(argv)

    try:
        profile_data = data.load_data(config.load_config(args.profile))
        logging_options = profile_data["logging"]
        level = "DEBUG" if args.verbose else "ERROR" if args.quiet else logging_options["level"]
        logging.basicConfig(format=logging_options["format"], level=level)

        if args.check_config:
            # Inspect profile structure without printing resolved secrets.
            print(f"Profile: {profile_data['name']}")
            print(f"Jobs: {', '.join(profile_data['jobs']) or '(none)'}")
            print(f"Enabled modules: {', '.join(profile_data['enabled_modules']) or '(none)'}")
            return 0

        run_profile(profile_data)
        return 0
    except Exception as exc:
        # Only the CLI boundary catches unexpected execution errors.
        print(f"RSS-Syphon: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
