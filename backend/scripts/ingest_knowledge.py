"""
RAG Ingestion Runner — Run this script to ingest knowledge base files into ChromaDB.

Usage (from the backend/ directory, with maf_a2a env active):
    python scripts/ingest_knowledge.py

This will:
  1. Read all .txt and .pdf files from the configured knowledge directories
  2. Chunk them into ~500-character segments
  3. Generate embeddings and store them in ChromaDB collections
"""
import sys
import os

# Ensure the backend directory is on the path so app imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag.ingestion import get_ingestion_service

def main():
    print("=" * 60)
    print("  RAG Knowledge Base Ingestion")
    print("=" * 60)

    service = get_ingestion_service()

    print("\n📚 Running full ingestion...")
    service.run_full_ingestion()

    print("\n✅ Ingestion complete!")
    print("=" * 60)

if __name__ == "__main__":
    main()
