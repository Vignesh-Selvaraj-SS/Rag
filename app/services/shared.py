from app.services.rag_service import RAGService

# One shared instance. Qdrant's embedded mode locks its data folder to a
# single client - unlike Chroma, it cannot be opened twice in one process,
# so each router creating its own RAGService() would crash on startup.
rag_service = RAGService()
