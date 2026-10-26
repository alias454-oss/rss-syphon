import asyncio
import hashlib
import logging
import re
import feedparser
import aiohttp
import socket
import ipaddress
from aiohttp import ClientConnectorError
from urllib.parse import urlparse
from datetime import datetime, timedelta
from time import mktime

# Requires adding `feedparser` to the requirements.txt file
# Requires adding `asyncio` to the requirements.txt file
# Requires adding `aiohttp` to the requirements.txt file
# Requires adding `brotli` to the requirements.txt file

# Set module logger name
logger = logging.getLogger(__name__)


async def fetch(sem, session, feed_name, feed_url):
    """
    Fetch RSS results using passed in feed URLs

    :param sem: Semaphore to use with async tasks
    :param session: aiohttp Session object
    :param feed_name: Nice name for RSS feed
    :param feed_url: URL to use when fetching feed data
    :return: Parsed and cleaned results or error
    """
    logger.debug(f"Acquiring semaphore and starting fetch for {feed_name}: {feed_url}")
    async with sem, session.get(feed_url) as response:
        logger.debug(f"Received response for {feed_name} with status {response.status}")
        if response.status == 200:
            data = await response.text()
            logger.debug(f"Fetched {len(data)} bytes from {feed_name}")

            # Strip empty lines from returned data
            stripped = "\n".join([line.rstrip() for line in data.splitlines() if line.strip()])
            logger.debug(f"Stripped data length for {feed_name}: {len(stripped)}")

            rss_page = feedparser.parse(stripped)
            logger.debug(f"Parsed feed for {feed_name}: {len(rss_page.entries)} entries found")

            return rss_page, feed_name
        else:
            msg = f"Error: API call Failed for {feed_name} => {response.status} : {response.reason}"
            logger.error(msg)

            return msg, feed_name


async def fetch_all(feeds_list, max_concurrent: int = 4):
    """
    Takes a list of urls and manages the fetch calls using async functions

    :param feeds_list: List of RSS feed data including name and URL
    :param max_concurrent: Maximum number of concurrent fetches.
    :return: Result values from fetch jobs
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    logger.info(f"Fetching feeds from {len(feeds_list)} URLs with max concurrency {max_concurrent}")

    sem = asyncio.Semaphore(max_concurrent)
    async with aiohttp.ClientSession(headers=headers) as session:
        fetch_res = await asyncio.gather(
            *[fetch(sem, session, feed["name"], feed["url"]) for feed in feeds_list],
            return_exceptions=True
        )
        return fetch_res


def fetch_feed_results(feeds_list):
    """
    Fetch RSS feed data using async functions

    :param feeds_list: List of RSS feed data including name and URL
    :return: Results from fetch_all
    """
    fetched_res = asyncio.run(fetch_all(tuple(feeds_list)))

    return fetched_res


def is_valid_url(url):
    """
    Validate that a URL is properly formatted and uses http(s).

    This checks:
      - Scheme is http or https
      - A hostname is present
      - No parsing errors

    :param url: String containing the URL to validate
    :return: True if URL is valid, False otherwise
    """
    try:
        parsed = urlparse(url)

        # Check if scheme is allowed
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"Rejected URL due to invalid scheme: {url}")
            return False

        # Must have a hostname
        if not parsed.netloc:
            logger.warning(f"Rejected URL due to missing hostname: {url}")
            return False

        # Passed all checks
        return True

    except Exception as e:
        logger.error(f"Error parsing URL '{url}': {e}")
        return False


def is_safe_hostname(hostname):
    """
    Validate that a hostname resolves to a public IP address.

    This checks:
      - Hostname resolves via DNS
      - IP is not private, loopback, or link-local

    :param hostname: String hostname (e.g., "example.com")
    :return: True if hostname is safe, False otherwise
    """
    try:
        # Resolve hostname to IP address
        ip = socket.gethostbyname(hostname)
        parsed_ip = ipaddress.ip_address(ip)

        # Block private networks
        if parsed_ip.is_private:
            logger.warning(f"Rejected hostname due to private IP: {hostname} -> {ip}")
            return False

        # Block loopback addresses
        if parsed_ip.is_loopback:
            logger.warning(f"Rejected hostname due to loopback IP: {hostname} -> {ip}")
            return False

        # Block link-local addresses
        if parsed_ip.is_link_local:
            logger.warning(f"Rejected hostname due to link-local IP: {hostname} -> {ip}")
            return False

        # Passed all checks
        return True

    except socket.gaierror:
        logger.error(f"DNS resolution failed for hostname: {hostname}")
        return False

    except Exception as e:
        logger.error(f"Error validating hostname '{hostname}': {e}")
        return False


def validate_feed_list(feed_list):
    """
    Validate all feed URLs in a given feed list dictionary.

    This checks:
      - URLs are valid http(s) URLs
      - Hostnames resolve to public IPs

    Logs any invalid entries.

    :param feed_list: List of dicts containing 'name' and 'url' keys
    :return: List of valid feeds (same dict format)
    """
    validated = []

    for feed in feed_list:
        url = feed.get("url")
        name = feed.get("name", "Unnamed Feed")

        if not url:
            logger.warning(f"Feed '{name}' is missing a URL. Skipping.")
            continue

        if not is_valid_url(url):
            logger.warning(f"Feed '{name}' has an invalid URL format: {url}. Skipping.")
            continue

        parsed = urlparse(url)
        if not is_safe_hostname(parsed.hostname):
            logger.warning(f"Feed '{name}' resolved to an unsafe hostname: {parsed.hostname}. Skipping.")
            continue

        # Passed all checks
        validated.append(feed)

    logger.info(f"Validated {len(validated)} out of {len(feed_list)} feeds.")
    return validated


def process_feeds(feed_results, feeds_list):
    """
    Clean up data being passed back to the calling
    function and handle any exceptions that were thrown

    :param feed_results: List of RSS feed results
    :param feeds_list: List of RSS feeds including name and URL
    :return: Data without exception objects in the results
    """
    # TODO remove ipv6 sections from regex
    # https://stackoverflow.com/questions/839994/extracting-a-url-in-python/50790119#50790119
    regex = r"\b((?:https?://)?(?:(?:www\.)?(?:[\da-z\.-]+)\.(?:[a-z]{2,6})|" \
            r"(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|" \
            r"[01]?[0-9][0-9]?)|(?:(?:[0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|" \
            r"(?:[0-9a-fA-F]{1,4}:){1,7}:|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|" \
            r"(?:[0-9a-fA-F]{1,4}:){1,5}(?::[0-9a-fA-F]{1,4}){1,2}|" \
            r"(?:[0-9a-fA-F]{1,4}:){1,4}(?::[0-9a-fA-F]{1,4}){1,3}|" \
            r"(?:[0-9a-fA-F]{1,4}:){1,3}(?::[0-9a-fA-F]{1,4}){1,4}|" \
            r"(?:[0-9a-fA-F]{1,4}:){1,2}(?::[0-9a-fA-F]{1,4}){1,5}|" \
            r"[0-9a-fA-F]{1,4}:(?:(?::[0-9a-fA-F]{1,4}){1,6})|" \
            r":(?:(?::[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(?::[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|" \
            r"::(?:ffff(?::0{1,4}){0,1}:){0,1}(?:(?:25[0-5]|(?:2[0-4]|" \
            r"1{0,1}[0-9]){0,1}[0-9])\.){3,3}(?:25[0-5]|(?:2[0-4]|" \
            r"1{0,1}[0-9]){0,1}[0-9])|(?:[0-9a-fA-F]{1,4}:){1,4}:(?:(?:25[0-5]|" \
            r"(?:2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(?:25[0-5]|(?:2[0-4]|" \
            r"1{0,1}[0-9]){0,1}[0-9])))(?::[0-9]{1,4}|[1-5][0-9]{4}|" \
            r"6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|" \
            r"6553[0-5])?(?:/[\w\.-]*)*/?)\b"

    processed_results = []
    for result in feed_results:
        # Defensive: handle if result is an exception type, string, or tuple instead of expected
        if isinstance(result, ClientConnectorError):
            # Lookup name from feeds list when client exception
            match = None
            port = None
            try:
                parsed_item = re.search(regex, str(result))
                if parsed_item:
                    parsed_item = parsed_item.group()
                    match, port = parsed_item.split(':', 1)
            except Exception as e:
                logger.warning(f"Regex parse failed on exception string: {e}")

            for feed in feeds_list:
                # Defensive: ensure keys exist and values are strings before searching
                if any(match and isinstance(url, str) and match in url.lower() for key, url in feed.items()):
                    items = {
                        "entries": None,
                        "message": {
                            "feed_name": feed.get("name", "unknown"),
                            "host_match": match,
                            "port": port,
                            "error": str(result)
                        }
                    }
                    items_list = [items, feed.get("name", "unknown")]
                    processed_results.append(tuple(items_list))

                    # Log the exception result as a warning
                    logger.warning(f"Feed name {feed.get('name', 'unknown')} : {result}")
                    break
        elif isinstance(result, tuple) and len(result) == 2:
            processed_results.append(result)
        else:
            logger.warning(f"Unexpected feed result type: {type(result)}")
            # Append a tuple with empty entries and unknown feed name for consistency
            processed_results.append(({"entries": None, "message": {"error": "Unexpected result type"}}, "unknown"))

    return processed_results


def prepare_feed_message(rss_feeds, keywords_list, ignored_list, hard_ignore=False, lookback_days=0):
    """
    Prepare returned RSS feed posts by validating entries, filtering by date,
    and performing keyword searches.

    Articles sharing an exact URL are retained once per run. The first entry
    keeps its original feed name, with all contributing feeds recorded in
    rss_feed_names. Keyword counts reflect unique matched articles.

    :param rss_feeds: Iterable of (rss_feed_dict, feed_name) tuples.
    :param keywords_list: List of keywords to search articles for.
    :param ignored_list: List of keywords to ignore.
    :param hard_ignore: If True, ignore any occurrence of an ignored keyword.
    :param lookback_days: Number of days to look back for articles (0 = only today).
    :return: Tuple of (matched dict, feed_errors list, date_errors list, old_articles list).
    """
    # Hold feed information
    feed_errors = []
    date_errors = []
    old_articles = []
    matched = {
        "titles": [],
        "articles": [],
        "keywords": {}
    }

    # Overlapping feeds can return the same article URL. Keep one article
    # while retaining its contributing feeds and unique keyword matches.
    article_indexes = {}
    article_keywords = []

    for rss_feed, rss_feed_name in rss_feeds:
        # Defensive: check types before processing
        if not isinstance(rss_feed, dict):
            logger.warning(f"Unexpected feed result type: {type(rss_feed)} for feed '{rss_feed_name}'")
            feed_errors.append(rss_feed_name)
            continue

        # Check API errors, missing entries, url changes, or remote host being offline
        if "Error: API call Failed" in str(rss_feed):
            logger.warning(f"API call failed for feed '{rss_feed_name}'")
            feed_errors.append(rss_feed_name)
            continue
        elif rss_feed.get("entries") is None:
            logger.warning(f"No 'entries' found in feed '{rss_feed_name}'")
            feed_errors.append(rss_feed_name)
            continue

        else:
            # Iterate through feed articles
            for item in rss_feed.get("entries", []):
                try:
                    item_date = None

                    # Try to extract the publication date and compare to timestamp
                    if "published_parsed" in item:
                        item_date = datetime.fromtimestamp(mktime(item["published_parsed"]))
                    elif "updated_parsed" in item:
                        item_date = datetime.fromtimestamp(mktime(item["updated_parsed"]))
                    else:
                        logger.debug(f"No parsed date found for item in feed '{rss_feed_name}'")
                        date_errors.append(rss_feed_name)

                    if item_date is not None:
                        if item_date.date() >= (datetime.now().date() - timedelta(days=lookback_days)):
                            # If we get here, it's an article from today so run a keyword search
                            kw_res = search_keywords(item, keywords_list, ignored_list, rss_feed_name, hard_ignore)

                            # Handle returned search results, deduplicating only
                            # when two feeds link to the same article URL.
                            for article in kw_res["articles"]:
                                article_url = article.get("link")
                                article_index = (
                                    article_indexes.get(article_url)
                                    if isinstance(article_url, str) and article_url
                                    else None
                                )

                                if article_index is None:
                                    article_index = len(matched["articles"])
                                    if isinstance(article_url, str) and article_url:
                                        article_indexes[article_url] = article_index

                                    article["rss_feed_names"] = [rss_feed_name]
                                    matched["articles"].append(article)
                                    matched["titles"].extend(kw_res["titles"])
                                    article_keywords.append([])
                                else:
                                    article = matched["articles"][article_index]
                                    if rss_feed_name not in article["rss_feed_names"]:
                                        article["rss_feed_names"].append(rss_feed_name)

                                # A keyword counts once per unique article even
                                # when several feeds return that article.
                                for kw in kw_res["keywords"]:
                                    if kw not in article_keywords[article_index]:
                                        article_keywords[article_index].append(kw)
                                        matched["keywords"][kw] = matched["keywords"].get(kw, 0) + 1

                                # Preserve the existing string-valued keywords
                                # field expected by current integrations.
                                article["keywords"] = str(article_keywords[article_index]).strip("[]")
                        else:
                            # Otherwise, the article is probably older than today
                            old_articles.append(f"{item_date} - {rss_feed_name} - {item.get('title', 'No Title')}")

                except KeyError as e:
                    logger.error(f"KeyError while processing feed '{rss_feed_name}': {e}")
                    feed_errors.append(rss_feed_name)

    return matched, feed_errors, date_errors, old_articles


def check_ignored_keywords(rss_post, ignore_list):
    """
    Checks for any occurrence of any ignored word in the RSS post

    :param rss_post: RSS post content to check
    :param ignore_list: List of words to ignore
    :return: True if match else False
    """
    for ignored in ignore_list:
        escaped = re.escape(ignored)
        if re.search(f"\\b{escaped}\\b", str(rss_post), re.IGNORECASE):
            return True
    return False


def search_keywords(rss_post, keywords_list, ignored_list, rss_feed_name, hard_ignore=False):
    """
    Search RSS posts using a list of keywords omitting any ignored keywords

    :param rss_post: Dict of RSS post content
    :param keywords_list: List of values to search articles for
    :param ignored_list: List of values to ignored from search
    :param rss_feed_name: Name of the rss feed
    :param hard_ignore: Ignore any occurrence of an ignored keyword
    :return: Matches or Empty values
    """
    # Hold feed information
    matched = {
        "titles": [],
        "articles": [],
        "keywords": {}
    }

    # Remove noisy items from keywords as they cause too many false alerts
    keywords = list(set(keywords_list).difference(ignored_list))

    for keyword in keywords:
        # Don't match if any ignored word is found
        if hard_ignore and check_ignored_keywords(rss_post, ignored_list):
            break

        # Escape any special regex chars to avoid regex errors
        escaped_keyword = re.escape(keyword)

        # Check entire RSS post for full word keyword match
        if re.search(f"\\b{escaped_keyword}\\b", str(rss_post), re.IGNORECASE):
            # Check prior keyword match or not and increment count
            matched["keywords"][keyword] = matched["keywords"].get(keyword, 0) + 1

            # Add origin of RSS feed name
            rss_post['rss_feed_name'] = rss_feed_name
            rss_post["keywords"] = str(list(matched["keywords"].keys())).strip("[]")

            # Skip if post already added to the matched list and continue
            post_title = rss_post.get("title", "").lower()
            if not any(post_title in title.lower() for title in matched["titles"]):
                msg = f"Unique Match: Keyword {keyword} found in post {post_title}"
                logger.debug(msg)
                rss_post["md5"] = hashlib.md5(post_title.encode('utf-8')).hexdigest()

                matched["titles"].append(post_title)
                matched["articles"].append(rss_post)

    return matched


def check_last_modified(date, days=90):
    """
    Check if date delta is within a certain amount of days

    :param date: Date to check
    :param days: Days to verify delta for
    :return: None or date
    """
    try:
        last_modified = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        logger.warning(f"Invalid date format: {date}")
        return None

    delta = datetime.now() - last_modified

    if delta.days > days:
        return date

    return None
