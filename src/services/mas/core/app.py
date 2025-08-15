import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import agents.routes
import chat.routes
import conversations.routes
import tasks.routes
from agents.controller import check_agent_heartbeat


def create_app_environment():
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )

    app.include_router(agents.routes.router)
    app.include_router(chat.routes.router)
    app.include_router(conversations.routes.router)
    app.include_router(tasks.routes.router)

    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(check_agent_heartbeat())
    yield
    task.cancel()
