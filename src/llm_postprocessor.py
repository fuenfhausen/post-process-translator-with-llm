"""LLM post-processor that refines machine-translated text.

Uses Azure OpenAI (via the openai SDK with azure_endpoint) to make
translations sound more natural, idiomatic, and contextually appropriate.
Authenticates via Managed Identity (DefaultAzureCredential).
"""

import json

import structlog
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from src.config import settings

logger = structlog.get_logger(__name__)

# System prompt that instructs the LLM on its role
_SYSTEM_PROMPT = """\
You are an expert linguist and translation post-editor.

Your task is to refine a machine-translated text so it reads as if originally
written by a native speaker. You will receive:
- The original source text
- The source language
- The target language
- The raw machine translation
- A desired tone (e.g. formal, casual, natural)
- An optional domain context (e.g. medical, legal, marketing)

Rules:
1. Preserve the original meaning exactly — do NOT add or omit information.
2. Fix grammar, word choice, phrasing, and register to match the target tone.
3. Adapt idioms and cultural references appropriately.
4. Keep technical terms accurate when a domain is provided.
5. Return your response as JSON with exactly two keys:
   - "refined_translation": the improved text
   - "refinement_notes": a brief summary of what you changed and why
"""


class LlmPostProcessor:
    """Refines machine-translated text via Azure OpenAI."""

    def __init__(self) -> None:
        # Managed Identity token provider for Azure OpenAI
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default",
        )

        self._client = AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=settings.azure_openai_api_version,
        )
        self._deployment = settings.azure_openai_deployment

    async def refine(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        raw_translation: str,
        tone: str = "natural",
        domain: str | None = None,
    ) -> tuple[str, str | None]:
        """Refine *raw_translation* to sound natural in *target_language*.

        Returns ``(refined_text, refinement_notes)``.
        """
        user_message = (
            f"Source language: {source_language}\n"
            f"Target language: {target_language}\n"
            f"Tone: {tone}\n"
            f"Domain: {domain or 'general'}\n\n"
            f"--- Original text ---\n{source_text}\n\n"
            f"--- Machine translation ---\n{raw_translation}"
        )

        logger.info(
            "llm.request",
            deployment=self._deployment,
            source_lang=source_language,
            target_lang=target_language,
            tone=tone,
            domain=domain,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            result = json.loads(content)

            refined: str = result.get("refined_translation", raw_translation)
            notes: str | None = result.get("refinement_notes")

            logger.info(
                "llm.success",
                refined_length=len(refined),
                has_notes=notes is not None,
            )
            return refined, notes

        except Exception:
            logger.exception("llm.error")
            raise
