# Job Application Assistant

An AI-powered web app that generates tailored cover letters, customizes resumes to a single page, and answers application questions — all from a job posting URL or pasted text.

Built with a **FastAPI backend**, a **minimal static frontend**, and deployed to **Azure Container Apps**.

## Features

- **Cover letter generation** — generates a personalized cover letter using a two-model evaluator–optimizer loop. A generator produces a draft, an evaluator scores it across multiple dimensions and returns feedback, and the loop retries until the letter passes or the attempt limit is reached. Outputs plain text and PDF.
- **Resume tailoring** — selects and reorders resume content to match the job description, with automatic page-fit enforcement to ensure the output compiles to exactly one page. Supports iterative refinement: you can provide optional notes to guide the model and optionally use a previous tailored result as the starting point rather than regenerating from scratch.
- **Full resume export** — compiles your complete candidate profile into a formatted multi-page PDF without any tailoring or content trimming.
- **Resume upload and extraction** — upload a PDF, DOCX, or TXT resume to automatically populate your candidate profile using AI extraction.
- **Interview question answering** — answers open-ended application questions in first person using your candidate profile and the job description.
- **Job posting scraping** — accepts a job posting URL or pasted text; URLs are automatically scraped and parsed into structured data used across all features.
- **Per-user profiles** — each authenticated user has isolated profile data stored in Azure Blob Storage, including personal info, candidate content, a personal summary, and a customizable resume section layout.

## Architecture

```
Azure Container Apps (Easy Auth → Microsoft Entra ID)
├── FastAPI backend        (backend/src/)
├── Static frontend        (frontend/)
├── Azure Blob Storage     (user profiles + generated PDFs)
└── OpenAI API             (gpt-4o, o4-mini)
```

Authentication is handled by Azure Container Apps Easy Auth. The app reads the `X-MS-CLIENT-PRINCIPAL` header injected by the platform and extracts the user's OID claim to scope all storage reads and writes.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency management
- [Tectonic](https://tectonic-typesetting.github.io/en-US/install.html) for LaTeX PDF compilation (required for resume generation)
- Python 3.12+
- An OpenAI API key with access to `gpt-4o` and `o4-mini`
- An Azure Storage Account with two containers: `user-profiles` and `outputs`

## Local Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment variables

Create a `.env` file in the root directory:

```env
OPENAI_API_KEY=your_openai_key_here
AZURE_STORAGE_ACCOUNT_NAME=your_storage_account_name

# Local development — bypasses Azure Easy Auth
DEV_MODE=true
DEV_USER_OID=local-dev-user
```

`DEV_MODE=true` skips the `X-MS-CLIENT-PRINCIPAL` header check. `DEV_USER_OID` sets the user identity used for all storage operations. In production these variables should be absent; auth is handled by the platform.

The app uses `DefaultAzureCredential` for Azure Storage access. Locally, make sure you are logged in via the Azure CLI (`az login`) or have another credential source configured.

### 3. Run the app

```bash
uv run python backend/src/main.py
```

The app starts at `http://localhost:7860`.

- **UI**: `http://localhost:7860/`
- **API docs (Swagger)**: `http://localhost:7860/docs`

## Deployment

The app is containerized and deployed to Azure Container Apps via GitHub Actions on every push to `main`.

### Build and run with Docker

```bash
docker build -t resume-pipeline-app .
docker run -p 7860:7860 \
  -e OPENAI_API_KEY=your_key \
  -e AZURE_STORAGE_ACCOUNT_NAME=your_account \
  -e DEV_MODE=true \
  -e DEV_USER_OID=local-dev-user \
  resume-pipeline-app
```

### CI/CD

The GitHub Actions workflow (`.github/workflows/docker-image.yml`) builds the image, pushes it to Azure Container Registry (`resumepipelineacr.azurecr.io`), and deploys to the `resume-pipeline-app` Container App in the `resume-pipeline-rg` resource group. Authentication uses OIDC — no long-lived secrets.

Required GitHub secrets:

- `RESUMEPIPELINEAPP_AZURE_CLIENT_ID`
- `RESUMEPIPELINEAPP_AZURE_TENANT_ID`
- `RESUMEPIPELINEAPP_AZURE_SUBSCRIPTION_ID`
- `RESUMEPIPELINEAPP_REGISTRY_USERNAME`
- `RESUMEPIPELINEAPP_REGISTRY_PASSWORD`

## API Endpoints (v1)

**Auth**

- `GET /api/v1/auth/me` — returns the authenticated user's OID

**Profile**

- `GET /api/v1/profile/exists` — checks whether the user has completed profile setup
- `GET /api/v1/profile` — returns all profile data (personal, candidate, personal summary)
- `PUT /api/v1/profile/personal` — save personal info
- `PUT /api/v1/profile/personal-summary` — save personal summary
- `PUT /api/v1/profile/candidate` — save candidate content
- `GET /api/v1/profile/layout` — get resume section layout (user override or app default)
- `PUT /api/v1/profile/layout` — save resume section layout
- `POST /api/v1/profile/upload-resume` — extract and save profile from an uploaded PDF, DOCX, or TXT
- `GET /api/v1/profile/line-count` — returns total line count for the full candidate profile plus min/max thresholds

**Job**

- `POST /api/v1/job/parse` — scrape and extract structured data from a job posting URL or text

**Generation**

- `POST /api/v1/cover-letter` — generate a tailored cover letter (text)
- `POST /api/v1/cover-letter/pdf` — convert a cover letter to PDF
- `POST /api/v1/resume/tailor` — tailor and compile a one-page resume PDF for a specific job
- `POST /api/v1/resume/export` — compile and export a full (untailored) resume PDF
- `GET /api/v1/resume/download/{blob_name}` — proxy a generated PDF from Blob Storage to the client
- `POST /api/v1/questions/answer` — answer an open-ended application question

**Health**

- `GET /health`

## Project Structure

```
backend/
├── src/
│   ├── main.py                    # App entry point (FastAPI + static mount)
│   ├── dependencies.py            # Auth, service wiring, profile loading
│   ├── api_models.py              # API request/response models
│   ├── models.py                  # Domain models (candidate, job, config)
│   ├── utils.py                   # Shared utilities
│   ├── core/
│   │   ├── cover_letter.py        # Cover letter generator and evaluator loop
│   │   ├── resume.py              # Resume tailoring and page-fit enforcement
│   │   ├── resume_extractor.py    # AI-powered resume parsing from uploaded files
│   │   ├── job_processor.py       # Job posting scraping and structured extraction
│   │   ├── question_answerer.py   # Application question answering
│   │   ├── latex_generator.py     # LaTeX generation from resume data
│   │   └── core_models.py         # Shared core data models
│   ├── infrastructure/
│   │   ├── ai_client.py           # OpenAI API wrapper
│   │   ├── blob_client.py         # Azure Blob Storage — generated PDF outputs
│   │   └── user_data_client.py    # Azure Blob Storage — per-user profile data
│   └── routers/
│       ├── generation.py          # Cover letter, resume, and Q&A endpoints
│       ├── job.py                 # Job parsing endpoint
│       └── profile.py             # Profile CRUD and resume upload endpoints
└── resources/
    ├── app_config.json            # File paths and generation parameters
    ├── resume_template.tex        # LaTeX resume template
    ├── resume_layout.json         # Default section order configuration
    ├── line_estimates.json        # Line budget weights for page fitting
    └── cover_letter_template.txt  # Cover letter structure template
frontend/
├── index.html                     # Main app shell
├── landing.html                   # Landing page
├── login.html                     # Login page
├── profile-setup.html             # Profile setup UI
├── app.js                         # Main app logic
├── auth.js                        # Auth helpers
├── profile-setup.js               # Profile setup logic
└── style.css                      # Styles
scripts/
└── migrate.py                     # Data migration utility
```

## Known Limitations

- Some job posting URLs may not scrape reliably due to bot detection. Pasting the job description text directly is more reliable.
- Local development requires an Azure Storage Account. There is no in-memory or local filesystem fallback for storage.
