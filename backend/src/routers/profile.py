from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
import logging

from api_models import ProfileExistsResponse, ProfileLineCountResponse, ProfileResponse, ResumeUploadResponse
from core.core_models import ResumeLayoutConfig
from core.resume_extractor import ALLOWED_EXTENSIONS
from dependencies import get_current_user, get_services, _load_user_profile, _load_layout
from models import CandidateProfile, PersonalSummary, UserProfile

router = APIRouter(prefix="/api/v1", tags=["profile"])
logger = logging.getLogger(__name__)


@router.get("/auth/me")
def auth_me(request: Request, user_id: str = Depends(get_current_user)):
    return {"oid": user_id}


@router.get("/profile/exists", response_model=ProfileExistsResponse)
def profile_exists(request: Request, user_id: str = Depends(get_current_user)):
    services = get_services(request)
    return ProfileExistsResponse(exists=services.user_data.exists(user_id))


@router.get("/profile", response_model=ProfileResponse)
def get_profile(request: Request, user_id: str = Depends(get_current_user)):
    services = get_services(request)
    candidate, personal, personal_summary = _load_user_profile(services, user_id)
    return ProfileResponse(
        personal=personal,
        candidate=candidate,
        personal_summary=personal_summary,
    )


@router.put("/profile/personal", status_code=status.HTTP_204_NO_CONTENT)
def update_personal(
    body: UserProfile,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    get_services(request).user_data.save(user_id, "personal.json", body.model_dump())


@router.put("/profile/personal-summary", status_code=status.HTTP_204_NO_CONTENT)
def update_personal_summary(
    body: PersonalSummary,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    get_services(request).user_data.save(
        user_id, "personal_summary.json", body.model_dump()
    )


@router.put("/profile/candidate", status_code=status.HTTP_204_NO_CONTENT)
def update_candidate(
    body: CandidateProfile,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    get_services(request).user_data.save(user_id, "candidate.json", body.model_dump())


@router.get("/profile/layout", response_model=ResumeLayoutConfig)
def get_layout(request: Request, user_id: str = Depends(get_current_user)):
    services = get_services(request)
    layout = _load_layout(services, user_id)
    return layout or services.default_layout


@router.put("/profile/layout", status_code=status.HTTP_204_NO_CONTENT)
def update_layout(
    body: ResumeLayoutConfig,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    get_services(request).user_data.save(user_id, "layout.json", body.model_dump())


@router.post("/profile/upload-resume", response_model=ResumeUploadResponse)
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """Extract profile data from an uploaded resume (PDF, DOCX, or TXT) and save it."""
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Please upload a PDF, DOCX, or TXT file.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 10 MB.",
        )

    services = get_services(request)
    try:
        resume_text = services.resume_extractor.extract_text(file_bytes, filename)
        extracted = services.resume_extractor.parse(resume_text)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error during resume extraction for user %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resume extraction failed. Please try again.",
        )

    services.user_data.save(user_id, "personal.json", extracted.personal.model_dump())
    services.user_data.save(user_id, "candidate.json", extracted.candidate.model_dump())

    c = extracted.candidate
    return ResumeUploadResponse(
        personal=extracted.personal,
        candidate=extracted.candidate,
        experience_count=len(c.experience),
        education_count=len(c.education),
        projects_count=len(c.projects),
        skills_count=len(c.skills),
        certificates_count=len(c.certificates),
    )


@router.get("/profile/line-count", response_model=ProfileLineCountResponse)
def get_profile_line_count(request: Request, user_id: str = Depends(get_current_user)):
    """Return the total line count for the user's full candidate content, plus min/max thresholds.
    Used by the frontend to drive the content meter and enable/disable generation buttons."""
    services = get_services(request)
    thresholds = services.resume_builder.line_thresholds

    raw_candidate = services.user_data.load(user_id, "candidate.json")
    if raw_candidate is None:
        return ProfileLineCountResponse(lines=0, **thresholds)

    try:
        candidate = CandidateProfile.model_validate(raw_candidate)
    except Exception:
        return ProfileLineCountResponse(lines=0, **thresholds)

    layout = _load_layout(services, user_id)
    try:
        lines = services.resume_builder.full_line_count(candidate, layout)
    except Exception:
        logger.exception("Error calculating line count for user %s — returning 0", user_id)
        return ProfileLineCountResponse(lines=0, **thresholds)
    return ProfileLineCountResponse(lines=lines, **thresholds)