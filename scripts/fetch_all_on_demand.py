#!/usr/bin/env python3
"""Run arXiv paper fetching for ALL categories on demand with visible logs."""

import argparse
import logging
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from src.categories import ArxivCategory
from src.tasks.fetch_papers import fetch_papers_for_category


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch arXiv papers for ALL categories on a given date."
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
    logger = logging.getLogger("fetch_all_on_demand")

    date_str = args.date or (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info("Fetching all categories for date=%s", date_str)

    for category in ArxivCategory:
        logger.info("=" * 50)
        logger.info("Starting %s", category.value)
        try:
            result = fetch_papers_for_category.run(category.value, date_str)
            logger.info("Finished %s: %s", category.value, result)
        except Exception:
            logger.exception("Failed %s", category.value)

    logger.info("=" * 50)
    logger.info("Done.")


if __name__ == "__main__":
    main()
