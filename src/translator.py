"""Azure Translator service client.

Translates text using the Azure AI Translator Text API.
Authenticates via Managed Identity (DefaultAzureCredential).
"""

import structlog
from azure.ai.translation.text import TextTranslationClient
from azure.ai.translation.text.models import InputTextItem
from azure.identity import DefaultAzureCredential

from src.config import settings

logger = structlog.get_logger(__name__)


class TranslatorService:
    """Wrapper around Azure AI Translator for text translation."""

    def __init__(self) -> None:
        # Managed Identity / DefaultAzureCredential — no secrets in code
        credential = DefaultAzureCredential()
        self._client = TextTranslationClient(
            credential=credential,
            endpoint=settings.azure_translator_endpoint,
            region=settings.azure_translator_region,
        )

    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        """Translate *text* from *source_language* to *target_language*.

        Returns the translated string. Raises on API errors after logging.
        """
        logger.info(
            "translator.request",
            source=source_language,
            target=target_language,
            text_length=len(text),
        )

        try:
            response = self._client.translate(
                body=[InputTextItem(text=text)],
                from_language=source_language,
                to_language=[target_language],
            )

            translated_text: str = response[0].translations[0].text
            logger.info(
                "translator.success",
                target=target_language,
                result_length=len(translated_text),
            )
            return translated_text

        except Exception:
            logger.exception("translator.error")
            raise
