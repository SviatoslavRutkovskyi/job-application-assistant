import json
import logging
import math
import re
from pathlib import Path

from models import (
    AnnotatedProfile,
    AppConfig,
    AnnotatedBullet,
    AnnotatedCandidate,
    AnnotatedCertificateEntry,
    AnnotatedEducationEntry,
    AnnotatedExperience,
    AnnotatedProject,
    AnnotatedSkill,
    AnnotatedSkillCategory,
    CandidateProfile,
    UserProfile,
)

logger = logging.getLogger(__name__)


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


def sanitize_filename(name: str) -> str:
    if not name:
        return ""
    sanitized = re.sub(r"[^\w\s-]", "", name)
    sanitized = re.sub(r"[-\s]+", "_", sanitized)
    return sanitized.lower().strip("_")



def annotate_candidate(candidate: CandidateProfile, estimates: dict) -> AnnotatedCandidate:
    """Build AnnotatedCandidate from source data. Assigns ids and computes line costs."""
    chars_per_line_bullet = estimates["chars_per_line_bullet"]

    def annotate_bullets(bullets) -> list[AnnotatedBullet]:
        def cost(text: str) -> float:
            return math.ceil(len(text) / chars_per_line_bullet)
        return [AnnotatedBullet(id=j, text=b.text, line_cost=cost(b.text)) for j, b in enumerate(bullets, start=1)]

    return AnnotatedCandidate(
        section_heading_line=estimates["section_heading_line"],
        profile=AnnotatedProfile(text=candidate.profile, line_cost=estimates["profile_lines"]),
        education=[
            AnnotatedEducationEntry(id=i, line_cost=estimates["education_item_line"], **e.model_dump())
            for i, e in enumerate(candidate.education, start=1)
        ],
        certificates=[
            AnnotatedCertificateEntry(id=i, line_cost=estimates["certificate_item_line"], **c.model_dump())
            for i, c in enumerate(candidate.certificates, start=1)
        ],
        skills=[
            AnnotatedSkillCategory(
                id=i, line_cost=estimates["skills_category_line"], name=cat.name,
                skills=[AnnotatedSkill(id=j, text=s.text) for j, s in enumerate(cat.skills, start=1)],
            )
            for i, cat in enumerate(candidate.skills, start=1)
        ],
        experiences=[
            AnnotatedExperience(
                id=i, line_cost=estimates["experience_item_line"],
                bullet_points=annotate_bullets(exp.bullet_points),
                **exp.model_dump(exclude={"bullet_points"}),
            )
            for i, exp in enumerate(candidate.experiences, start=1)
        ],
        projects=[
            AnnotatedProject(
                id=i, line_cost=estimates["project_item_line"],
                bullet_points=annotate_bullets(proj.bullet_points),
                **proj.model_dump(exclude={"bullet_points"}),
            )
            for i, proj in enumerate(candidate.projects, start=1)
        ],
    )