"""
RSS-Syphon package.

Feed parsing is optional until a job executes; importing config, data, or CLI
help must not load feed-processing dependencies.
"""

from importlib import import_module


def __getattr__(name: str):
    """
    Keep the existing rss_syphon.feed attribute lazily available.

    :param name: Requested package attribute.
    :return: Feed-processing module when requested.
    :raises AttributeError: If the attribute is not supported.
    """
    if name == "feed":
        return import_module(".feed", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
