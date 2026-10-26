import logging
import json
import splunklib.client as client
from splunklib import results
from splunklib.binding import HTTPError

# Requires adding splunk-sdk>=1.6.18 to the requirements.txt file

# Set module logger name
logger = logging.getLogger(__name__)


def init_splunk_client(host, api_user, api_pass, port=8089, scheme="https"):
    """
    Initialize a connection with the Splunk API

    :param host: Splunk host FQDN or IP for client connection
    :param api_user: API user
    :param api_pass: API password
    :param port: Port to connect on. Defaults to 8089
    :param scheme: Use http(s). Defaults to https
    :return: Splunk client connection object
    """
    logger.debug(f"Debug: Initializing Splunk client connection to {scheme}://{host}:{port}")
    try:
        # Create a Splunk client connection object
        con = client.connect(host=host, port=port, username=api_user, password=api_pass, scheme=scheme)
        logger.info(f"Info: Successfully connected to Splunk at {host}:{port}")
        return con
    except HTTPError as e:
        msg = f"Error: HTTP error while connecting to Splunk: {e}"
        logger.error(msg)
        raise
    except Exception as e:
        msg = f"Error: Unexpected error while connecting to Splunk: {e}"
        logger.error(msg)
        raise


def validate_spl(query, splunk_con):
    """
    Check if the Splunk query syntax is correct

    :param query: Splunk SPL to validate
    :param splunk_con: Splunk client connection object
    :return: True if success False if not
    """
    logger.debug(f"Debug: Validating SPL query syntax: {query}")
    try:
        splunk_con.parse(query, parse_only=True)
        logger.info("Info: SPL query syntax validation succeeded.")
        return True
    except Exception as e:
        logger.error(f"Error: SPL query validation failed: {e}")
        return False


def oneshot_search(query, args, splunk_con):
    """
    Splunk OneShot search runs a search and wait for the results

    :param query: Splunk SPL to use as search
    :param args: Search arguments like output_mode, earliest/latest time etc.
    :param splunk_con: Splunk client connection object
    :return: Search results or error
    """
    logger.debug(f"Debug: Validating SPL query: {query}")
    if validate_spl(query, splunk_con):
        try:
            logger.info("Info: Starting Splunk oneshot search.")
            res = splunk_con.jobs.oneshot(query, **args)

            logger.debug(f"Debug: Search completed. Preparing results in {args.get('output_mode', 'xml')} mode.")

            # Prep results prior to returning them
            if args.get("output_mode") == "xml":
                # If xml, iterate returned data
                # for event in search_results:
                #     print(event)
                search_results = results.ResultsReader(res)
            elif args.get("output_mode") == "csv":
                # Data is returned as csv output
                # print(search_results)
                search_results = res.read().decode()
            elif args.get("output_mode") == "json":
                # Return a JSON object
                # print(search["results"])
                search_results = json.loads(res.read())
            else:
                # XML returned by default
                search_results = results.ResultsReader(res)

            logger.info("Info: Splunk oneshot search results prepared successfully.")
            return search_results

        except HTTPError as e:
            logger.error(f"Error: HTTP error during oneshot search: {e}")
            return f"Error: An error occurred {e}"

    logger.warning("Warning: SPL query validation failed. Search will not run.")
    return "Failed to validate search"


def get_splunk_results(message_params):
    """
     Performs a simple OneShot Splunk search and returns the results

    :param message_params: Dictionary of config values
    :return: Results from the Search
    """
    # Check if module is enabled and bail out if not
    if str(message_params["splunk_enabled"]).lower() == "false":
        logger.debug("Debug: Splunk not enabled.")
        return None

    api_user = message_params["splunk_api_user"]
    api_pass = message_params["splunk_api_pass"]
    splunk_host = message_params["splunk_host"]

    if api_pass and api_user:
        # Init Splunk client
        logger.info("Info: Initializing Splunk client session.")

        splunk_client = init_splunk_client(
            splunk_host["base_url"], api_user, api_pass, splunk_host["port"], splunk_host["scheme"]
        )

        # Pull search results formatted as a list
        logger.debug(f"Debug: Running Splunk search query: {message_params['search']['query']}")
        search = message_params["search"]
        search_results = oneshot_search(search["query"], search["args"], splunk_client)
        if "packages" in search_results.get("results", [])[0]:
            logger.info("Info: Returned packages from Splunk search results")
            search_keywords = search_results["results"][0]["packages"]
        else:
            logger.warning("Warn: Splunk search results had no packages")
            search_keywords = []

        logger.debug(f"Debug: Extracted {len(search_keywords)} keywords from Splunk.")
        return search_keywords
    else:
        msg = "Warning: No Splunk credentials set. No additional packages will be returned."
        logger.warning(msg)
        return []
