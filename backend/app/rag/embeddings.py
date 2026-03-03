from sentence_transformers import SentenceTransformer
import logging
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        try:
            logger.info(f"Loading Embedding Model: {settings.EMBEDDING_MODEL_NAME}")
            # Load model on CPU by default, or CUDA if available and efficient for embeddings
            # Embeddings are usually fast enough on CPU, but let's use the configured device strategy generally
            device = settings.DEVICE if settings.DEVICE == "cuda" else "cpu"
            self.model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME, device=device)
            logger.info("Embedding Model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Embedding Model: {e}")
            raise e

    def get_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for a single string.
        """
        try:
            # sentence-transformers returns numpy array, convert to list for ChromaDB
            embedding = self.model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return []

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a list of strings.
        """
        try:
            embeddings = self.model.encode(texts, convert_to_tensor=False)
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Error generating embeddings batch: {e}")
            return []

# Singleton
embedding_service = None

def get_embedding_service():
    global embedding_service
    if embedding_service is None:
        embedding_service = EmbeddingService()
    return embedding_service
