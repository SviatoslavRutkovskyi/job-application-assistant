from pydantic import BaseModel, Field
from typing import Literal, Optional
from models import Link, ResumeSectionId


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
    links: list[Link] = Field(default_factory=list)
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
    start_date: str
    end_date: str
    degree_line: str
    gpa: Optional[str] = None
    location: str
    line_cost: float


class AnnotatedCertificateEntry(BaseModel):
    id: int
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None
    line_cost: float


class AnnotatedCandidate(BaseModel):
    """CandidateProfile with ids and line costs. No personal info — UserProfile is kept separate."""
    section_heading_line: float
    profile: AnnotatedProfile
    education: list[AnnotatedEducationEntry]
    certificates: list[AnnotatedCertificateEntry] = Field(default_factory=list)
    skills: list[AnnotatedSkillCategory]
    projects: list[AnnotatedProject]
    experience: list[AnnotatedExperience]


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


class ResumeLayoutConfig(BaseModel):
    """Body section order (header is always rendered first, not listed here)."""
    section_order: list[ResumeSectionId]