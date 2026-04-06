from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.routes import ROUTERS
from app.core.logging import get_logger
from app.core.middleware import CorrelationIDMiddleware
from app.core.metrics import set_system_info
from app.services.content_analyzer import ContentAnalyzer

logger = get_logger("main")

# OpenTelemetry auto-instrumentation is handled by opentelemetry-instrument wrapper
# See Dockerfile CMD for details

description = """
The Knowledge Store is a centralized designed to store, organize and retrieve data for the Horus Agents.

It serves as the backbone for the Horus Agents to access relevant information, enabling them to make informed decisions and generate context-aware responses.

### Documents

You can:

* **Add a document**: Add a document to the knowledge store by providing a _**unique id**_, _**title**_ and _**content**_.
* **Query the knowledge store**: Query the knowledge store with a _**query string**_ to retrieve relevant documents.
* **Delete a document**: Delete a document from the knowledge store by providing the _**id**_ of the document.

### Observability

* **Metrics**: `/metrics` - Prometheus metrics endpoint
* **Health**: Health checks via standard HTTP status codes
* **Logging**: Structured JSON logging with correlation IDs
"""

app = FastAPI(
    docs_url="/docs",
    root_path="/api/knowledge-store",
    title="Horus Knowledge Store",
    description=description,
    summary="Vector database and document retrieval service",
    version="1.0.0",
    contact={
        "name": "Horus",
    }
)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
logger.info("Prometheus metrics endpoint mounted at /metrics")

# Add correlation ID middleware for request tracing
app.add_middleware(CorrelationIDMiddleware)
logger.info("Correlation ID middleware added")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Correlation-ID"]
)

# Set system info for metrics
set_system_info(version="1.0.0", embedding_model="BAAI/bge-base-en-v1.5")


@app.on_event("startup")
async def startup_event():
    """Log startup event."""
    logger.info(
        "Knowledge Store starting up",
        extra={
            "type": "startup",
            "version": "1.0.0",
        }
    )
    #start = ContentAnalyzer()
    #start.analyze("Here is an invoice for the server purchase.")
    #start.analyze("This is a technical document about software development.")
    #start.analyze("Meeting notes from the sales team.")
    #start.analyze("Employee benefits and HR policies.")
    #start.analyze("Legal contract for service agreement.")
    #start.analyze("Marketing strategies for product launch.")
    #start.analyze("General company updates and announcements.")
    #start.analyze("Invoice #123 dated 2026-01-27 for 25/02/2025 is due.")
    #start.analyze("The total amount is $1,250.50 as per the contract signed on 15-03-2024.")
    #start.analyze("Our meeting is scheduled for January, 2th 2023 to discuss the budget of EUR 3000, there will be 4000 persons.")
    #start.analyze("No relevant keywords here.")
    #start.analyze("dates: 2023-12-31, 31/12/2023, December 5th, 2023, Dec 2023, 2024. amounts: $100, 200 USD, EUR 300. dates: 01-01-2024, 1st January 2024. dates: 1999, 2020. dates: 5th Feb, Feb 5th, 5 Feb 2022.")
    #start.analyze("amounts: $100, 200 USD, EUR 300. amounts: $1,250.50, 3000 EUR, USD 4500. amounts: 7500$.")
    #start.analyze("spacy test document for entity recognition: John Doe from Acme Corp met with Jane Smith of Globex Corporation on 5th May 2023 to discuss a contract worth $5000.")
    #start.analyze("spacy test document for entity recognition: Alice Johnson of OpenAI met with Bob Brown from Tech Solutions on March 10, 2024 to finalize a deal worth €7500.")
    #start.analyze("topic testing document about machine learning and artificial intelligence in the field of data science and neural networks.")
    #start.analyze("summary test document: The quick brown fox jumps over the lazy dog. This sentence is commonly used to test typing skills and font rendering. It contains every letter of the English alphabet at least once. The fox is known for its agility and cleverness, while the dog represents loyalty and companionship.")



@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown event."""
    logger.info(
        "Knowledge Store shutting down",
        extra={"type": "shutdown"}
    )


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "knowledge-store"}


@app.exception_handler(HTTPException)
def handle_http_exception(_: Request, exc: HTTPException):
    logger.warning(
        f"HTTP exception: {exc.status_code} - {exc.detail}",
        extra={
            "type": "http_exception",
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


for prefix, router in zip(ROUTERS.keys(), ROUTERS.values()):
    app.include_router(router, prefix=prefix)
    logger.info(f"Router mounted at {prefix}")