import base64
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Header, HTTPException, Request

from core.cover_letter import CoverLetter
from core.job_processor import JobProcessor
from core.resume import Resume
from core.question_answerer import QuestionAnswerer
from core.core_models import ResumeLayoutConfig
from infrastructure.ai_client import AIClient
from infrastructure.blob_client import BlobClient
from infrastructure.user_data_client import UserDataClient
from models import (
    AppConfig,
    CandidateProfile,
    JobDescription,
    PersonalSummary,
    UserProfile,
)

load_dotenv()
logger = logging.getLogger(__name__)

_DEV_MODE = os.getenv("DEV_MODE", "").lower() == "true"
_DEV_USER_OID = os.getenv("DEV_USER_OID", "")


# --- Config loading ---

def load_app_config(config_file: str) -> AppConfig:
    cfg_path = Path(config_file)
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        raw = json.load(f)
    return AppConfig.model_validate(raw)


def validate_app_config(config_file: str) -> AppConfig:
    cfg = load_app_config(config_file)
    for key in AppConfig.model_fields:
        value = getattr(cfg, key)
        if isinstance(value, Path) and not value.is_file():
            raise FileNotFoundError(f"Missing file for config key '{key}': {value}")
    return cfg


# --- Auth ---

async def get_current_user(
    x_ms_client_principal: str | None = Header(default=None),
    x_user_oid: str | None = Header(default=None),
) -> str:
    """FastAPI dependency that returns the authenticated user's OID.

    In production, reads the X-MS-CLIENT-PRINCIPAL header injected by
    Azure Container Apps Easy Auth. The header is base64-encoded JSON
    containing a claims array; we extract the 'oid' claim.

    In dev (DEV_MODE=true), returns DEV_USER_OID from environment if set,
    otherwise falls back to the X-User-OID header.
    """
    if _DEV_MODE:
        if _DEV_USER_OID:
            logger.debug(f"Dev mode: using DEV_USER_OID: {_DEV_USER_OID}")
            return _DEV_USER_OID
        if x_user_oid:
            logger.debug(f"Dev mode: using X-User-OID header: {x_user_oid}")
            return x_user_oid

    if not x_ms_client_principal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    try:
        decoded = base64.b64decode(x_ms_client_principal).decode("utf-8")
        principal = json.loads(decoded)
        claims = {claim["typ"]: claim["val"] for claim in principal.get("claims", [])}
        oid = claims.get("oid") or claims.get(
            "http://schemas.microsoft.com/identity/claims/objectidentifier"
        )
    except Exception:
        logger.exception("Failed to parse X-MS-CLIENT-PRINCIPAL header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    if not oid:
        logger.error(
            "OID claim missing from principal. Available claims: %s", list(claims.keys())
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    return oid


# --- Application services ---

class ApplicationServices:
    """Wires resume, cover letter, Q&A, and job parsing (no UI).
    Stateless with respect to user data — candidate/profile are passed per request.
    """

    def __init__(
        self,
        config_file: str = os.getenv("APP_CONFIG", "backend/resources/app_config.json"),
        include_feedback: bool = False,
    ):
        self.config = validate_app_config(config_file)
        ai = AIClient()
        self.blob = BlobClient()
        self.user_data = UserDataClient()

        self.resume_builder = Resume(
            config=self.config,
            ai=ai,
            blob=self.blob,
            fit_limit=self.config.fit_limit,
        )
        self.cover_letter_builder = CoverLetter(
            config=self.config,
            ai=ai,
            eval_limit=self.config.eval_limit,
            include_feedback=include_feedback,
        )
        self.question_answerer = QuestionAnswerer(ai=ai)
        self.job_processor = JobProcessor(ai=ai)
        self.default_layout = self.resume_builder.latex_generator.layout

    def get_or_parse_job(
        self, job_posting: str | None, job_desc: JobDescription | None
    ) -> JobDescription:
        if job_desc is not None:
            logger.info("Using client-provided job description")
            return job_desc
        if not job_posting or not job_posting.strip():
            raise ValueError("Provide job_posting text/URL or a parsed job_description.")
        return self.job_processor.process_and_extract_job_info(job_posting)


def get_services(request: Request) -> ApplicationServices:
    return request.app.state.services


def _load_user_profile(
    services: ApplicationServices, user_id: str
) -> tuple[CandidateProfile, UserProfile, PersonalSummary]:
    """Load and validate all three profile blobs for the authenticated user.
    Raises 400 if any file is missing — directs the user to complete profile setup.
    All three blobs are fetched in parallel to reduce latency.
    """
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_personal  = executor.submit(services.user_data.load, user_id, "personal.json")
        f_candidate = executor.submit(services.user_data.load, user_id, "candidate.json")
        f_summary   = executor.submit(services.user_data.load, user_id, "personal_summary.json")

    personal_raw        = f_personal.result()
    candidate_raw       = f_candidate.result()
    personal_summary_raw = f_summary.result()

    if any(raw is None for raw in (personal_raw, candidate_raw, personal_summary_raw)):
        raise ValueError("Profile setup incomplete. Upload all three profile files before using the app.")

    return (
        CandidateProfile.model_validate(candidate_raw),
        UserProfile.model_validate(personal_raw),
        PersonalSummary.model_validate(personal_summary_raw),
    )


def _load_layout(
    services: ApplicationServices, user_id: str
) -> ResumeLayoutConfig | None:
    """Return the user's saved layout, or None to fall back to the app default."""
    raw = services.user_data.load(user_id, "layout.json")
    if raw is None:
        return None
    try:
        return ResumeLayoutConfig.model_validate(raw)
    except Exception:
        logger.warning(f"Invalid layout.json for user {user_id} — using default")
        return None