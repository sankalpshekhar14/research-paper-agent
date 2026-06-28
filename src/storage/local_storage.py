"""Local filesystem storage for downloaded arXiv PDFs."""

from pathlib import Path

import requests


class LocalStorage:
    """Store and retrieve paper PDFs on local disk."""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save_paper(self, paper_id: str, pdf_url: str, category: str) -> str:
        """
        Download *pdf_url* and persist it under ``base_path/category/paper_id.pdf``.

        Returns:
            The absolute filesystem path of the saved PDF.
        """
        safe_category = category.replace(".", "_")
        category_dir = self.base_path / safe_category
        category_dir.mkdir(exist_ok=True)

        # paper_id comes in as "arxiv:2401.12345"; strip prefix for filename
        safe_paper_id = paper_id.replace(":", "_").replace("/", "_")
        filepath = category_dir / f"{safe_paper_id}.pdf"

        if filepath.exists():
            return str(filepath)

        # Ensure we hit the direct PDF URL
        if not pdf_url.endswith(".pdf"):
            pdf_url = pdf_url.replace("/abs/", "/pdf/") + ".pdf"

        response = requests.get(pdf_url, timeout=60)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(response.content)

        return str(filepath)

    def get_paper_path(self, paper_id: str, category: str) -> Path | None:
        """Return the path for a paper if it already exists, else None."""
        safe_category = category.replace(".", "_")
        safe_paper_id = paper_id.replace(":", "_").replace("/", "_")
        filepath = self.base_path / safe_category / f"{safe_paper_id}.pdf"
        return filepath if filepath.exists() else None
