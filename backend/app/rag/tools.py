from agent_framework import AIFunction
from app.rag.engine import get_rag_engine
import logging

logger = logging.getLogger(__name__)

def create_rag_tool(collection_name: str) -> AIFunction:
    """Creates a RAG tool bound to a specific collection."""
    
    def search_knowledge_base(query: str) -> str:
        """Searches the internal knowledge base for relevant information."""
        logger.info(f"Tool 'search_knowledge_base' invoked for collection '{collection_name}' with query: '{query}'")
        try:
            rag_engine = get_rag_engine()
            results = rag_engine.query(collection_name, query, n_results=3)
            
            if not results or not results['documents'] or not results['documents'][0]:
                return "No relevant information found in the knowledge base."
                
            # persistent client query returns list of lists (one per query)
            # We only queried one string, so take the first list
            docs = results['documents'][0]
            
            # Join chunks
            context = "\n\n".join(docs)
            return f"Found the following information:\n{context}"
            
        except Exception as e:
            logger.error(f"Error executing RAG tool: {e}")
            return f"Error searching knowledge base: {str(e)}"

    # Create the tool with a specific name to avoid conflicts if multiple agents share tools (though usually they don't)
    # providing a generic name 'search_knowledge_base' is standard for the LLM to understand.
    return AIFunction(
        name="search_knowledge_base",
        description=f"Searches the {collection_name} knowledge base for relevant documents.",
        func=search_knowledge_base,
        approval_mode="never_require"
    )
