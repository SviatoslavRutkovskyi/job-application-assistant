import json
import math
import logging
import tempfile
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from core.core_models import (
    AnnotatedBullet,
    AnnotatedCandidate,
    AnnotatedCertificateEntry,
    AnnotatedEducationEntry,
    AnnotatedExperience,
    AnnotatedProject,
    AnnotatedProfile,
    AnnotatedSkill,
    AnnotatedSkillCategory,
    ResumeData,
    ResumeLayoutConfig,
    SelectedExperience,
    SelectedProject,
    SelectedSkillsCategory,
)
from core.latex_generator import LatexGenerator
from infrastructure.ai_client import AIClient
from infrastructure.blob_client import BlobClient
from models import AppConfig, CandidateProfile, JobDescription, UserProfile
from utils import sanitize_filename

logger = logging.getLogger(__name__)


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
            for i, exp in enumerate(candidate.experience, start=1)
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


def _apply_layout_filter(ac: AnnotatedCandidate, layout: ResumeLayoutConfig) -> AnnotatedCandidate:
    """Return a copy of AnnotatedCandidate with sections absent from the layout cleared.
    The AI and line counter only see what will actually render."""
    sections = set(layout.section_order)
    return ac.model_copy(update={
        "education":    ac.education    if "education"     in sections else [],
        "certificates": ac.certificates if "certificates"  in sections else [],
        "skills":       ac.skills       if "skills"        in sections else [],
        "experience":  ac.experience  if "experience"    in sections else [],
        "projects":     ac.projects     if "projects"      in sections else [],
    })


class Resume:
    """Resume tailoring class."""

    def __init__(
        self,
        config: AppConfig,
        ai: AIClient,
        blob: BlobClient,
        fit_limit: int,
    ):
        self.config = config
        self.ai = ai
        self.blob = blob
        self.latex_generator = LatexGenerator(config=self.config)
        self.fit_limit = fit_limit

        line_path = Path(self.config.line_estimates_json)
        try:
            self._line_estimates = json.loads(line_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Invalid line estimates JSON at {line_path}: {e}") from e

    def _fit_score(self, lines: float) -> tuple:
        """Return a tuple that encodes how far the resume is from fitting one page.

        (0, 0)       — within the acceptable range; perfect.
        (1, delta)   — too short by `delta` lines.
        (2, delta)   — too long by `delta` lines.

        Tuples compare lexicographically, so (1, x) < (2, y) for any x, y.
        This means too-short is always preferred over too-long: a sparse resume
        is recoverable by the user; an overflowing one gets silently clipped by
        the PDF renderer.
        """
        min_l = self._line_estimates['min_page_lines']
        max_l = self._line_estimates['max_page_lines']
        if lines > max_l:
            return (2, lines - max_l)
        if lines < min_l:
            return (1, min_l - lines)
        return (0, 0)

    def tailor_resume(
        self,
        job_info: JobDescription,
        resume_feedback: str,
        last_resume_content: str | None,
        candidate: CandidateProfile,
        user_profile: UserProfile,
        user_id: str,
        layout: ResumeLayoutConfig | None = None,
    ):
        annotated_candidate = annotate_candidate(candidate, self._line_estimates)
        if layout is not None:
            annotated_candidate = _apply_layout_filter(annotated_candidate, layout)

        ac = annotated_candidate
        edu_costs   = {e.id: e.line_cost for e in ac.education}
        cert_costs  = {c.id: c.line_cost for c in ac.certificates}
        skill_costs = {s.id: s.line_cost for s in ac.skills}
        exp_costs   = {e.id: e.line_cost for e in ac.experience}
        proj_costs  = {p.id: p.line_cost for p in ac.projects}
        exp_bullet_costs  = {e.id: {b.id: b.line_cost for b in e.bullet_points} for e in ac.experience}
        proj_bullet_costs = {p.id: {b.id: b.line_cost for b in p.bullet_points} for p in ac.projects}

        cost_maps = (edu_costs, cert_costs, skill_costs, exp_costs, proj_costs, exp_bullet_costs, proj_bullet_costs)
        system_prompt = self._build_system_prompt(annotated_candidate, user_profile)

        start_time = time.time()
        run_id = uuid4()
        logger.info(f"[tailor_resume called] run_id={run_id}")
        logger.info(f"[1/5] Generating tailored resume content...")

        if last_resume_content:
            logger.info("    Using last resume as base for tailoring")

        message = self._build_user_message(job_info, resume_feedback, last_resume_content)

        best_score = (2, float("inf"))
        best_resume_data = None

        for i in range(self.fit_limit + 1):
            if i > 0:
                elapsed = time.time() - start_time
                logger.info(f"[2/5] Adjusting resume length — attempt {i + 1}/{self.fit_limit + 1} ({elapsed:.1f}s elapsed)")

            resume_data = self.ai.run(system_prompt, message, ResumeData, reasoning=True, reasoning_effort="low")
            lines_calculated = self.calculate_resume_lines(resume_data, annotated_candidate, cost_maps)
            score = self._fit_score(lines_calculated)

            elapsed = time.time() - start_time
            logger.info(
                f"    Attempt [{i + 1}/{self.fit_limit + 1}]: {lines_calculated} lines "
                f"(model estimated: {resume_data.estimated_resume_lines}, "
                f"range: {self._line_estimates['min_page_lines']}–{self._line_estimates['max_page_lines']}) "
                f"({elapsed:.1f}s elapsed)"
            )

            if score < best_score:
                best_score = score
                best_resume_data = resume_data

            if score == (0, 0):
                break

            message = self._build_retry_message(job_info, resume_data.model_dump_json(), lines_calculated)

        resume_data = best_resume_data
        final_lines = self.calculate_resume_lines(resume_data, annotated_candidate, cost_maps)

        if self._fit_score(final_lines) != (0, 0):
            if final_lines > self._line_estimates['max_page_lines']:
                logger.warning(f"Resume still over page limit after retries: {final_lines} lines")
            else:
                logger.warning(
                    f"Insufficient content to fill page: {final_lines} lines — returning best available"
                )

        elapsed = time.time() - start_time
        logger.info(f"[3/5] Converting to LaTeX... ({elapsed:.1f}s elapsed)")

        company_name_sanitized = sanitize_filename(job_info.company_name or "")
        filename_base = f"resume_{company_name_sanitized}" if company_name_sanitized else "resume"

        latex_content = self.latex_generator.convert_to_latex(annotated_candidate, user_profile, resume_data, layout=layout)
        if latex_content is None:
            logger.error("Failed to create LaTeX from resume data")
            return None

        elapsed = time.time() - start_time
        logger.info(f"[4/5] Compiling PDF... ({elapsed:.1f}s elapsed)")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex_path = tmp_path / f"{filename_base}.tex"
            tex_path.write_bytes(latex_content.encode("utf-8"))

            result = subprocess.run(
                ["tectonic", tex_path.name],
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"LaTeX compilation failed with return code {result.returncode}")
                logger.error(f"LaTeX error details: {result.stderr}")
                return None

            blob_name = self.blob.upload(f"{filename_base}.pdf", tex_path.with_suffix(".pdf").read_bytes(), user_id)

        elapsed = time.time() - start_time
        logger.info(f"[5/5] Resume generated successfully: {blob_name} ({elapsed:.1f}s elapsed)")
        return blob_name, resume_data.model_dump_json()

    def export_full_resume(
        self,
        candidate: CandidateProfile,
        user_profile: UserProfile,
        user_id: str,
        layout: ResumeLayoutConfig | None = None,
    ) -> str | None:
        """Compile a PDF containing every section and bullet — no AI selection, no page-fit loop."""
        annotated_candidate = annotate_candidate(candidate, self._line_estimates)
        if layout is not None:
            annotated_candidate = _apply_layout_filter(annotated_candidate, layout)
        ac = annotated_candidate

        resume_data = ResumeData(
            profile=candidate.profile,
            selected_education_ids=[e.id for e in ac.education],
            selected_certificate_ids=[c.id for c in ac.certificates],
            selected_skills=[
                SelectedSkillsCategory(
                    category_id=cat.id,
                    skill_ids=[s.id for s in cat.skills],
                )
                for cat in ac.skills
            ],
            selected_experiences=[
                SelectedExperience(
                    experience_id=exp.id,
                    bullet_ids=[b.id for b in exp.bullet_points],
                )
                for exp in ac.experience
            ],
            selected_projects=[
                SelectedProject(
                    project_id=proj.id,
                    bullet_ids=[b.id for b in proj.bullet_points],
                )
                for proj in ac.projects
            ],
            estimated_resume_lines=0,
        )

        latex_content = self.latex_generator.convert_to_latex(
            annotated_candidate, user_profile, resume_data, layout=layout
        )
        if latex_content is None:
            logger.error("Failed to create LaTeX for full resume export")
            return None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex_path = tmp_path / "resume_full.tex"
            tex_path.write_bytes(latex_content.encode("utf-8"))

            result = subprocess.run(
                ["tectonic", tex_path.name],
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"LaTeX compilation failed: {result.stderr}")
                return None

            blob_name = self.blob.upload(
                "resume_full.pdf",
                tex_path.with_suffix(".pdf").read_bytes(),
                user_id,
            )

        logger.info(f"Full resume exported: {blob_name}")
        return blob_name

    def calculate_resume_lines(self, resume_data: ResumeData, annotated_candidate, cost_maps: tuple) -> float:
        edu_costs, cert_costs, skill_costs, exp_costs, proj_costs, exp_bullet_costs, proj_bullet_costs = cost_maps
        H = annotated_candidate.section_heading_line
        chars_per_line = self._line_estimates["chars_per_line"]

        total = H + math.ceil(len(resume_data.profile) / chars_per_line)

        flat_sections = [
            (resume_data.selected_education_ids,                        edu_costs),
            (resume_data.selected_certificate_ids,                      cert_costs),
            ([sel.category_id for sel in resume_data.selected_skills],  skill_costs),
        ]
        for ids, cost_map in flat_sections:
            if ids:
                total += H + sum(cost_map.get(i, 0) for i in ids)

        if resume_data.selected_experiences:
            total += H
            for se in resume_data.selected_experiences:
                total += exp_costs.get(se.experience_id, 0)
                total += sum(exp_bullet_costs.get(se.experience_id, {}).get(bid, 0) for bid in se.bullet_ids)

        if resume_data.selected_projects:
            total += H
            for sp in resume_data.selected_projects:
                total += proj_costs.get(sp.project_id, 0)
                total += sum(proj_bullet_costs.get(sp.project_id, {}).get(bid, 0) for bid in sp.bullet_ids)

        return total

    def _build_system_prompt(self, annotated_candidate, user_profile: UserProfile) -> str:
        candidate_dict = annotated_candidate.model_dump(
            exclude={"projects": {"__all__": {"github_links"}}}
        )
        candidate_json = json.dumps(candidate_dict, indent=2)
        name = user_profile.name
        location = user_profile.location or ""
        min_l = self._line_estimates["min_page_lines"]
        max_l = self._line_estimates["max_page_lines"]

        return f"""You are a resume editor. The job posting is in the user message.

Candidate name: {name}
Location: {location}

Rules:
- Candidate JSON is the only fact source: employers, titles, schools, dates, tools, metrics, and bullet text must trace to it—no invented credentials or roles.
- Choose what to include for fit; use only ids that exist in that JSON. List ids top-to-bottom as they should read on the page.
- One concise opening paragraph aimed at the role; every claim still supported by that JSON.

## Candidate data
{candidate_json}

## Line budget
Calculate your total using section_heading_line once per included section:
- Profile: section_heading_line + profile.line_cost (write to fill approximately profile.line_cost lines)
- Education, certificates, skills: section_heading_line + sum of selected item line_cost values
- Experience, projects: section_heading_line + sum of (item.line_cost + sum of selected bullet line_cost values)

Your estimated_resume_lines must equal your calculated total.
Acceptable range: {min_l}–{max_l} lines.
If your total exceeds {max_l}, remove content. If your total is below {min_l}, add content.
If you receive feedback stating your actual line count, treat it as truth and adjust accordingly."""

    def _job_section(self, job_info: JobDescription) -> str:
        return f"## Job posting\n{job_info.model_dump_json(indent=2)}"

    def _build_user_message(self, job_info: JobDescription, resume_feedback: str, last_resume_content: str | None):
        parts = [self._job_section(job_info)]

        if last_resume_content:
            parts.append(
                f"## Previous resume output\n{last_resume_content}\n\n"
                "Use as the starting point; keep selections and bullets unless user notes require changes."
            )

        if resume_feedback:
            parts.append(f"## User notes\n{resume_feedback}")

        return "\n\n".join(parts)

    def _build_retry_message(self, job_info: JobDescription, previous_output: str, lines_calculated: float) -> str:
        min_l = self._line_estimates['min_page_lines']
        max_l = self._line_estimates['max_page_lines']
        direction, target = ("Remove", max_l) if lines_calculated > max_l else ("Add", min_l)

        parts = [
            self._job_section(job_info),
            f"## Previous attempt\n{previous_output}",
            (
                f"## Size correction only\n"
                f"This attempt has {lines_calculated} lines. Acceptable range: {min_l}–{max_l} lines.\n"
                f"{direction} content equivalent to {abs(lines_calculated - target)} lines to reach the acceptable range."
            ),
        ]
        return "\n\n".join(parts)