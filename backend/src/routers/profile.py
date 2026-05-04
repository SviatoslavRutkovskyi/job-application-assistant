from fastapi import APIRouter, Depends, HTTPException, Request, status

from api_models import ProfileExistsResponse, ProfileResponse
from dependencies import get_current_user, get_services, _load_user_profile
from models import CandidateProfile, PersonalSummary, UserProfile

router = APIRouter(prefix="/api/v1", tags=["profile"])


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
    try:
        candidate, personal, personal_summary = _load_user_profile(services, user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Complete profile setup first.",
        )
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