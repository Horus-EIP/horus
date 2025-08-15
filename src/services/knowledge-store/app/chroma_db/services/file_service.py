from .. import model, knowledge_collection, DocumentModel
import datetime

async def embedding_func(text):
    return model.encode(text).tolist()

async def store_file(doc: DocumentModel):
    embedding = await embedding_func(doc.content)

    knowledge_collection.add(
        ids=[doc.id],
        documents=[doc.content],
        metadatas=[
            {"title": doc.title,
            "date": str(datetime.datetime.now().ctime()),
            "size": doc.size},
        ],
        embeddings=[embedding]
    )

async def query_knowledge(query: str, n_results: int):
    """
    Query the knowledge store with a query string to retrieve relevant documents.

    Parameters:

            query (str): The query string to search for relevant documents.
            n_results (int): The number of results to return.

    Returns:
    
            results (dict): The results of the query.
    """
    query_embedding = await embedding_func(query)

    results = knowledge_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"]
    )

    return results

async def delete_document(id: str):
    """
    Delete a document from the knowledge store.
    
    Parameters:

            id (str): The id of the document to delete.

    Returns:

            status (str): The status of the operation.
    """
    knowledge_collection.delete(ids=[id])

    return {"status": "document deleted"}
