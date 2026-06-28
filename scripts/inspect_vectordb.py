"""Print a summary table of ChromaDB contents."""

import argparse
import sys

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

sys.path.insert(0, ".")
from src.config import settings

_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_COLLECTION_NAME = "papers"


def main():
    parser = argparse.ArgumentParser(description="Inspect ChromaDB vector store contents")
    parser.add_argument("--host", default=settings.CHROMA_HOST)
    parser.add_argument("--port", type=int, default=settings.CHROMA_PORT)
    parser.add_argument("--limit", type=int, default=200, help="Max chunks to fetch (default 200)")
    parser.add_argument("--paper-id", help="Filter to a specific paper ID")
    args = parser.parse_args()

    client = chromadb.HttpClient(host=args.host, port=args.port)

    try:
        collection = client.get_collection(
            name=_COLLECTION_NAME,
            embedding_function=SentenceTransformerEmbeddingFunction(model_name=_EMBEDDING_MODEL),
        )
    except Exception:
        print(f"Collection '{_COLLECTION_NAME}' not found or server unreachable.")
        sys.exit(1)

    total = collection.count()
    print(f"\nCollection : {_COLLECTION_NAME}")
    print(f"Total chunks: {total}\n")

    if total == 0:
        print("No chunks indexed yet.")
        return

    kwargs = {"limit": args.limit, "include": ["metadatas", "documents"]}
    if args.paper_id:
        kwargs["where"] = {"paper_id": args.paper_id}

    result = collection.get(**kwargs)

    ids = result["ids"]
    metadatas = result["metadatas"]
    documents = result["documents"]

    # Aggregate per-paper stats
    paper_stats: dict = {}
    for meta in metadatas:
        pid = meta.get("paper_id", "unknown")
        if pid not in paper_stats:
            paper_stats[pid] = {
                "title": meta.get("title", "")[:60],
                "categories": meta.get("categories", ""),
                "chunks": 0,
                "sections": set(),
            }
        paper_stats[pid]["chunks"] += 1
        paper_stats[pid]["sections"].add(meta.get("section", ""))

    # Paper-level summary table
    col_widths = [30, 62, 14, 8, 10]
    headers = ["Paper ID", "Title", "Categories", "Chunks", "Sections"]
    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    row_fmt = "| " + " | ".join(f"{{:<{w}}}" for w in col_widths) + " |"

    print(sep)
    print(row_fmt.format(*headers))
    print(sep)
    for pid, info in sorted(paper_stats.items()):
        print(row_fmt.format(
            pid[:col_widths[0]],
            info["title"][:col_widths[1]],
            info["categories"][:col_widths[2]],
            str(info["chunks"]),
            str(len(info["sections"])),
        ))
    print(sep)
    print(f"\nShowing {len(ids)} of {total} chunks across {len(paper_stats)} papers.")

    # If filtering by paper, also show chunk-level detail
    if args.paper_id:
        print(f"\nChunk detail for {args.paper_id}:\n")
        chunk_widths = [8, 30, 55]
        chunk_headers = ["Chunk #", "Section", "Text preview"]
        csep = "+-" + "-+-".join("-" * w for w in chunk_widths) + "-+"
        crow_fmt = "| " + " | ".join(f"{{:<{w}}}" for w in chunk_widths) + " |"

        print(csep)
        print(crow_fmt.format(*chunk_headers))
        print(csep)
        for cid, meta, doc in zip(ids, metadatas, documents):
            preview = doc.replace("\n", " ")[:chunk_widths[2]]
            print(crow_fmt.format(
                str(meta.get("chunk_index", ""))[:chunk_widths[0]],
                meta.get("section", "")[:chunk_widths[1]],
                preview,
            ))
        print(csep)


if __name__ == "__main__":
    main()
