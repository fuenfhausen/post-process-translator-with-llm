# Post-Process Translator with LLM

Translate **text and documents** with **Azure Translator** and automatically refine the output using an **Azure OpenAI LLM** so it reads naturally — as if written by a native speaker.

Supports two translation modes:
- **Text translation** — inline string translation with LLM refinement
- **Document translation** — whole-file translation (DOCX, PPTX, XLSX, PDF, …) with format-aware LLM refinement for supported formats

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client / Caller                         │
│               (any HTTP client, web app, CLI)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │  POST /translate
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI REST API                            │
│                       (src/app.py)                              │
│  • Input validation (Pydantic models)                          │
│  • Health-check endpoint                                       │
│  • Structured logging (structlog)                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Translation Pipeline                           │
│                    (src/pipeline.py)                             │
│                                                                 │
│   Orchestrates the two-stage flow:                              │
│                                                                 │
│   ┌───────────────────┐        ┌──────────────────────────┐     │
│   │  Stage 1:         │        │  Stage 2:                │     │
│   │  Azure Translator │──raw──▶│  LLM Post-Processor      │     │
│   │  (src/translator) │  text  │  (src/llm_postprocessor)  │     │
│   └────────┬──────────┘        └────────────┬─────────────┘     │
│            │                                │                   │
│            ▼                                ▼                   │
│   Azure AI Translator          Azure OpenAI (GPT-4o)            │
│   Text API                     Chat Completions API             │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
              TranslationResult (JSON)
              ├─ raw_translation     ← from Azure Translator
              ├─ refined_translation ← from LLM
              └─ refinement_notes    ← what the LLM changed
```

### Text Translation Data Flow

1. **Client** sends a `POST /translate` request with source text, source/target languages, desired tone, and optional domain.
2. **FastAPI** validates the request via Pydantic models.
3. **Pipeline** calls **Azure Translator** (Stage 1) to produce a raw machine translation.
4. **Pipeline** sends the original text + raw translation to **Azure OpenAI** (Stage 2) with a carefully crafted system prompt instructing the LLM to refine the translation for naturalness, idiom usage, and tone.
5. The **combined result** — raw translation, refined translation, and change notes — is returned to the client.

### Document Translation Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       Client / Caller                           │
│         POST /translate/document  (multipart file upload)       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI REST API                              │
│                      (src/app.py)                                │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              Document Translation Pipeline                      │
│               (src/document_pipeline.py)                         │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  Stage 1: Azure Document Translation                     │    │
│  │  Upload to Blob → batch translate → download result      │    │
│  │  (src/document_translator.py)                             │    │
│  └────────────────────────┬─────────────────────────────────┘    │
│                           │                                      │
│                     ┌─────▼──────┐                               │
│                     │ Format?    │                               │
│                     └──┬─────┬───┘                               │
│           DOCX/PPTX/XLSX     PDF/other                           │
│                  │              │                                 │
│                  ▼              ▼                                 │
│  ┌───────────────────────┐  Return as-is                         │
│  │  Stage 2: Extract     │  (no LLM refinement)                  │
│  │  text segments        │                                       │
│  │  (document_handlers)  │                                       │
│  └───────────┬───────────┘                                       │
│              ▼                                                   │
│  ┌───────────────────────┐                                       │
│  │  Stage 3: LLM Refine  │                                       │
│  │  each segment         │                                       │
│  │  (llm_postprocessor)  │                                       │
│  └───────────┬───────────┘                                       │
│              ▼                                                   │
│  ┌───────────────────────┐                                       │
│  │  Stage 4: Re-inject   │                                       │
│  │  refined text into    │                                       │
│  │  document             │                                       │
│  └───────────────────────┘                                       │
└──────────────────────────────────────────────────────────────────┘
                           │
                           ▼
              Translated document (file download)
              Header: X-Was-Refined: true/false
```

### Document Translation Data Flow

1. **Client** uploads a document via `POST /translate/document` (multipart form).
2. **Document Translator** uploads the file to **Azure Blob Storage**, submits a batch translation job to **Azure Document Translation**, polls until complete, and downloads the result.
3. **Format detection** — if the file is DOCX, PPTX, or XLSX (Tier 1), proceed to LLM refinement. Otherwise (PDF, etc.) return the translated document as-is.
4. **Document handler** extracts text segments from the translated document while tracking their positions.
5. Each segment is **refined by the LLM** post-processor.
6. Refined text is **re-injected** into the document, preserving all original formatting.
7. The final document is returned as a **file download**.

### Supported Formats

| Tier | Formats | LLM Refinement | Notes |
|------|---------|-----------------|-------|
| **Tier 1** (full pipeline) | DOCX, PPTX, XLSX | Yes | Text extracted, refined, re-injected with formatting preserved |
| **Tier 2** (translate only) | PDF, HTML, TXT, CSV, etc. | No | Azure Document Translation only — format lacks reliable text extraction |

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Two-stage text pipeline** (Translator → LLM) | Azure Translator is fast, cheap, and reliable for baseline accuracy. The LLM excels at stylistic refinement but is slower and more expensive. Combining both gives the best cost/quality trade-off. |
| **Tiered document pipeline** | Full LLM refinement for DOCX/PPTX/XLSX (structured XML). PDF and others get Azure Document Translation only, since reliable text extraction/re-injection isn't feasible. |
| **Blob Storage for documents** | Azure Document Translation requires files in Blob Storage. Temporary blobs are created per job and cleaned up automatically. |
| **Managed Identity auth** (`DefaultAzureCredential`) | No secrets in code or config files. Works seamlessly in Azure-hosted environments and falls back to developer credentials locally. |
| **Structured JSON logging** (`structlog`) | Each pipeline stage emits structured logs for easy observability and troubleshooting. |
| **JSON-mode LLM output** | Forces the LLM to return structured `{"refined_translation", "refinement_notes"}` for reliable parsing. |
| **Tone & domain hints** | Lets the caller control the LLM's register (formal / casual) and vocabulary (medical / legal / marketing). |

---

## Project Structure

```
post-process-translator-with-llm/
├── src/
│   ├── __init__.py
│   ├── app.py                   # FastAPI application & endpoints
│   ├── config.py                # Pydantic-settings configuration
│   ├── models.py                # Request / response data models
│   ├── pipeline.py              # Text: Translate → Refine
│   ├── translator.py            # Azure Translator text client
│   ├── llm_postprocessor.py     # Azure OpenAI refinement client
│   ├── document_pipeline.py     # Document: Translate → Extract → Refine → Re-inject
│   ├── document_translator.py   # Azure Document Translation + Blob Storage
│   └── document_handlers.py     # DOCX/PPTX/XLSX text extraction & re-injection
├── tests/
│   └── __init__.py
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## Prerequisites

| Resource | Purpose |
|---|---|
| **Azure AI Translator** | Text translation (Cognitive Services) |
| **Azure OpenAI Service** | LLM post-processing (GPT-4o deployment) |
| **Azure Blob Storage** | Temporary file storage for document translation |
| **Azure Managed Identity** | Passwordless auth to all services |

Both services must grant the app's managed identity the appropriate RBAC roles:

- Translator: **Cognitive Services User**
- Azure OpenAI: **Cognitive Services OpenAI User**
- Blob Storage: **Storage Blob Data Contributor**

---

## Setup

### 1. Clone & install

```bash
git clone <repo-url>
cd post-process-translator-with-llm
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -e ".[dev]"
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your Azure resource endpoints:

```bash
cp .env.example .env
```

### 3. Run locally

```bash
uvicorn src.app:app --reload
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Usage

### Translate text

```bash
curl -X POST http://localhost:8000/translate \
  -H "Content-Type: application/json" \
  -d '{
    "text": "The quarterly earnings exceeded all expectations, driven by strong consumer demand.",
    "source_language": "en",
    "target_language": "de",
    "tone": "formal",
    "domain": "finance"
  }'
```

### Response

```json
{
  "source_text": "The quarterly earnings exceeded all expectations...",
  "source_language": "en",
  "target_language": "de",
  "raw_translation": "Die Quartalsergebnisse übertrafen alle Erwartungen...",
  "refined_translation": "Die Quartalsergebnisse haben sämtliche Erwartungen übertroffen...",
  "confidence_score": null,
  "refinement_notes": "Replaced 'übertrafen' with 'haben ... übertroffen' for a more formal register..."
}
```

### Translate a document (Tier 1 — DOCX with LLM refinement)

```bash
curl -X POST http://localhost:8000/translate/document \
  -F "file=@report.docx" \
  -F "source_language=en" \
  -F "target_language=de" \
  -F "tone=formal" \
  -F "domain=finance"
```

Returns the translated DOCX file as a download. The `X-Was-Refined` response header indicates whether LLM post-processing was applied.

### Translate a document (Tier 2 — PDF, no LLM refinement)

```bash
curl -X POST http://localhost:8000/translate/document \
  -F "file=@brochure.pdf" \
  -F "source_language=en" \
  -F "target_language=fr"
```

Returns the translated PDF. `X-Was-Refined: false` since PDF doesn't support text re-injection.

---

## Security

- **No secrets in code** — authentication uses `DefaultAzureCredential` (Managed Identity).
- **Key Vault** recommended for any additional secrets.
- **Least-privilege RBAC** — grant only the roles listed above.
- **Input validation** — Pydantic enforces max text length and language code format.
- **Temporary blobs cleaned up** — source and target blobs are deleted after each document translation job.
