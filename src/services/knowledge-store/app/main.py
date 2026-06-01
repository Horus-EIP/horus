from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from app.api.routes import ROUTERS
from app.core.logging import get_logger
from app.core.metrics import set_system_info
from app.core.middleware import CorrelationIDMiddleware

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Replace deprecated on_event startup/shutdown."""
    logger.info(
        "Knowledge Store starting up",
        extra={
            "type": "startup",
            "version": "1.0.0",
        },
    )
    yield
    logger.info(
        "Knowledge Store shutting down",
        extra={"type": "shutdown"},
    )


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
    },
    lifespan=lifespan,
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


for prefix, router in zip(ROUTERS.keys(), ROUTERS.values(), strict=False):
    app.include_router(router, prefix=prefix)
    logger.info(f"Router mounted at {prefix}")
