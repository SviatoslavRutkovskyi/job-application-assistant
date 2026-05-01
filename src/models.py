from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional
from pathlib import Path


# --- User identity (separate JSON file, not sent to model) ---

class UserProfile(BaseModel):
    """Contact block rendered in the resume header. Kept out of model prompts."""
    name: str
    location: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    linkedin_label: Optional[str] = None


# --- Candidate career content (source JSON, no ids or line costs) ---

class TextItem(BaseModel):
    text: str


class SkillCategory(BaseModel):
    name: str
    skills: list[TextItem]


class Project(BaseModel):
    name: str
    date: str
    github_link_names: list[str] = Field(default_factory=list)
    github_links: list[str] = Field(default_factory=list)
    bullet_points: list[TextItem]


class Experience(BaseModel):
    company_name: str
    job_title: str
    start_date: str
    end_date: str
    location: str
    bullet_points: list[TextItem]


class EducationEntry(BaseModel):
    institution: str
    date_range: str
    degree_line: str
    location: str


class CertificateEntry(BaseModel):
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None
    details: Optional[str] = None


class CandidateProfile(BaseModel):
    """Source JSON for tailoring; do not invent employers, dates, credentials, or bullets not present here."""
    profile: str
    education: list[EducationEntry]
    certificates: list[CertificateEntry] = Field(default_factory=list)
    skills: list[SkillCategory]
    projects: list[Project]
    experiences: list[Experience]


# --- Annotated candidate (built in memory; ids + line costs added at runtime) ---

class AnnotatedProfile(BaseModel):
    text: str
    line_cost: float


class AnnotatedBullet(BaseModel):
    id: int
    text: str
    line_cost: float


class AnnotatedSkill(BaseModel):
    id: int
    text: str


class AnnotatedSkillCategory(BaseModel):
    id: int
    name: str
    line_cost: float
    skills: list[AnnotatedSkill]


class AnnotatedProject(BaseModel):
    id: int
    name: str
    date: str
    github_link_names: list[str] = Field(default_factory=list)
    github_links: list[str] = Field(default_factory=list)
    line_cost: float
    bullet_points: list[AnnotatedBullet]


class AnnotatedExperience(BaseModel):
    id: int
    company_name: str
    job_title: str
    start_date: str
    end_date: str
    location: str
    line_cost: float
    bullet_points: list[AnnotatedBullet]


class AnnotatedEducationEntry(BaseModel):
    id: int
    institution: str
    date_range: str
    degree_line: str
    location: str
    line_cost: float


class AnnotatedCertificateEntry(BaseModel):
    id: int
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None
    details: Optional[str] = None
    line_cost: float


class AnnotatedCandidate(BaseModel):
    """CandidateProfile with ids and line costs. No personal info — UserProfile is kept separate."""
    section_heading_line: float
    profile: AnnotatedProfile
    education: list[AnnotatedEducationEntry]
    certificates: list[AnnotatedCertificateEntry] = Field(default_factory=list)
    skills: list[AnnotatedSkillCategory]
    projects: list[AnnotatedProject]
    experiences: list[AnnotatedExperience]


# --- Tailored resume output (model returns IDs + rewritten profile only) ---

class SelectedSkillsCategory(BaseModel):
    category_id: int
    skill_ids: list[int]


class SelectedProject(BaseModel):
    project_id: int
    bullet_ids: list[int]


class SelectedExperience(BaseModel):
    experience_id: int
    bullet_ids: list[int]


class ResumeData(BaseModel):
    profile: str
    selected_education_ids: list[int] = Field(default_factory=list)
    selected_skills: list[SelectedSkillsCategory]
    selected_projects: list[SelectedProject]
    selected_experiences: list[SelectedExperience]
    selected_certificate_ids: list[int] = Field(default_factory=list)
    estimated_resume_lines: float


# --- Resume layout ---

ResumeSectionId = Literal[
    "profile", "education", "experience", "projects", "skills", "certificates"
]


class ResumeLayoutConfig(BaseModel):
    """Body section order (header is always rendered first, not listed here)."""
    section_order: list[ResumeSectionId]


# --- Text generation output ---

class TextResponse(BaseModel):
    text: str


# --- Cover letter ---

class Evaluation(BaseModel):
    is_acceptable: bool
    feedback: str
    score: int


# --- Job description ---

class JobDescription(BaseModel):
    """Structured info extracted from a job posting for resume & cover letter generation."""
    company_name: Optional[str] = None
    job_title: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    key_phrases: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    description_summary: Optional[str] = None
    values: list[str] = Field(default_factory=list)
    culture_text: Optional[str] = None


# --- App config ---

class AppConfig(BaseModel):
    """App configuration. Paths are interpreted relative to the current working directory."""
    candidate_json: Path
    personal_json: Path
    cover_letter_template: Path
    resume_template_tex: Path
    resume_layout_json: Path
    line_estimates_json: Path
    personal_summary: Path


# --- API models ---

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


class CoverLetterResponse(BaseModel):
    cover_letter: str


class CoverLetterPdfBody(BaseModel):
    cover_letter_text: str = Field(..., min_length=1)
    job_description: JobDescription | None = Field(
        default=None,
        description="Optional; used for PDF filename (company name).",
    )


class TailorResumeBody(JobContextBody):
    resume_feedback: str = ""
    last_resume_json: str | None = None


class TailorResumeResponse(BaseModel):
    last_resume_json: str
    pdf_url: str


class AnswerQuestionBody(JobContextBody):
    question: str


class AnswerQuestionResponse(BaseModel):
    answer: str