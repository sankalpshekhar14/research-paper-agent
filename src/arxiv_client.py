"""Lightweight arXiv API client using the built-in Atom feed parser."""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Tuple

import requests

from src.categories import ArxivCategory
from src.config import settings


class ArxivAPIClient:
    """Client for querying the arXiv Atom API."""

    BASE_URL = "http://export.arxiv.org/api/query"
    NAMESPACE = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def __init__(self, max_results: int = None, rate_limit_delay: float = None):
        self.max_results = max_results or settings.ARXIV_MAX_RESULTS_PER_QUERY
        self.rate_limit_delay = rate_limit_delay or settings.ARXIV_RATE_LIMIT_SECONDS
        self._last_request_time: float = 0.0

    def _rate_limit(self) -> None:
        """Enforce a minimum delay between consecutive API calls."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.monotonic()

    def fetch_papers_by_category_and_date(
        self,
        category: ArxivCategory,
        target_date: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Fetch *all* papers submitted to *category* on *target_date* (paginated).

        Args:
            category: An ``ArxivCategory`` member.
            target_date: The calendar day to query (UTC).

        Returns:
            A list of paper metadata dicts.
        """
        date_str = target_date.strftime("%Y%m%d")
        # arXiv date-range format: [YYYYMMDD0000 TO YYYYMMDD2359]
        # Use literal spaces; requests will encode them as + in the query string.
        date_range = f"[{date_str}0000 TO {date_str}2359]"
        query = f"cat:{category.value} AND submittedDate:{date_range}"

        all_papers: List[Dict[str, Any]] = []
        start = 0

        while True:
            params = {
                "search_query": query,
                "start": start,
                "max_results": self.max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            self._rate_limit()
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            papers = self._parse_feed(response.text)
            if not papers:
                break

            all_papers.extend(papers)

            if len(papers) < self.max_results:
                break

            start += self.max_results

        return all_papers

    @staticmethod
    def _parse_arxiv_id(id_url: str) -> Tuple[str, str, str]:
        """
        Parse an arXiv ID URL into (full_id, base_id, version).

        Returns:
            (arxiv_id_with_prefix, base_id_without_version, version_str)
            e.g. ("arxiv:2401.12345", "2401.12345", "1")
        """
        raw = id_url.split("/abs/")[-1]  # 2401.12345v2

        match = re.match(r"^(\d{4}\.\d{4,5})(v(\d+))?$", raw)
        if match:
            base_id = match.group(1)
            version = match.group(3) or "1"
        else:
            # Old-style IDs (e.g. hep-th/9901001v2)
            base_match = re.match(r"^(.+?)(v(\d+))?$", raw)
            if base_match:
                base_id = base_match.group(1)
                version = base_match.group(3) or "1"
            else:
                base_id = raw
                version = "1"

        return f"arxiv:{base_id}", base_id, version

    @staticmethod
    def _parse_feed(xml_text: str) -> List[Dict[str, Any]]:
        """Parse arXiv Atom XML into a list of paper dicts."""
        root = ET.fromstring(xml_text)
        papers: List[Dict[str, Any]] = []

        for entry in root.findall("atom:entry", ArxivAPIClient.NAMESPACE):
            id_elem = entry.find("atom:id", ArxivAPIClient.NAMESPACE)
            if id_elem is None:
                continue

            arxiv_id, base_id, version = ArxivAPIClient._parse_arxiv_id(id_elem.text)

            title_elem = entry.find("atom:title", ArxivAPIClient.NAMESPACE)
            title = " ".join(title_elem.text.split()) if title_elem is not None else ""

            summary_elem = entry.find("atom:summary", ArxivAPIClient.NAMESPACE)
            abstract = summary_elem.text.strip() if summary_elem is not None else ""

            published_elem = entry.find("atom:published", ArxivAPIClient.NAMESPACE)
            published = published_elem.text if published_elem is not None else ""

            updated_elem = entry.find("atom:updated", ArxivAPIClient.NAMESPACE)
            updated = updated_elem.text if updated_elem is not None else ""

            authors = []
            for author in entry.findall("atom:author", ArxivAPIClient.NAMESPACE):
                name_elem = author.find("atom:name", ArxivAPIClient.NAMESPACE)
                if name_elem is not None:
                    authors.append(name_elem.text)

            # All categories
            categories = []
            for cat in entry.findall("atom:category", ArxivAPIClient.NAMESPACE):
                term = cat.get("term")
                if term:
                    categories.append(term)

            pdf_url = None
            for link in entry.findall("atom:link", ArxivAPIClient.NAMESPACE):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href")
                    break

            papers.append({
                "id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "categories": categories,
                "published": published,
                "updated": updated,
                "pdf_url": pdf_url,
                "source": "arxiv",
                "version": version,
            })

        return papers
