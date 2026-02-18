"""Azure Document Translation service client.

Submits documents stored in Azure Blob Storage for batch translation,
polls for completion, and downloads the translated result.
Authenticates via Managed Identity (DefaultAzureCredential).
"""

from __future__ import annotations

import io
import time
import uuid

import structlog
from azure.ai.translation.document import DocumentTranslationClient
from azure.ai.translation.document.models import (
    DocumentTranslationInput,
    StorageInputType,
    TranslationGlossary,
    TranslationSource,
    TranslationTarget,
)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from src.config import settings

logger = structlog.get_logger(__name__)

# Maximum time to wait for a document translation job (seconds)
_MAX_POLL_SECONDS = 600
_POLL_INTERVAL_SECONDS = 5


class DocumentTranslatorService:
    """Manages the upload → translate → download flow for document translation."""

    def __init__(self) -> None:
        credential = DefaultAzureCredential()

        self._doc_client = DocumentTranslationClient(
            endpoint=settings.azure_translator_endpoint,
            credential=credential,
        )

        self._blob_service = BlobServiceClient(
            account_url=settings.azure_storage_account_url,
            credential=credential,
        )

        self._source_container = settings.azure_storage_container_source
        self._target_container = settings.azure_storage_container_target

    async def translate_document(
        self,
        file_data: bytes,
        filename: str,
        source_language: str,
        target_language: str,
    ) -> bytes:
        """Translate a document via Azure Document Translation.

        1. Upload the source file to Blob Storage.
        2. Submit a translation job.
        3. Poll until the job completes.
        4. Download the translated file from Blob Storage.
        5. Clean up temporary blobs.

        Returns the translated document bytes.
        """
        job_id = uuid.uuid4().hex[:12]
        source_blob_name = f"{job_id}/{filename}"
        target_blob_name = f"{job_id}/{filename}"

        logger.info(
            "doc_translator.upload",
            job_id=job_id,
            filename=filename,
            size=len(file_data),
        )

        # ── 1. Upload source document ──────────────────────────────
        source_container_client = self._blob_service.get_container_client(self._source_container)
        source_container_client.upload_blob(name=source_blob_name, data=file_data, overwrite=True)

        source_url = f"{settings.azure_storage_account_url}/{self._source_container}"
        target_url = f"{settings.azure_storage_account_url}/{self._target_container}"

        # ── 2. Submit translation job ──────────────────────────────
        try:
            poller = self._doc_client.begin_translation(
                inputs=[
                    DocumentTranslationInput(
                        source=TranslationSource(
                            source_url=source_url,
                            storage_type=StorageInputType.FOLDER,
                            filter_prefix=f"{job_id}/",
                            language=source_language,
                        ),
                        targets=[
                            TranslationTarget(
                                target_url=target_url,
                                language=target_language,
                            ),
                        ],
                    )
                ],
            )

            logger.info("doc_translator.job_submitted", job_id=job_id)

            # ── 3. Poll for completion ─────────────────────────────
            elapsed = 0
            while not poller.done():
                if elapsed >= _MAX_POLL_SECONDS:
                    raise TimeoutError(f"Document translation job {job_id} timed out after {_MAX_POLL_SECONDS}s")
                time.sleep(_POLL_INTERVAL_SECONDS)
                elapsed += _POLL_INTERVAL_SECONDS
                poller.status()

            result = poller.result()
            # Check for per-document errors
            for doc_result in result:
                if doc_result.status.value == "Failed":
                    raise RuntimeError(
                        f"Document translation failed: {doc_result.error.code} - {doc_result.error.message}"
                    )

            logger.info("doc_translator.job_complete", job_id=job_id, elapsed_s=elapsed)

            # ── 4. Download translated document ────────────────────
            target_container_client = self._blob_service.get_container_client(self._target_container)
            blob_client = target_container_client.get_blob_client(target_blob_name)
            translated_data = blob_client.download_blob().readall()

            logger.info("doc_translator.downloaded", job_id=job_id, size=len(translated_data))
            return translated_data

        finally:
            # ── 5. Clean up temporary blobs ────────────────────────
            self._cleanup_blob(self._source_container, source_blob_name)
            self._cleanup_blob(self._target_container, target_blob_name)

    def _cleanup_blob(self, container: str, blob_name: str) -> None:
        """Delete a blob, logging but not raising on failure."""
        try:
            client = self._blob_service.get_container_client(container)
            client.delete_blob(blob_name)
            logger.debug("doc_translator.blob_deleted", container=container, blob=blob_name)
        except Exception:
            logger.warning("doc_translator.cleanup_failed", container=container, blob=blob_name)
