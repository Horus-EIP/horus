from sentence_transformers import SentenceTransformer
import chromadb

chroma_client = chromadb.PersistentClient(path="chroma_data")

model = SentenceTransformer("paraphrase-MiniLM-L6-v2")

COLLECTION_NAME = "knowledge_collection"

try:
    knowledge_collection = chroma_client.get_collection(name=COLLECTION_NAME)
except Exception:
    knowledge_collection = chroma_client.create_collection(name=COLLECTION_NAME)