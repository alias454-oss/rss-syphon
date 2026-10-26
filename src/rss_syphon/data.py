"""
Prepare profile feed and keyword datasets for RSS-Syphon jobs.

Configuration is supplied by config.load_config(). This layer never locates or
reloads syphon.toml, and does not import feed-processing clients.
"""

import tomllib

from .config import _profile_path


def load_data(settings: dict) -> dict:
    """
    Validate and load the selected profile's data without fetching feeds.

    Feed and keyword datasets are read from the selected profile directory.
    The returned dictionary preserves the original integration dispatch shape
    without mutating the supplied configuration dictionary.

    :param settings: Resolved global/profile configuration from config.load_config.
    :return: Configuration with validated feed and keyword datasets.
    :raises ValueError: If job datasets are invalid.
    """
    profile = dict(settings)

    # Dataset files are optional for profiles without jobs. Keep the TOML
    # loading here so config.py handles only executable configuration.
    for section in ("feeds", "keywords"):
        dataset_path = _profile_path(profile["_profile_root"], f"{section}.toml")
        if not dataset_path.exists():
            profile[section] = {}
            continue

        try:
            with dataset_path.open("rb") as stream:
                dataset = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Cannot load '{dataset_path}': {exc}") from exc

        if not isinstance(dataset.get(section), dict):
            raise ValueError(f"Missing or invalid [{section}] table in '{dataset_path}'")
        profile[section] = dataset[section]

    feeds = profile["feeds"]
    for job, options in profile.get("jobs", {}).items():
        if not isinstance(options, dict) or not isinstance(feeds.get(job), list) or not feeds[job]:
            raise ValueError(f"Job '{job}' needs options and a nonempty [feeds].{job} list")
        if any(not isinstance(feed, dict) or not isinstance(feed.get("name"), str)
               or not isinstance(feed.get("url"), str) for feed in feeds[job]):
            raise ValueError(f"Job '{job}' contains invalid feed definitions")
        lookback = options.get("lookback_days", 3)
        if type(lookback) is not int or lookback < 0:
            raise ValueError(f"[jobs.{job}].lookback_days must be nonnegative integer")
        if "hard_ignore" in options and not isinstance(options["hard_ignore"], bool):
            raise ValueError(f"[jobs.{job}].hard_ignore must be boolean")
        for key in ("search_keywords", "ignored_keywords"):
            if key in options and (not isinstance(options[key], list)
                                   or any(not isinstance(item, str) for item in options[key])):
                raise ValueError(f"[jobs.{job}].{key} must be a list of strings")

    for key in ("static_keywords", "ignored"):
        values = profile.get("keywords", {}).get(key, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError(f"[keywords].{key} must be a list of strings")

    return profile
