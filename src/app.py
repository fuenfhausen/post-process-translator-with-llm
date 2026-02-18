"""FastAPI application exposing text and document translation pipelines as a REST API."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from src.config import settings
from src.document_pipeline import DocumentTranslationPipeline
from src.models import DocumentTranslationResult, TranslationRequest, TranslationResult
from src.pipeline import TranslationPipeline

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_level_from_name(settings.log_level),
    ),
)

logger = structlog.get_logger(__name__)

# Pipelines are created once at startup and reused for all requests.
_pipeline: TranslationPipeline | None = None
_doc_pipeline: DocumentTranslationPipeline | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared resources on startup."""
    global _pipeline, _doc_pipeline  # noqa: PLW0603
    _pipeline = TranslationPipeline()
    _doc_pipeline = DocumentTranslationPipeline()
    logger.info("app.startup")
    yield
    logger.info("app.shutdown")


app = FastAPI(
    title="Post-Process Translator",
    description=(
        "Translate text and documents with Azure Translator and refine the output "
        "using an LLM for natural-sounding results."
    ),
    version="0.2.0",
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


# ── Document Translation ───────────────────────────────────────────


_CONTENT_TYPE_MAP = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@app.post("/translate/document")
async def translate_document(
    file: UploadFile = File(..., description="Document to translate (DOCX, PPTX, XLSX, PDF, etc.)"),
    source_language: str = Form(..., description="BCP-47 source language code"),
    target_language: str = Form(..., description="BCP-47 target language code"),
    tone: str = Form(default="natural", description="Desired tone for LLM refinement"),
    domain: str | None = Form(default=None, description="Optional domain hint"),
) -> Response:
    """Translate a document and optionally refine with LLM post-processing.

    - **Tier 1** (DOCX, PPTX, XLSX): Full pipeline with LLM refinement.
    - **Tier 2** (PDF, etc.): Azure Document Translation only (no LLM refinement).

    Returns the translated document as a file download.
    """
    if _doc_pipeline is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        translated_data, was_refined = await _doc_pipeline.run(
            file_data=file_data,
            filename=file.filename,
            source_language=source_language,
            target_language=target_language,
            tone=tone,
            domain=domain,
        )
    except Exception:
        logger.exception("translate_document.error")
        raise HTTPException(
            status_code=502,
            detail="Document translation pipeline failed. Check logs for details.",
        ) from None

    ext = file.filename.rsplit(".", maxsplit=1)[-1].lower() if "." in file.filename else "bin"
    content_type = _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
    output_filename = f"translated_{file.filename}"

    return Response(
        content=translated_data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "X-Was-Refined": str(was_refined).lower(),
        },
    )


@app.post("/translate/document/metadata", response_model=DocumentTranslationResult)
async def translate_document_metadata(
    file: UploadFile = File(...),
    source_language: str = Form(...),
    target_language: str = Form(...),
    tone: str = Form(default="natural"),
    domain: str | None = Form(default=None),
) -> DocumentTranslationResult:
    """Same as /translate/document but returns only metadata (no file download).

    Useful for checking whether a file format supports LLM refinement.
    """
    if _doc_pipeline is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        _, was_refined = await _doc_pipeline.run(
            file_data=file_data,
            filename=file.filename,
            source_language=source_language,
            target_language=target_language,
            tone=tone,
            domain=domain,
        )
    except Exception:
        logger.exception("translate_document_metadata.error")
        raise HTTPException(
            status_code=502,
            detail="Document translation pipeline failed. Check logs for details.",
        ) from None

    return DocumentTranslationResult(
        filename=file.filename,
        source_language=source_language,
        target_language=target_language,
        was_refined=was_refined,
        output_filename=f"translated_{file.filename}",
        message="LLM refinement applied" if was_refined else "Translated without LLM refinement (unsupported format)",
    )
