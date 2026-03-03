import os
import logging
from typing import List, Dict
import PyPDF2
from app.rag.engine import get_rag_engine
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IngestionService:
    def __init__(self):
        self.rag_engine = get_rag_engine()

    def load_documents_from_directory(self, directory_path: str) -> List[Dict]:
        """
        Reads all PDF and TXT files from a directory.
        Returns a list of dicts: {'content': str, 'metadata': dict}
        """
        documents = []
        if not os.path.exists(directory_path):
            logger.warning(f"Directory not found: {directory_path}")
            return documents

        for filename in os.listdir(directory_path):
            file_path = os.path.join(directory_path, filename)
            if filename.endswith(".pdf"):
                content = self._read_pdf(file_path)
                if content:
                    documents.append({"content": content, "metadata": {"source": filename, "type": "pdf"}})
            elif filename.endswith(".txt"):
                content = self._read_txt(file_path)
                if content:
                    documents.append({"content": content, "metadata": {"source": filename, "type": "txt"}})
        
        return documents

    def _read_pdf(self, file_path: str) -> str:
        try:
            text = ""
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.error(f"Error reading PDF {file_path}: {e}")
            return ""

    def _read_txt(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading TXT {file_path}: {e}")
            return ""

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """
        Splits text into chunks of roughly `chunk_size` characters with `overlap`.
        """
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += chunk_size - overlap
        return chunks

    def ingest_directory(self, directory_path: str, collection_name: str):
        """
        1. Load documents from directory
        2. Chunk them
        3. Add to ChromaDB collection
        """
        logger.info(f"Starting ingestion for {collection_name} from {directory_path}")
        
        raw_docs = self.load_documents_from_directory(directory_path)
        if not raw_docs:
            logger.warning(f"No documents found in {directory_path}")
            return

        final_chunks = []
        final_metadatas = []
        final_ids = []

        for doc in raw_docs:
            chunks = self.chunk_text(doc['content'])
            for i, chunk in enumerate(chunks):
                final_chunks.append(chunk)
                # Clone metadata and add chunk index
                meta = doc['metadata'].copy()
                meta['chunk_index'] = i
                final_metadatas.append(meta)
                final_ids.append(f"{doc['metadata']['source']}_chunk_{i}")

        if final_chunks:
            self.rag_engine.add_documents(
                collection_name=collection_name,
                documents=final_chunks,
                metadatas=final_metadatas,
                ids=final_ids
            )
            logger.info(f"Ingested {len(final_chunks)} chunks into {collection_name} from {len(raw_docs)} files.")
        else:
            logger.warning("No content to ingest after processing.")

    def run_full_ingestion(self):
        """
        Ingests all configured agent storage paths.
        Scalable: Add more agents here as needed.
        """
        # 1. Technical Agent
        self.ingest_directory(
            settings.KNOWLEDGE_BASE_TECHNICAL, 
            settings.RAG_COLLECTION_TECHNICAL
        )

        # 2. Agriculture Agent
        self.ingest_directory(
            settings.KNOWLEDGE_BASE_AGRICULTURE, 
            settings.RAG_COLLECTION_AGRICULTURE
        )
        
        # ... Add future agents here ...

# Singleton
ingestion_service = None

def get_ingestion_service():
    global ingestion_service
    if ingestion_service is None:
        ingestion_service = IngestionService()
    return ingestion_service
