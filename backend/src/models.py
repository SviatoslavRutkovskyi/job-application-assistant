from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional
from pathlib import Path


# --- App config ---

ResumeSectionId = Literal[
    "profile", "education", "experience", "projects", "skills", "certificates"
]


# --- User identity (separate JSON file, not sent to model) ---

class UserProfile(BaseModel):
    """Contact block rendered in the resume header. Kept out of model prompts."""
    name: str
    location: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    linkedin_label: Optional[str] = None


# --- Personal summary (narrative context for Q&A, not sent to resume/cover letter model) ---

class SummaryTopic(BaseModel):
    topic: str
    response: str


class PersonalSummary(BaseModel):
    """Narrative topics for answering open-ended application questions."""
    topics: list[SummaryTopic] = Field(default_factory=list)


# --- Candidate career content (source JSON, no ids or line costs) ---

class GithubLink(BaseModel):
    name: str
    url: str


class TextItem(BaseModel):
    text: str


class SkillCategory(BaseModel):
    name: str
    skills: list[TextItem]


class Project(BaseModel):
    name: str
    date: str
    github_links: list[GithubLink] = Field(default_factory=list)
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
    start_date: str
    end_date: str
    degree_line: str
    gpa: Optional[str] = None
    location: str


class CertificateEntry(BaseModel):
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None


class CandidateProfile(BaseModel):
    """Source JSON for tailoring; do not invent employers, dates, credentials, or bullets not present here."""
    profile: str
    education: list[EducationEntry]
    certificates: list[CertificateEntry] = Field(default_factory=list)
    skills: list[SkillCategory]
    projects: list[Project]
    experience: list[Experience]


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
    cover_letter_template: Path
    resume_template_tex: Path
    line_estimates_json: Path
    section_order: list[ResumeSectionId] = Field(
        default=["profile", "education", "experience", "projects", "skills", "certificates"]
    )
    eval_limit: int = 5
    fit_limit: int = 3

    @model_validator(mode="after")
    def check_limits(self) -> "AppConfig":
        if self.eval_limit < 1:
            raise ValueError("eval_limit must be >= 1")
        if self.fit_limit < 0:
            raise ValueError("fit_limit must be >= 0")
        return self