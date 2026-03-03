from openai import AzureOpenAI, OpenAI
from app.core.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMFactory:
    @staticmethod
    def get_client(provider: str = None):
        """
        Returns an initialized LLM client based on the provider.
        If provider is None, uses the default from settings.
        """
        provider = provider or settings.LLM_PROVIDER
        provider = provider.upper()

        if provider == "AZURE":
            return LLMFactory._get_azure_client()
        elif provider == "OPENAI":
            return LLMFactory._get_openai_client()
        elif provider == "GEMINI":
            return LLMFactory._get_gemini_client()
        elif provider == "OLLAMA":
            return LLMFactory._get_ollama_client()
        else:
            logger.warning(f"Unknown provider: {provider}. Defaulting to Azure.")
            return LLMFactory._get_azure_client()

    @staticmethod
    def _get_azure_client():
        try:
            client = AzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT
            )
            logger.info("Initialized Azure OpenAI Client")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize Azure Client: {e}")
            raise e

    @staticmethod
    def _get_openai_client():
        try:
            client = OpenAI(
                api_key=settings.OPENAI_API_KEY
            )
            logger.info("Initialized OpenAI Client")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI Client: {e}")
            raise e

    @staticmethod
    def _get_ollama_client():
        try:
            # Ollama is compatible with OpenAI Client
            client = OpenAI(
                base_url=settings.OLLAMA_URL,
                api_key="ollama" # generic key required
            )
            logger.info("Initialized Ollama Client (via OpenAI Protocol)")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize Ollama Client: {e}")
            raise e

    @staticmethod
    def _get_gemini_client():
        try:
             # Using google.generativeai
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            
            # Since Gemini SDK is different from OpenAI, we might need a wrapper or return the model object directly.
            # However, to keep consistency, we should ideally wrap it to look like OpenAI client or handle usage differently.
            # For now, let's return the genai module or model, but the caller will need to know how to use it.
            # *Architecture Decision*: We should eventually make a unified wrapper, but for now we return the raw client/module.
            # The caller (BaseAgent) will need to check the type or we implement a wrapper here.
            
            logger.info("Initialized Gemini Client")
            return genai 
        except ImportError:
            logger.error("google-generativeai package not installed")
            raise ImportError("Please install google-generativeai to use Gemini")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini Client: {e}")
            raise e
