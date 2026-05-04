from fastapi import APIRouter, Depends, Request

from api_models import JobPostingBody
from dependencies import get_current_user, get_services
from models import JobDescription

router = APIRouter(prefix="/api/v1", tags=["job"])


@router.post("/job/parse", response_model=JobDescription)
def parse_job(
    body: JobPostingBody,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    services = get_services(request)
    return services.job_processor.process_and_extract_job_info(body.job_posting.strip())
