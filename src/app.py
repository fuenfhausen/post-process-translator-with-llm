"""FastAPI application exposing the translation pipeline as a REST API."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException

from src.config import settings
from src.models import TranslationRequest, TranslationResult
from src.pipeline import TranslationPipeline

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_level_from_name(settings.log_level),
    ),
)

logger = structlog.get_logger(__name__)

# Pipeline is created once at startup and reused for all requests.
_pipeline: TranslationPipeline | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared resources on startup."""
    global _pipeline  # noqa: PLW0603
    _pipeline = TranslationPipeline()
    logger.info("app.startup")
    yield
    logger.info("app.shutdown")


app = FastAPI(
    title="Post-Process Translator",
    description=(
        "Translate text with Azure Translator and refine the output "
        "using an LLM for natural-sounding results."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.post("/translate", response_model=TranslationResult)
async def translate(request: TranslationRequest) -> TranslationResult:
    """Translate text and post-process it via LLM for natural phrasing."""
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        return await _pipeline.run(request)
    except Exception:
        logger.exception("translate.error")
        raise HTTPException(
            status_code=502,
            detail="Translation pipeline failed. Check logs for details.",
        ) from None


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
