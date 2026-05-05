from pydantic import BaseModel, Field, model_validator
from models import UserProfile, CandidateProfile, PersonalSummary, JobDescription


# --- Job endpoints ---

class JobPostingBody(BaseModel):
    job_posting: str = Field(..., min_length=1, description="Job URL or pasted posting text.")


class JobContextBody(BaseModel):
    job_posting: str | None = None
    job_description: JobDescription | None = None

    @model_validator(mode="after")
    def require_job_source(self) -> "JobContextBody":
        if self.job_description is not None:
            return self
        if self.job_posting is not None and self.job_posting.strip():
            return self
        raise ValueError("Provide job_posting or job_description.")


# --- Cover letter endpoints ---

class CoverLetterResponse(BaseModel):
    cover_letter: str


class CoverLetterPdfBody(BaseModel):
    cover_letter_text: str = Field(..., min_length=1)
    job_description: JobDescription | None = Field(
        default=None,
        description="Optional; used for PDF filename (company name).",
    )


# --- Resume endpoints ---

class TailorResumeBody(JobContextBody):
    resume_feedback: str = ""
    last_resume_json: str | None = None


class TailorResumeResponse(BaseModel):
    last_resume_json: str
    pdf_url: str


class ExportResumeResponse(BaseModel):
    pdf_url: str


# --- Question endpoints ---

class AnswerQuestionBody(JobContextBody):
    question: str


class AnswerQuestionResponse(BaseModel):
    answer: str


# --- Profile endpoints ---

class ProfileExistsResponse(BaseModel):
    exists: bool


class ProfileLineCountResponse(BaseModel):
    lines: float
    min_lines: float
    max_lines: float


class ProfileResponse(BaseModel):
    personal: UserProfile
    candidate: CandidateProfile
    personal_summary: PersonalSummary