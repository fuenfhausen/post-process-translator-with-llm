"""Application settings loaded from environment variables.

Uses Managed Identity by default (recommended for Azure-hosted environments).
Falls back to environment-based credentials via DefaultAzureCredential.
Never hardcode secrets — use Azure Key Vault for any secret storage.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for all Azure services and app behavior."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Azure Translator ────────────────────────────────────────────
    azure_translator_endpoint: str
    azure_translator_region: str = "global"

    # ── Azure OpenAI ────────────────────────────────────────────────
    azure_openai_endpoint: str
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-12-01-preview"

    # ── Azure Blob Storage (for document translation) ───────────────
    azure_storage_account_url: str = ""
    azure_storage_container_source: str = "translate-source"
    azure_storage_container_target: str = "translate-target"

    # ── App ─────────────────────────────────────────────────────────
    log_level: str = "INFO"


settings = Settings()  # type: ignore[call-arg]
