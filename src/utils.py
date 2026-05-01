import json
import logging
import math
import os
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


def load_candidate_data(candidate_json_path: str | Path) -> CandidateProfile:
    """Load and validate candidate profile JSON (career content only, no personal info)."""
    try:
        with open(candidate_json_path, encoding="utf-8") as f:
            data = json.load(f)
            return CandidateProfile.model_validate(data)
    except FileNotFoundError:
        logger.error(f"Candidate JSON file not found at {candidate_json_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in candidate file: {e}")
        raise
    except Exception as e:
        logger.error(f"Invalid candidate data structure: {e}")
        raise


def load_user_profile(personal_json_path: str | Path) -> UserProfile:
    """Load and validate user profile JSON (personal/contact info)."""
    try:
        with open(personal_json_path, encoding="utf-8") as f:
            data = json.load(f)
            return UserProfile.model_validate(data)
    except FileNotFoundError:
        logger.error(f"Personal JSON file not found at {personal_json_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in personal file: {e}")
        raise
    except Exception as e:
        logger.error(f"Invalid personal data structure: {e}")
        raise


def annotate_candidate(candidate: CandidateProfile, estimates: dict) -> AnnotatedCandidate:
    """Build AnnotatedCandidate from source data. Assigns ids and computes line costs."""
    chars_per_line_bullet = estimates["chars_per_line_bullet"]

    def annotate_bullets(bullets) -> list[AnnotatedBullet]:
        cost = lambda text: math.ceil(len(text) / chars_per_line_bullet)
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