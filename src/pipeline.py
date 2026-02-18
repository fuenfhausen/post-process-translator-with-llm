"""Orchestration pipeline that chains Azure Translator → LLM post-processing.

This is the core workflow:
  1. Azure Translator produces a raw machine translation.
  2. Azure OpenAI (LLM) refines the translation to sound natural.
  3. The combined result is returned as a ``TranslationResult``.
"""

import structlog

from src.llm_postprocessor import LlmPostProcessor
from src.models import TranslationRequest, TranslationResult
from src.translator import TranslatorService

logger = structlog.get_logger(__name__)


class TranslationPipeline:
    """Two-stage translation pipeline: Translate → Refine."""

    def __init__(self) -> None:
        self._translator = TranslatorService()
        self._postprocessor = LlmPostProcessor()

    async def run(self, request: TranslationRequest) -> TranslationResult:
        """Execute the full translate-then-refine pipeline.

        Parameters
        ----------
        request:
            The incoming translation request with source text, languages,
            tone, and optional domain.

        Returns
        -------
        TranslationResult
            Contains both the raw Azure Translator output and the
            LLM-refined version.
        """
        logger.info(
            "pipeline.start",
            source_lang=request.source_language,
            target_lang=request.target_language,
            text_length=len(request.text),
        )

        # ── Stage 1: Azure Translator ───────────────────────────────
        raw_translation = await self._translator.translate(
            text=request.text,
            source_language=request.source_language,
            target_language=request.target_language,
        )

        # ── Stage 2: LLM Post-Processing ───────────────────────────
        refined_translation, refinement_notes = await self._postprocessor.refine(
            source_text=request.text,
            source_language=request.source_language,
            target_language=request.target_language,
            raw_translation=raw_translation,
            tone=request.tone,
            domain=request.domain,
        )

        result = TranslationResult(
            source_text=request.text,
            source_language=request.source_language,
            target_language=request.target_language,
            raw_translation=raw_translation,
            refined_translation=refined_translation,
            refinement_notes=refinement_notes,
        )

        logger.info("pipeline.complete")
        return result
