"""ChromaDB HTTP client wrapper for indexing and querying paper chunks."""

import logging
from typing import Any, Dict, List, Optional

import chromadb
import torch
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from src.config import settings
from src.indexing.pdf_parser import PaperChunk

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "papers"
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Reciprocal Rank Fusion constant (higher → smooths rank differences)
_RRF_K = 60


def _matches_where(metadata: Dict[str, Any], where: Dict[str, Any]) -> bool:
    """Minimal ChromaDB-style where-filter evaluation for BM25 post-filtering.

    Supports: exact match and {"$contains": value} for string fields.
    """
    for key, condition in where.items():
        val = metadata.get(key)
        if isinstance(condition, dict):
            if "$contains" in condition and condition["$contains"] not in str(val or ""):
                return False
        else:
            if val != condition:
                return False
    return True


def _embedding_device() -> str:
    """Pick the best available device for sentence-transformer embeddings."""
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class VectorStore:
    def __init__(self):
        device = _embedding_device()
        logger.info("VectorStore: using embedding device=%s model=%s", device, _EMBEDDING_MODEL)

        self._client = chromadb.HttpClient(
            host=settings.CHROMA_HOST,
            port=settings.CHROMA_PORT,
        )
        self._ef = SentenceTransformerEmbeddingFunction(
            model_name=_EMBEDDING_MODEL,
            device=device,
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        self._reranker = CrossEncoder(_RERANKER_MODEL)

        # BM25 index — built lazily, invalidated on index_chunks()
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_ids: List[str] = []
        self._bm25_docs: List[str] = []
        self._bm25_metadatas: List[Dict[str, Any]] = []

    def index_chunks(self, chunks: List[PaperChunk]) -> None:
        """Upsert a list of chunks into the ChromaDB collection."""
        if not chunks:
            return

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for chunk in chunks:
            chunk_id = f"{chunk.paper_id}::chunk::{chunk.chunk_index}"
            ids.append(chunk_id)
            documents.append(chunk.text)
            metadatas.append(
                {
                    "paper_id": chunk.paper_id,
                    "section": chunk.section_title,
                    "chunk_index": chunk.chunk_index,
                    **{k: v for k, v in chunk.metadata.items() if k not in ("section",)},
                }
            )

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        self._bm25 = None  # invalidate BM25 cache

    # ------------------------------------------------------------------
    # BM25 helpers
    # ------------------------------------------------------------------

    def _ensure_bm25(self) -> None:
        """Build (or rebuild) the in-memory BM25 index from ChromaDB."""
        if self._bm25 is not None:
            return

        logger.info("VectorStore: building BM25 index from ChromaDB ...")
        result = self._collection.get(include=["documents", "metadatas"])
        self._bm25_ids = result["ids"]
        self._bm25_docs = result["documents"]
        self._bm25_metadatas = result["metadatas"]

        tokenized = [doc.lower().split() for doc in self._bm25_docs]
        self._bm25 = BM25Okapi(tokenized)
        logger.info("VectorStore: BM25 index ready (%d docs)", len(self._bm25_ids))

    def _bm25_search(
        self,
        query_text: str,
        n: int,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return top-n BM25 hits as dicts with text/metadata/score keys."""
        self._ensure_bm25()
        scores = self._bm25.get_scores(query_text.lower().split())

        # pair (score, idx), filter by where clause, pick top-n
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        hits = []
        for idx, score in ranked:
            meta = self._bm25_metadatas[idx]
            if where and not _matches_where(meta, where):
                continue
            hits.append(
                {
                    "id": self._bm25_ids[idx],
                    "text": self._bm25_docs[idx],
                    "metadata": meta,
                    "score": float(score),
                }
            )
            if len(hits) >= n:
                break
        return hits

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the top-n most relevant chunks (pure vector search)."""
        kwargs: Dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        result = self._collection.query(**kwargs)

        hits = []
        for i, doc in enumerate(result["documents"][0]):
            hits.append(
                {
                    "text": doc,
                    "metadata": result["metadatas"][0][i],
                    "distance": result["distances"][0][i],
                }
            )
        return hits

    def hybrid_query(
        self,
        query_text: str,
        n_results: int = 5,
        candidate_multiplier: int = 5,
        where: Optional[Dict[str, Any]] = None,
        rerank: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search: BM25 + vector search fused via Reciprocal Rank Fusion,
        then optionally reranked with a cross-encoder.

        candidate_multiplier: fetch n*k candidates from each retriever before fusion.
        """
        n_candidates = n_results * candidate_multiplier

        # --- vector retrieval ---
        vec_kwargs: Dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": min(n_candidates, self._collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            vec_kwargs["where"] = where
        vec_result = self._collection.query(**vec_kwargs)

        vec_hits: List[Dict[str, Any]] = []
        for i, doc in enumerate(vec_result["documents"][0]):
            chunk_id = vec_result["ids"][0][i]
            vec_hits.append(
                {
                    "id": chunk_id,
                    "text": doc,
                    "metadata": vec_result["metadatas"][0][i],
                    "distance": vec_result["distances"][0][i],
                }
            )

        # --- BM25 retrieval ---
        bm25_hits = self._bm25_search(query_text, n=n_candidates, where=where)

        # --- Reciprocal Rank Fusion ---
        rrf_scores: Dict[str, float] = {}
        id_to_hit: Dict[str, Dict[str, Any]] = {}

        for rank, hit in enumerate(vec_hits):
            cid = hit["id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            id_to_hit[cid] = hit

        for rank, hit in enumerate(bm25_hits):
            cid = hit["id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            if cid not in id_to_hit:
                id_to_hit[cid] = hit

        fused = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        candidates = [id_to_hit[cid] for cid, _ in fused[:n_candidates]]

        # --- Cross-encoder reranking ---
        if rerank and candidates:
            pairs = [(query_text, c["text"]) for c in candidates]
            ce_scores = self._reranker.predict(pairs)
            for i, c in enumerate(candidates):
                c["rerank_score"] = float(ce_scores[i])
            candidates.sort(key=lambda c: c["rerank_score"], reverse=True)

        # Trim to requested n and normalise output shape
        results = []
        for c in candidates[:n_results]:
            results.append(
                {
                    "text": c["text"],
                    "metadata": c["metadata"],
                    "distance": c.get("distance", 0.0),
                    "rerank_score": c.get("rerank_score"),
                }
            )
        return results

    def paper_is_indexed(self, paper_id: str) -> bool:
        """Return True if any chunk for this paper_id already exists."""
        result = self._collection.get(
            where={"paper_id": paper_id}, limit=1, include=[]
        )
        return len(result["ids"]) > 0

    def delete_paper(self, paper_id: str) -> None:
        """Remove all chunks belonging to a paper."""
        self._collection.delete(where={"paper_id": paper_id})


_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
