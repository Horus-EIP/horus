"""
Migrate existing embeddings of paraphrase-MiniLM-L6-v2 to BAAI/bge-base-en-v1.5.

Usage:
    python scripts/migrate-embeddings.py [--chroma-path PATH] [--dry-run]
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src/services/knowledge-store/app"))

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

OLD_MODEL_NAME = "paraphrase-MiniLM-L6-v2"
NEW_MODEL_NAME = "BAAI/bge-base-en-v1.5"
COLLECTION_NAME = "knowledge_collection"
BATCH_SIZE = 50

def migrate(chroma_path: str, dry_run: bool = False):
    print(f"Connecting to ChromaDB at: {chroma_path}")
    client = chromadb.PersistentClient(
        path=chroma_path,
        settings=Settings(anonymized_telemetry=False)
    )

    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found.")
        sys.exit(1)

    total = collection.count()
    print(f"Total documents to migrate: {total}")

    if total == 0:
        print("Nothing to migrate.")
        return

    if dry_run:
        print("Running in dry-run mode. No changes will be made to the database.")

    print(f"Loading new model '{NEW_MODEL_NAME}'...")
    new_model = SentenceTransformer(NEW_MODEL_NAME)

    all_ids, all_documents, all_metadatas = [], [], []
    offset = 0

    while offset < total:
        results = collection.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["documents", "metadatas"]
        )
        if not results["ids"]:
            break
        all_ids.extend(results["ids"])
        all_documents.extend(results["documents"])
        all_metadatas.extend(results["metadatas"])
        offset += BATCH_SIZE

    print(f"Processing batch 1 / {(total // BATCH_SIZE) + 1}...")

    new_embeddings = new_model.encode(
        all_documents,
        normalize_embeddings=True,
        show_progress_bar=False
    ).tolist()

    updated_metadatas = []
    for meta in all_metadatas:
        m = dict(meta) if meta else {}
        m["embedding_model"] = NEW_MODEL_NAME
        updated_metadatas.append(m)

    if not dry_run:
        print("Recreating collection with new embedding dimensions (from 384 to 768)...")
        client.delete_collection(name=COLLECTION_NAME)
        new_collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"embedding_model": NEW_MODEL_NAME, "dimensions": 768}
        )
        new_collection.add(
            ids=all_ids,
            embeddings=new_embeddings,
            documents=all_documents,
            metadatas=updated_metadatas
        )

    print(f"\nMigration {'dry-run' if dry_run else 'complete'}: {len(all_ids)}/{total} documents.")
    if not dry_run:
        print(f"\tActive model: {NEW_MODEL_NAME} (768 dims)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate existing embeddings to a new model.")
    parser.add_argument("--chroma-path", default="src/services/knowledge-store/chroma_data", help="Path to the ChromaDB data directory.")
    parser.add_argument("--dry-run", action="store_true", help="Run the migration without making any changes to the database.")
    args = parser.parse_args()

    migrate(args.chroma_path, args.dry_run)