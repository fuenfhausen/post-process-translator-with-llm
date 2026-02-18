"""Shared data models used across the translation pipeline."""

from pydantic import BaseModel, Field


class TranslationRequest(BaseModel):
    """Input payload for the text translation pipeline."""

    text: str = Field(..., min_length=1, max_length=50_000, description="Source text to translate")
    source_language: str = Field(..., min_length=2, max_length=10, description="BCP-47 source language code (e.g. 'en')")
    target_language: str = Field(..., min_length=2, max_length=10, description="BCP-47 target language code (e.g. 'de')")
    tone: str = Field(
        default="natural",
        description="Desired tone for LLM post-processing (e.g. 'formal', 'casual', 'natural')",
    )
    domain: str | None = Field(
        default=None,
        description="Optional domain hint for LLM (e.g. 'medical', 'legal', 'marketing')",
    )


class TranslationResult(BaseModel):
    """Output payload from the text translation pipeline."""

    source_text: str
    source_language: str
    target_language: str
    raw_translation: str = Field(description="Direct output from Azure Translator")
    refined_translation: str = Field(description="LLM-refined, natural-sounding translation")
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    refinement_notes: str | None = Field(
        default=None,
        description="Brief LLM explanation of changes made during refinement",
    )


class DocumentTranslationResult(BaseModel):
    """Output metadata from the document translation pipeline."""

    filename: str
    source_language: str
    target_language: str
    was_refined: bool = Field(description="Whether LLM post-processing was applied")
    output_filename: str = Field(description="Name of the translated output file")
    message: str
