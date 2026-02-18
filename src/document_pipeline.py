"""Document translation pipeline: Document Translation → extract → LLM refine → re-inject.

Orchestrates the full document translation flow:
  1. Azure Document Translation translates the whole file (preserving formatting).
  2. For supported formats (DOCX, PPTX, XLSX), extract text segments from the
     translated document, refine each via LLM, then re-inject back.
  3. For unsupported formats (PDF, etc.), return the translated document as-is.
"""

from __future__ import annotations

import structlog

from src.document_handlers import (
    DocumentFormat,
    TextSegment,
    detect_format,
    get_handler,
)
from src.document_translator import DocumentTranslatorService
from src.llm_postprocessor import LlmPostProcessor

logger = structlog.get_logger(__name__)

# Maximum number of segments to send in a single LLM batch to stay within token limits
_BATCH_SIZE = 20


class DocumentTranslationPipeline:
    """Three-stage document pipeline: Translate → Extract & Refine → Re-inject."""

    def __init__(self) -> None:
        self._doc_translator = DocumentTranslatorService()
        self._postprocessor = LlmPostProcessor()

    async def run(
        self,
        file_data: bytes,
        filename: str,
        source_language: str,
        target_language: str,
        tone: str = "natural",
        domain: str | None = None,
    ) -> tuple[bytes, bool]:
        """Execute the full document translate-then-refine pipeline.

        Parameters
        ----------
        file_data:
            Raw bytes of the uploaded document.
        filename:
            Original filename (used to detect format).
        source_language / target_language:
            BCP-47 language codes.
        tone / domain:
            Passed to the LLM post-processor.

        Returns
        -------
        (document_bytes, was_refined)
            The translated (and possibly LLM-refined) document bytes,
            plus a flag indicating whether LLM post-processing was applied.
        """
        logger.info(
            "doc_pipeline.start",
            filename=filename,
            source_lang=source_language,
            target_lang=target_language,
        )

        # ── Stage 1: Azure Document Translation ────────────────────
        translated_data = await self._doc_translator.translate_document(
            file_data=file_data,
            filename=filename,
            source_language=source_language,
            target_language=target_language,
        )

        # ── Can we post-process this format? ────────────────────────
        doc_format = detect_format(filename)

        if doc_format is None:
            logger.info("doc_pipeline.skip_refinement", reason="unsupported_format", filename=filename)
            return translated_data, False

        # ── Stage 2: Extract → LLM Refine → Re-inject ──────────────
        handler = get_handler(doc_format)
        segments = handler.extract_segments(translated_data)

        if not segments:
            logger.info("doc_pipeline.skip_refinement", reason="no_segments")
            return translated_data, False

        logger.info("doc_pipeline.refining", segment_count=len(segments), format=doc_format.value)

        refined_segments = await self._refine_segments(
            segments=segments,
            source_language=source_language,
            target_language=target_language,
            tone=tone,
            domain=domain,
        )

        # ── Stage 3: Re-inject refined text ─────────────────────────
        refined_data = handler.inject_segments(translated_data, refined_segments)

        logger.info("doc_pipeline.complete", filename=filename, refined=True)
        return refined_data, True

    async def _refine_segments(
        self,
        segments: list[TextSegment],
        source_language: str,
        target_language: str,
        tone: str,
        domain: str | None,
    ) -> list[TextSegment]:
        """Refine each text segment through the LLM post-processor.

        Processes segments in batches to manage token limits.
        Short segments (< 5 chars) are skipped to avoid wasting LLM calls.
        """
        refined: list[TextSegment] = []

        for seg in segments:
            # Skip very short segments (numbers, single words, etc.)
            if len(seg.text.strip()) < 5:
                refined.append(seg)
                continue

            try:
                refined_text, _ = await self._postprocessor.refine(
                    source_text=seg.text,  # We use the translated text as both source & raw
                    source_language=source_language,
                    target_language=target_language,
                    raw_translation=seg.text,
                    tone=tone,
                    domain=domain,
                )
                refined.append(TextSegment(text=refined_text, location=seg.location))
            except Exception:
                logger.warning("doc_pipeline.segment_refine_failed", text_preview=seg.text[:50])
                refined.append(seg)  # Keep original on failure

        return refined
