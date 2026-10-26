import requests
import logging
import re
import urllib.parse
import textwrap
import json
from bs4 import BeautifulSoup

# Set module logger name
logger = logging.getLogger(__name__)


def init_notion_client(api_token, api_version):
    """
    Instantiates a Notion requests session for API operations

    :param api_token: Notion API token
    :param api_version: Notion API Version
    :return: Session Object
    """
    logger.debug("Initializing Notion client session.")

    # Setup session
    session_obj = requests.Session()

    # Header for query and patch request operations
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Notion-Version": f"{api_version}",
        "Authorization": f"Bearer {api_token}"
    }
    session_obj.headers.update(headers)

    logger.debug("Notion client session headers set.")
    return session_obj


def check_existing_posts(session, url, db_id):
    """
    Reads MD5_Hash values from DB rows and returns matching content

    :param session: Session Object
    :param url: Base url to use for requests
    :param db_id: ID of the database to operate on
    :return: List of MD5_Hash values found in DB
    """
    # Get pages from DB using database ID
    query_url = urllib.parse.urljoin(url, f"databases/{db_id}/query")
    logger.debug(f"Querying Notion DB for existing posts at URL: {query_url}")

    res = session.post(query_url)

    # Database queries return 100 items per page
    # Results are paginated, see: https://developers.notion.com/reference/post-database-query
    # TODO handle paginating multiple pages
    if res.status_code == 200:
        data = res.json()
        # Iterate through returned database results
        md5_match = []
        for row in data["results"]:
            if "MD5_Hash" in row["properties"]:
                # Get MD5 values if value exists
                if row["properties"]["MD5_Hash"]["rich_text"]:
                    md5_val = row["properties"]["MD5_Hash"]["rich_text"][0]["plain_text"]
                    md5_match.append(md5_val)
                    logger.debug(f"Found MD5 hash in DB: {md5_val}")

        logger.info(f"Found {len(md5_match)} existing MD5 hashes in Notion DB {db_id}.")
        return md5_match
    else:
        msg = f"Error: Notion database query failed for '{db_id}' ({res.status_code} {res.reason})"
        raise RuntimeError(msg)


def post_errors(session, url, db_id, messages):
    """
    This requires the following Notion DB configuration

    Property Name | Property Type
    ------------- | --------------
    Name          | title
    Summary       | rich_text
    Submitted     | Current time

    :param session: Session Object
    :param url: Base url to use for requests
    :param db_id: ID of the database to operate on
    :param messages: Message body content
    """
    logger.debug(f"Posting {len(messages)} error messages to Notion database {db_id}.")
    failed_posts = 0

    for message in messages:
        if message:
            logger.debug(f"Preparing error message payload for '{message.get('title', 'No Title')}'.")

            # Create a new page in the database
            payload = {
                "parent": {
                    "database_id": db_id
                },
                "properties": {
                    "Name": {
                        "title": [
                            {"text": {"content": message["title"]}}
                        ]
                    },
                    "Summary": {
                        "rich_text": [
                            {"text": {"content": message.get("summary", "")}}
                        ]
                    }
                }
            }

            create_url = urllib.parse.urljoin(url, "pages")
            logger.debug(f"Posting error message to Notion API endpoint: {create_url}")
            result = session.post(create_url, data=json.dumps(payload))

            if result.status_code == 200:
                msg = f"Success: Created a new error message for '{message.get('title', 'No Title')}'."
                logger.info(msg)
            else:
                msg = f"Error: API call failed ({result.status_code} {result.reason}): {result.content}"
                logger.error(msg)
                failed_posts += 1

    if failed_posts:
        raise RuntimeError(f"Failed to post {failed_posts} Notion error messages to database {db_id}.")


def post_message(session, url, db_id, messages):
    """
    This requires the following Notion DB configuration

    Property Name | Property Type
    ------------- | --------------
    Name          | title
    MD5_Hash      | rich_text
    Feed          | rich_text
    Type          | rich_text
    Keywords      | multi_select
    Article_Link  | url
    Summary       | rich_text
    CVE_Link      | url
    Submitted     | Current time

    :param session: Session Object
    :param url: Base url to use for requests
    :param db_id: ID of the database to operate on
    :param messages: Message body content
    """
    logger.debug(f"Posting {len(messages)} messages to Notion database {db_id}.")
    failed_posts = 0

    for message in messages:
        if message:
            logger.debug(f"Preparing payload for article '{message.get('title', 'Untitled')}'.")

            # Create a new page in the database
            payload = {
                "parent": {
                    "database_id": db_id
                },
                "properties": {
                    "Name": {
                        "title": [
                            {"text": {"content": message["title"]}}
                        ]
                    },
                    "MD5_Hash": {
                        "rich_text": [
                            {"text": {"content": message.get("md5", "")}}
                        ]
                    },
                    "Feed": {
                        "rich_text": [
                            {"text": {"content": message.get("feed", "")}}
                        ]
                    },
                    "Type": {
                        "rich_text": [
                            {"text": {"content": message.get("type", "")}}
                        ]
                    },
                    "Article_Link": {
                        "url": message.get("link", "")
                    }
                }
            }

            # Handle keywords for multi_select
            if "keywords" in message:
                kw_list = []
                for kw in message["keywords"].split(","):
                    kw_list.append({"name": kw.replace("'", "").strip()})

                keywords = {
                    "Keywords": {
                        "multi_select": kw_list
                    }
                }
                payload["properties"].update(keywords)
                logger.debug(f"Added keywords: {kw_list}")

            # When creating items for CVE jobs add Summary
            if "summary" in message:
                summary = {
                    "Summary": {
                        "rich_text": [
                            {"text": {"content": textwrap.shorten(message["summary"], width=125)}}
                        ]
                    }
                }
                payload["properties"].update(summary)
                logger.debug("Added summary field to payload.")

            # When creating items for CVE jobs add CVE_Link
            if "cve" in message:
                cve_link = {
                    "CVE_Link": {
                        "url": message["cve"]
                    }
                }
                payload["properties"].update(cve_link)
                logger.debug("Added CVE link to payload.")

            create_url = urllib.parse.urljoin(url, "pages")
            logger.debug(f"Posting to Notion API: {create_url}")

            result = session.post(create_url, data=json.dumps(payload))

            if result.status_code == 200:
                msg = f"Success: Created a new entry for '{message.get('title', 'Untitled')}' in Notion."
                logger.info(msg)
            else:
                msg = f"Error: API call failed ({result.status_code} {result.reason}): {result.content}"
                logger.error(msg)
                failed_posts += 1

    if failed_posts:
        raise RuntimeError(f"Failed to post {failed_posts} Notion articles to database {db_id}.")


def clean_html(input_text):
    """
    Summaries often come as html formatted.
    This def uses bs4 to clean that up.

    :param input_text: Text to clean
    :return: Cleaned output
    """
    logger.debug("Cleaning HTML from input text.")
    text = BeautifulSoup(input_text, "lxml").get_text(separator="\n")
    cleaned_text = re.sub('\n\n', '\n', text)
    logger.debug("HTML cleaning complete.")
    return cleaned_text


def build_results_message(feed_results, rss_found_already, rss_type):
    """
    Build message which will be used as the content body

    :param feed_results: Full list of processed rss posts
    :param rss_found_already: Filter for RSS articles found in Slack channel
    :param rss_type: Limited to News or CVE type articles
    :return: Message body content
    """
    md5_stored = []
    return_list = []

    logger.debug(f"Building results message for RSS type '{rss_type}'. Found {len(feed_results.get('articles', []))} articles to process.")

    if feed_results["articles"]:
        for rss_post in feed_results["articles"]:
            if rss_post['md5'] in rss_found_already:
                logger.debug(f"Skipping already-posted article '{rss_post['title']}' (MD5: {rss_post['md5']}).")
                continue
            elif rss_post['md5'] not in md5_stored:
                # Keep track of articles to return using md5
                md5_stored.append(rss_post['md5'])

                post_title = rss_post["title"].lower()
                post_summary = rss_post["summary"].lower()

                # Publishing News
                if rss_type == "news":
                    if not any(x in post_title for x in ["cve", "vulnerability"]):
                        logger.debug(f"Adding news article '{rss_post['title']}' to results.")
                        message = {
                            "title": rss_post['title'],
                            "link": rss_post['link'],
                            "md5": rss_post['md5'],
                            "keywords": rss_post['keywords'],
                            "feed": rss_post['rss_feed_name'],
                            "type": rss_type
                        }

                        if rss_post['summary']:
                            summary = clean_html(str(rss_post['summary']))
                            message.update(summary=summary)

                        return_list.append(message)

                # Publishing CVEs
                elif rss_type == "cve":
                    if ("cve" in post_title) or ("cve" in post_summary):
                        logger.debug(f"Adding CVE article '{rss_post['title']}' to results.")
                        # Parse for CVEs
                        cve_list = []
                        cve_url_list = []

                        cve_regex = r"(CVE-20[0-9]{2}-\d+)"
                        cve_title_results = re.findall(cve_regex, str(rss_post['title']), re.IGNORECASE)
                        cve_summary_results = re.findall(cve_regex, str(rss_post['summary']), re.IGNORECASE)

                        # Check CVE lists and dedup results and readies for results
                        for title_result in cve_title_results:
                            if title_result not in cve_list:
                                cve_list.append(title_result)
                                cve_url_list.append(
                                    f"https://cve.mitre.org/cgi-bin/cvename.cgi?name={title_result}")

                        for summary_result in cve_summary_results:
                            if summary_result not in cve_list:
                                cve_list.append(summary_result)
                                cve_url_list.append(
                                    f"https://cve.mitre.org/cgi-bin/cvename.cgi?name={summary_result}")

                        # Backslashes not allowed in f-string
                        cve_url_list = str(cve_url_list).strip("[]").replace("\'", "")

                        message = {
                            "title": rss_post['title'],
                            "link": rss_post['link'],
                            "md5": rss_post['md5'],
                            "keywords": rss_post['keywords'],
                            "feed": rss_post['rss_feed_name'],
                            "type": rss_type
                        }

                        if rss_post['summary']:
                            summary = clean_html(str(rss_post['summary']))
                            message.update(summary=summary)
                        if cve_url_list:
                            message.update(cve=cve_url_list)

                        return_list.append(message)

    logger.info(f"Built {len(return_list)} messages for '{rss_type}'.")
    return return_list


def dispatch(run_type, message_params, matched, errors, check_stale_keywords=None):
    """
    Send prepared RSS feed results to a Notion DB

    :param run_type: CVE or NEWs job type
    :param message_params: Dictionary of message config values
    :param matched: Keyword matched RSS articles
    :param errors: List of feeds that have an error
    :param check_stale_keywords: None or date
    """
    # Check if module is enabled and bail out if not
    if str(message_params["notion_enabled"]).lower() == "false":
        logger.debug("Debug: Notion not enabled.")
        return None

    api_token = message_params["notion_token"]
    base_url = message_params["base_url"]
    api_version = message_params["api_version"]
    db_id = message_params["databases"]

    # Check if api_token is set
    if api_token:
        logger.info(f"Dispatching '{run_type}' results to Notion.")

        # Init Notion client session
        session = init_notion_client(api_token, api_version)
        logger.debug("Initialized Notion client session.")

        # Check for existing RSS posts in DB
        rss_found = check_existing_posts(session, base_url, db_id[run_type])
        logger.debug(f"Retrieved {len(rss_found)} existing posts from Notion database '{db_id[run_type]}'.")

        # Build the message that will be sent
        build_results = build_results_message(matched, rss_found, run_type)
        if build_results:
            logger.info(f"Posting {len(build_results)} new items to Notion database '{db_id[run_type]}'.")
            post_message(session, base_url, db_id[run_type], build_results)
        else:
            logger.info("No new items to post to Notion.")

        # Feeds that have changes or are offline
        error_messages = []
        if len(errors) > 0:
            logger.warning(f"{len(errors)} feeds reported errors.")
            for feed in errors:
                message = {
                    "title": feed,
                    "summary": f"Feed {feed} is no longer publishing articles"
                }
                error_messages.append(message)

        # Keywords need to be updated
        if check_stale_keywords is not None:
            logger.warning("Keyword list is stale and needs updating.")
            message = {
                "title": "keyword",
                "summary": f"Keyword list was last updated on: {str(check_stale_keywords)}"
            }
            error_messages.append(message)

        if error_messages:
            logger.info(f"Posting {len(error_messages)} error/stale keyword notifications to Notion.")
            post_errors(session, base_url, db_id["error"], error_messages)
        else:
            logger.debug("No error messages to post to Notion.")
    else:
        raise ValueError(f"Notion token is not configured for '{run_type}' output.")
