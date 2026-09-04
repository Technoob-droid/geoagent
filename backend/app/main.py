import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.api.routes_layers import router as layers_router
from backend.app.api.routes_chat import router as chat_router

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("geoagent.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing GeoAgent backend and loading extensions...")
    yield
    logger.info("Shutting down GeoAgent backend...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware for local frontend dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount endpoints
app.include_router(layers_router)
app.include_router(chat_router)

@app.get("/health")
async def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}