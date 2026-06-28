#!/usr/bin/env python3
"""Run arXiv paper fetching on demand with visible logs."""

import argparse
import logging
import sys
from datetime import datetime, timedelta

# Add project root to path so 'src' imports work
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from src.tasks.fetch_papers import fetch_papers_for_category


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch arXiv papers for a category on a given date."
    )
    parser.add_argument(
        "--category",
        help="arXiv category, e.g. cs.AI",
    )
    parser.add_argument(
        "--date",
        help="Date to fetch (YYYY-MM-DD). Defaults to yesterday.",
        default=None,
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)

    date_str = args.date or (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger = logging.getLogger("fetch_on_demand")
    logger.info("Fetching category=%s date=%s", args.category, date_str)

    # .run() executes the task synchronously in the current process
    # so all logs and prints stream directly to this terminal.
    result = fetch_papers_for_category.run(args.category, date_str)

    logger.info("Result: %s", result)


if __name__ == "__main__":
    main()
