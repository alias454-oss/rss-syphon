"""
Generate the RSS-Syphon processing pipeline architecture diagram.

Documents configuration loading, feed processing, and modular output routing.
"""

from pathlib import Path

from diagrams import Diagram, Cluster, Edge
from diagrams.programming.language import Python
from diagrams.onprem.client import Client

DIAGRAM_PATH = Path(__file__).resolve().parent / "assets" / "rss_syphon_standard_workflow"

with Diagram("RSS-Syphon Processing Pipeline", filename=str(DIAGRAM_PATH), outformat="png", show=False, direction="LR"):

    # Configuration sources
    with Cluster("Configuration"):
        global_config = Client("syphon.toml")
        profile = Client("Profile TOML")
        config_loader = Python("Config / Data Loader")

    # RSS acquisition
    with Cluster("RSS Sources"):
        feeds = Python("Feed URLs")

    # Core processing
    with Cluster("Processing Pipeline"):
        fetcher = Python("Async Fetcher")
        processor = Python("Parse & Clean")
        filterer = Python("Keyword Filter")
        dispatcher = Python("Dispatch Router")

    # Available output integrations
    with Cluster("Output Modules"):
        files = Python("Files / NDJSON")
        slack = Python("Slack")
        notion = Python("Notion")
        zendesk = Python("Zendesk")

    # Configuration loading
    global_config >> config_loader
    profile >> config_loader

    # Feed acquisition and processing
    config_loader >> Edge(label="jobs / keywords") >> fetcher

    feeds >> Edge(label="fetch") >> fetcher
    fetcher >> processor
    processor >> filterer
    filterer >> dispatcher

    # Outputs execute only when globally enabled and routed by the profile.
    dispatcher >> Edge(color="green") >> files
    dispatcher >> Edge(color="blue", style="dashed") >> slack
    dispatcher >> Edge(color="purple", style="dashed") >> notion
    dispatcher >> Edge(color="orange", style="dashed") >> zendesk