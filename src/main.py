import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ai_client import AIClient
from blob_client import BlobClient
from cover_letter import CoverLetter
from job_processor import JobProcessor
from models import (
    AnswerQuestionBody,
    AnswerQuestionResponse,
    CandidateProfile,
    CoverLetterPdfBody,
    CoverLetterResponse,
    JobDescription,
    JobPostingBody,
    JobContextBody,
    PersonalSummary,
    TailorResumeBody,
    TailorResumeResponse,
    UserProfile,
)
from question_answerer import QuestionAnswerer
from resume import Resume
from user_data_client import UserDataClient
from utils import load_json_model, sanitize_filename, validate_app_config


load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


class ApplicationServices:
    """Wires resume, cover letter, Q&A, and job parsing (no UI).
    Stateless with respect to user data — candidate/profile are passed per request.
    """

    def __init__(
        self,
        config_file: str = os.getenv("APP_CONFIG", "resources/app_config.json"),
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
        self.question_answerer = QuestionAnswerer(config=self.config, ai=ai)
        self.job_processor = JobProcessor(ai=ai)

    def get_or_parse_job(
        self, job_posting: str | None, job_desc: JobDescription | None
    ) -> JobDescription:
        if job_desc is not None:
            logger.info("Using client-provided job description")
            return job_desc
        if not job_posting or not job_posting.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide job_posting text/URL or a parsed job_description.",
            )
        return self.job_processor.process_and_extract_job_info(job_posting)


# TODO (Step 3): Replace with get_current_user() dependency that reads the OID
# from the Easy Auth header and returns it as a string.
#
# TODO (Step 5): Replace _load_user_data() with per-user blob loading:
#   raw = services.user_data.load(user_id, "candidate.json")
#   candidate = CandidateProfile.model_validate(raw)
#   ... etc.
def _load_user_data() -> tuple[CandidateProfile, UserProfile, PersonalSummary]:
    """Temporary: loads from local files for single-user dev.
    Replaced in Step 5 with per-request blob loading keyed by authenticated user OID.
    """
    candidate = load_json_model("you/candidate_CS.json", CandidateProfile, "candidate")
    user_profile = load_json_model("you/personal_CS.json", UserProfile, "personal")
    personal_summary = load_json_model("you/personal_summary_CS.json", PersonalSummary, "personal_summary")
    return candidate, user_profile, personal_summary


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.services = ApplicationServices()
    yield


app = FastAPI(
    title="Job Application Assistant",
    description="Parse job postings, generate cover letters, tailor resumes, and answer application questions.",
    lifespan=lifespan,
)

app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


def get_services(request: Request) -> ApplicationServices:
    return request.app.state.services


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return HTMLResponse((Path("frontend") / "index.html").read_text())


@app.post("/api/v1/job/parse", response_model=JobDescription)
def parse_job(body: JobPostingBody, request: Request):
    services = get_services(request)
    return services.job_processor.process_and_extract_job_info(body.job_posting.strip())


@app.post("/api/v1/cover-letter", response_model=CoverLetterResponse)
def generate_cover_letter(body: JobContextBody, request: Request):
    services = get_services(request)
    candidate, user_profile, _ = _load_user_data()
    job_desc = services.get_or_parse_job(body.job_posting, body.job_description)
    cover_letter = services.cover_letter_builder.request_letter(job_desc, candidate, user_profile)
    return CoverLetterResponse(cover_letter=cover_letter)


@app.post("/api/v1/cover-letter/pdf")
def cover_letter_pdf(body: CoverLetterPdfBody, request: Request):
    services = get_services(request)
    company_name = body.job_description.company_name if body.job_description else None
    pdf_bytes = services.cover_letter_builder.convert_cover_letter_to_pdf(body.cover_letter_text)
    if pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate cover letter PDF.",
        )
    filename = f"cover_letter_{sanitize_filename(company_name)}.pdf" if company_name else "cover_letter.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/v1/resume/tailor", response_model=TailorResumeResponse)
def tailor_resume(body: TailorResumeBody, request: Request):
    services = get_services(request)
    candidate, user_profile, _ = _load_user_data()
    job_desc = services.get_or_parse_job(body.job_posting, body.job_description)
    result = services.resume_builder.tailor_resume(
        job_desc, body.resume_feedback, body.last_resume_json, candidate, user_profile
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Resume tailoring or PDF compilation failed.",
        )
    blob_name, resume_json = result
    return TailorResumeResponse(
        last_resume_json=resume_json,
        pdf_url=blob_name,
    )


@app.get("/api/v1/resume/download/{blob_name:path}")
def download_resume(blob_name: str, request: Request):
    """Proxies PDF from Blob Storage to the client."""
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


@app.post("/api/v1/questions/answer", response_model=AnswerQuestionResponse)
def answer_question(body: AnswerQuestionBody, request: Request):
    if not body.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please enter a question.",
        )
    services = get_services(request)
    candidate, user_profile, personal_summary = _load_user_data()
    job_desc = services.get_or_parse_job(body.job_posting, body.job_description)
    answer = services.question_answerer.answer_question(
        job_desc, body.question, candidate, user_profile, personal_summary
    )
    return AnswerQuestionResponse(answer=answer)


if __name__ == "__main__":
    import uvicorn

    logger.info("Local server starting at http://localhost:7860")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=7860,
        reload=False,
    )