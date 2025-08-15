from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import ROUTERS

description = """
The Knowledge Store is a centralized designed to store, organize and retrieve data for the Horus Agents.

It serves as the backbone for the Horus Agents to access relevant information, enabling them to make informed decisions and generate context-aware responses.

### Documents

You can:

* **Add a document**: Add a document to the knowledge store by providing a _**unique id**_, _**title**_ and _**content**_.
* **Query the knowledge store**: Query the knowledge store with a _**query string**_ to retrieve relevant documents.
* **Delete a document**: Delete a document from the knowledge store by providing the _**id**_ of the document.
"""

app = FastAPI(
    docs_url="/docs",
    root_path="/api/knowledge-store",
    title="Horus Knowledge Store",
    description=description,
    summary="",
    version="1.0.0",
    contact={
        "name": "Horus",
    }
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.exception_handler(HTTPException)
def handle_http_exception(_: Request, exc: HTTPException):
    return (JSONResponse(
	status_code=exc.status_code,
	content={"error": exc.detail}
    ))

for prefix, router in zip(ROUTERS.keys(), ROUTERS.values()):
    app.include_router(router, prefix=prefix)
