import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from api_models import (
    AnswerQuestionBody,
    AnswerQuestionResponse,
    CoverLetterPdfBody,
    CoverLetterResponse,
    ExportResumeResponse,
    JobContextBody,
    TailorResumeBody,
    TailorResumeResponse,
)
from dependencies import get_current_user, get_services, _load_user_profile, _load_layout, _validate_user_profile
from utils import sanitize_filename

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["generation"])


# --- Cover letter ---

@router.post("/cover-letter", response_model=CoverLetterResponse)
def generate_cover_letter(
    body: JobContextBody,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    services = get_services(request)
    candidate, user_profile, _ = _load_user_profile(services, user_id)
    _validate_user_profile(user_profile)
    job_desc = services.get_or_parse_job(body.job_posting, body.job_description)
    cover_letter = services.cover_letter_builder.request_letter(
        job_desc, candidate, user_profile
    )
    return CoverLetterResponse(cover_letter=cover_letter)


@router.post("/cover-letter/pdf")
def cover_letter_pdf(
    body: CoverLetterPdfBody,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    services = get_services(request)
    company_name = body.job_description.company_name if body.job_description else None
    pdf_bytes = services.cover_letter_builder.convert_cover_letter_to_pdf(
        body.cover_letter_text
    )
    if pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate cover letter PDF.",
        )
    filename = (
        f"cover_letter_{sanitize_filename(company_name)}.pdf"
        if company_name
        else "cover_letter.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# --- Resume ---

@router.post("/resume/tailor", response_model=TailorResumeResponse)
def tailor_resume(
    body: TailorResumeBody,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    services = get_services(request)
    candidate, user_profile, _ = _load_user_profile(services, user_id)
    _validate_user_profile(user_profile)
    job_desc = services.get_or_parse_job(body.job_posting, body.job_description)
    layout = _load_layout(services, user_id)
    result = services.resume_builder.tailor_resume(
        job_desc, body.resume_feedback, body.last_resume_json, candidate, user_profile, user_id, layout
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resume tailoring or PDF compilation failed.",
        )
    blob_name, resume_json = result
    return TailorResumeResponse(last_resume_json=resume_json, pdf_url=blob_name)


@router.post("/resume/export", response_model=ExportResumeResponse)
def export_resume(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    services = get_services(request)
    candidate, user_profile, _ = _load_user_profile(services, user_id)
    _validate_user_profile(user_profile)
    layout = _load_layout(services, user_id)
    blob_name = services.resume_builder.export_full_resume(candidate, user_profile, user_id, layout)
    if blob_name is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Full resume export failed.",
        )
    return ExportResumeResponse(pdf_url=blob_name)


@router.get("/resume/download/{blob_name:path}")
def download_resume(
    blob_name: str,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """Proxies PDF from Blob Storage to the client."""
    if not blob_name.startswith(f"{user_id}/"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    try:
        pdf_bytes, filename = get_services(request).blob.download(blob_name)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Failed to download blob {blob_name}: {e}")
        raise HTTPException(status_code=404, detail="Resume not found.")


# --- Questions ---

@router.post("/questions/answer", response_model=AnswerQuestionResponse)
def answer_question(
    body: AnswerQuestionBody,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    if not body.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please enter a question.",
        )
    services = get_services(request)
    candidate, user_profile, personal_summary = _load_user_profile(services, user_id)
    _validate_user_profile(user_profile)
    job_desc = services.get_or_parse_job(body.job_posting, body.job_description)
    answer = services.question_answerer.answer_question(
        job_desc, body.question, candidate, user_profile, personal_summary
    )
    return AnswerQuestionResponse(answer=answer)