import requests
import logging
from datetime import datetime

# Set module logger name
logger = logging.getLogger(__name__)


def get_groups(base_url, api_token):
    """
    Get groups from Zendesk support instance

    :param base_url: Base url for the request
    :param api_token: API token used for the request
    :return: list of groups
    """
    if api_token is not None:
        logger.info("Fetching Zendesk groups list.")
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + api_token
        }
        full_url = f"{base_url}/api/v2/groups.json"

        # Setup session
        session = requests.Session()

        groups = []
        while full_url:
            res = session.get(full_url, headers=headers, stream=True)

            if res.status_code == 200:
                # Get JSON data
                group_data = res.json()

                if "groups" in group_data:
                    groups.extend(group_data["groups"])

                # If next_page key not found, value is None
                # otherwise, value is based on next_page value
                full_url = group_data.get("next_page")
            else:
                msg = f"Error: API call Failed {res.status_code} : {res.reason}"
                logger.error(msg)
                raise ValueError(msg)

        logger.info(f"Fetched {len(groups)} groups from Zendesk.")
        return groups
    else:
        msg = "Error: Missing API key for Zendesk"
        logger.error(msg)
        raise ValueError(msg)


def create_ticket(base_url, email, subject, body, group_id, api_token):
    """
    Create a Zendesk ticket using the API

    Example:
      subject = "hello there!"
      mail_body = "Here's a new ticket for you!"

      response = create_zendesk_ticket(subject, mail_body)\n

    :param base_url: Base url of the Zendesk Support instance
    :param email: Authorized user's email that can create a Zendesk ticket
    :param subject: Subject of the ticket
    :param body: Content body of the ticket
    :param group_id: Numeric group ID to assign the ticket to
    :param api_token: API token used for the request
    :return: Zendesk API response or error message
    """
    if api_token is not None:
        logger.info(f"Creating Zendesk ticket with subject: {subject}")
        payload = {
            "ticket": {
                "subject": subject,
                "comment": {
                    "body": body
                },
                "priority": "normal",
                "group_id": int(group_id)
            }
        }

        full_url = f"{base_url}/api/v2/tickets.json"
        try:
            res = requests.post(full_url, json=payload, auth=(f"{email}/token", api_token))
            if res.status_code in [200, 201]:
                msg = f"Success: Message sent {res.status_code} : {res.reason}"
                logger.info(msg)
                return msg
            else:
                msg = f"Error: API call Failed {res.status_code} : {res.reason}"
                logger.error(msg)
                raise ValueError(msg)
        except Exception as e:
            logger.error(f"Exception occurred while creating Zendesk ticket: {e}")
            raise
    else:
        msg = "Error: Missing API key for Zendesk"
        logger.error(msg)
        raise ValueError(msg)


def build_results_message(feed_results, feed_error_details, update_keywords=None):
    """
    Build message which will be used as the content body

    :param feed_results: Full list of processed rss posts
    :param feed_error_details: List of feeds that have an error
    :param update_keywords: Pass in a date string like 2022-03-03
    :return: Message body content
    """
    logger.debug("Building results message for dispatch.")
    res = ""

    if update_keywords is not None:
        logger.info(f"Keywords list is stale, last updated on {update_keywords}. Adding update notice.")
        res += "-------------------------------------------------------------------------------------------------\n"
        res += " [ ! ] KEYWORD LIST ACTION REQUIRED [ ! ]\n"
        res += "-------------------------------------------------------------------------------------------------\n"
        res += "Keyword list was last updated on: " + str(update_keywords) + "\n"
        res += "Keyword list is past 90 days old and needs to be updated.\n\n"
        res += (
            "Please follow the steps outlined here to update before tomorrow's run:\n"
            "<add steps to remediate>\n\n"
        )
        res += "Once completed, please update this ticket for tracking purposes.\n\n"

    # Check for feeds that have changes
    if len(feed_error_details) > 0:
        logger.warning(f"Feeds with errors found: {feed_error_details}. Adding feed error notice.")
        res += "-------------------------------------------------------------------------------------------------\n"
        res += " [ ! ] FEED ACTION REQUIRED [ ! ]\n"
        res += "-------------------------------------------------------------------------------------------------\n"
        res += "The following feeds are no longer publishing articles:\n"

        for feed in feed_error_details:
            res += str(feed) + "\n"
        res += "\n"

    res += "---------------------------------------------------------------------------------------------------\n"
    res += " Daily News Summary\n"
    res += "---------------------------------------------------------------------------------------------------\n"

    for rss_post in feed_results["articles"]:
        # Include in result
        res += rss_post["title"] + "\n"
        res += "Link: " + rss_post["link"] + "\n"
        res += "Keyword: " + rss_post["keywords"] + "\n"
        res += "Feed: " + rss_post["rss_feed_name"] + "\n\n"

    if feed_results["keywords"]:
        logger.debug("Including matched keywords and counts in message.")
        res += "--------------------------------------------------------------------------------------------------\n"
        res += " Matched keywords found in listed articles and the counts for each\n"
        res += " Please remove non-relevant keywords in RSS data file and document changes in this ticket\n\n"
        res += " " + str(feed_results["keywords"]) + "\n\n"
        res += "--------------------------------------------------------------------------------------------------\n"
    else:
        logger.debug("No keyword matches found to include in message.")
        res += "No Keyword Matches"

    logger.debug("Results message build complete.")
    return res


def dispatch(run_type, message_params, matched, errors, check_stale_keywords=None):
    """
    Send prepared RSS feed results to a Zendesk instance

    :param run_type: CVE or NEWs job type
    :param message_params: Dictionary of message config values
    :param matched: Keyword matched RSS articles
    :param errors: List of feeds that have an error
    :param check_stale_keywords: None or date
    """
    # Check if module is enabled and bail out if not
    if str(message_params["zendesk_enabled"]).lower() == "false":
        logger.debug("Debug: Zendesk not enabled.")
        return None

    api_token = message_params["zendesk_token"]

    # Check if api_token is set
    if api_token:
        logger.info(f"Dispatching '{run_type}' data to Zendesk.")
        # Build the message that will be sent
        message_body = build_results_message(matched, errors, check_stale_keywords)
        if message_body:
            subject = f"Daily Vulnerability Intel ({datetime.now().date().strftime('%b %d %Y')})"

            base_url = message_params["base_url"]
            email = message_params["email"]
            group_id = message_params["group_id"]

            # Create an issue using prepared feed results
            create_ticket(base_url, email, subject, message_body, group_id, api_token)
            logger.info(f"Zendesk ticket created for '{run_type}'.")
        else:
            logger.info(f"No message body generated for '{run_type}', skipping Zendesk ticket creation.")
    else:
        raise ValueError(f"Zendesk token is not configured for '{run_type}' output.")
