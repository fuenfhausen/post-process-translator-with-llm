# Post-Process Translator with LLM

Translate text with **Azure Translator** and automatically refine the output using an **Azure OpenAI LLM** so it reads naturally — as if written by a native speaker.

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

### Data Flow

1. **Client** sends a `POST /translate` request with source text, source/target languages, desired tone, and optional domain.
2. **FastAPI** validates the request via Pydantic models.
3. **Pipeline** calls **Azure Translator** (Stage 1) to produce a raw machine translation.
4. **Pipeline** sends the original text + raw translation to **Azure OpenAI** (Stage 2) with a carefully crafted system prompt instructing the LLM to refine the translation for naturalness, idiom usage, and tone.
5. The **combined result** — raw translation, refined translation, and change notes — is returned to the client.

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Two-stage pipeline** (Translator → LLM) | Azure Translator is fast, cheap, and reliable for baseline accuracy. The LLM excels at stylistic refinement but is slower and more expensive. Combining both gives the best cost/quality trade-off. |
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
│   ├── app.py                 # FastAPI application & endpoints
│   ├── config.py              # Pydantic-settings configuration
│   ├── models.py              # Request / response data models
│   ├── pipeline.py            # Orchestration: Translate → Refine
│   ├── translator.py          # Azure Translator client
│   └── llm_postprocessor.py   # Azure OpenAI refinement client
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
| **Azure Managed Identity** | Passwordless auth to both services |

Both services must grant the app's managed identity the appropriate RBAC roles:

- Translator: **Cognitive Services User**
- Azure OpenAI: **Cognitive Services OpenAI User**

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

---

## Security

- **No secrets in code** — authentication uses `DefaultAzureCredential` (Managed Identity).
- **Key Vault** recommended for any additional secrets.
- **Least-privilege RBAC** — grant only the roles listed above.
- **Input validation** — Pydantic enforces max text length and language code format.
