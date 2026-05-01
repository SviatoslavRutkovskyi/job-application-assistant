import json
import tempfile
import subprocess
import time
import logging
from pathlib import Path
from uuid import uuid4
import math

from ai_client import AIClient
from latex_generator import LatexGenerator
from models import AppConfig, CandidateProfile, JobDescription, ResumeData, UserProfile
from blob_client import BlobClient
from utils import annotate_candidate, load_json_model, sanitize_filename

logger = logging.getLogger(__name__)


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

        self.user_profile = load_json_model(self.config.personal_json, UserProfile, "personal")
        candidate_data = load_json_model(self.config.candidate_json, CandidateProfile, "candidate")
        self.annotated_candidate = annotate_candidate(candidate_data, self._line_estimates)

        # Cache lookup dicts — annotated_candidate never mutates after init
        ac = self.annotated_candidate
        self._edu_costs   = {e.id: e.line_cost for e in ac.education}
        self._cert_costs  = {c.id: c.line_cost for c in ac.certificates}
        self._skill_costs = {s.id: s.line_cost for s in ac.skills}
        self._exp_costs   = {e.id: e.line_cost for e in ac.experiences}
        self._proj_costs  = {p.id: p.line_cost for p in ac.projects}
        self._exp_bullet_costs  = {e.id: {b.id: b.line_cost for b in e.bullet_points} for e in ac.experiences}
        self._proj_bullet_costs = {p.id: {b.id: b.line_cost for b in p.bullet_points} for p in ac.projects}

        self.system_prompt = self._build_system_prompt()

    def _fit_score(self, lines: float) -> tuple:
        min_l = self._line_estimates['min_page_lines']
        max_l = self._line_estimates['max_page_lines']
        if lines > max_l:
            return (2, lines - max_l)
        if lines < min_l:
            return (1, min_l - lines)
        return (0, 0)

    def tailor_resume(self, job_info: JobDescription, resume_feedback, last_resume_content=None):
        start_time = time.time()
        run_id = uuid4()
        logger.info(f"[tailor_resume called] run_id={run_id}")
        logger.info(f"[1/4] Generating tailored resume content...")

        if last_resume_content:
            logger.info("    Using last resume as base for tailoring")


        initial_message = self._build_user_message(job_info, resume_feedback, last_resume_content)
        resume_data = self.ai.run(self.system_prompt, initial_message, ResumeData, reasoning=True, reasoning_effort="low")
        lines_calculated = self.calculate_resume_lines(resume_data)
        score = self._fit_score(lines_calculated)

        elapsed = time.time() - start_time
        logger.info(f"[2/4] Verifying resume length... ({elapsed:.1f}s elapsed)")
        logger.info(
            f"    [attempt 1/{self.fit_limit + 1}]: {lines_calculated} lines "
            f"(model estimated: {resume_data.estimated_resume_lines}, "
            f"range: {self._line_estimates['min_page_lines']}–{self._line_estimates['max_page_lines']})"
        )

        best_score = score
        best_resume_data = resume_data

        for i in range(self.fit_limit):
            if score == (0, 0):
                break

            elapsed = time.time() - start_time
            logger.info(f"[2/4] Adjusting resume length... ({elapsed:.1f}s elapsed)")
            retry_message = self._build_retry_message(job_info, resume_data.model_dump_json(), lines_calculated)
            resume_data = self.ai.run(self.system_prompt, retry_message, ResumeData, reasoning=True, reasoning_effort="low")
            lines_calculated = self.calculate_resume_lines(resume_data)
            score = self._fit_score(lines_calculated)

            logger.info(
                f"    [attempt {i + 2}/{self.fit_limit + 1}]: {lines_calculated} lines "
                f"(model estimated: {resume_data.estimated_resume_lines}, "
                f"range: {self._line_estimates['min_page_lines']}–{self._line_estimates['max_page_lines']})"
            )

            if score < best_score:
                best_score = score
                best_resume_data = resume_data

        resume_data = best_resume_data
        final_lines = self.calculate_resume_lines(resume_data)

        if self._fit_score(final_lines) != (0, 0):
            if final_lines > self._line_estimates['max_page_lines']:
                logger.warning(f"Resume still over page limit after retries: {final_lines} lines")
            else:
                logger.warning(
                    f"Insufficient content to fill page: {final_lines} lines — returning best available"
                )

        elapsed = time.time() - start_time
        logger.info(f"[3/4] Converting to LaTeX... ({elapsed:.1f}s elapsed)")

        company_name_sanitized = sanitize_filename(job_info.company_name or "")
        filename_base = f"resume_{company_name_sanitized}" if company_name_sanitized else "resume"

        latex_content = self.latex_generator.convert_to_latex(self.annotated_candidate, self.user_profile, resume_data)
        if latex_content is None:
            logger.error("Failed to create LaTeX from resume data")
            return None

        elapsed = time.time() - start_time
        logger.info(f"[4/4] Compiling PDF... ({elapsed:.1f}s elapsed)")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tex_path = tmp_path / f"{filename_base}.tex"
            tex_path.write_bytes(latex_content.encode("utf-8"))
            pdf_path = tex_path.with_suffix(".pdf")

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

            blob_name = self.blob.upload(f"{filename_base}.pdf", pdf_path.read_bytes())

        elapsed = time.time() - start_time
        logger.info(f"Resume generated successfully: {blob_name} ({elapsed:.1f}s elapsed)")
        return blob_name, resume_data.model_dump_json()

    def calculate_resume_lines(self, resume_data: ResumeData) -> float:
        H = self.annotated_candidate.section_heading_line
        chars_per_line = self._line_estimates["chars_per_line"]

        total = H + math.ceil(len(resume_data.profile) / chars_per_line)

        flat_sections = [
            (resume_data.selected_education_ids,                        self._edu_costs),
            (resume_data.selected_certificate_ids,                      self._cert_costs),
            ([sel.category_id for sel in resume_data.selected_skills],  self._skill_costs),
        ]
        for ids, cost_map in flat_sections:
            if ids:
                total += H + sum(cost_map.get(i, 0) for i in ids)

        if resume_data.selected_experiences:
            total += H
            for se in resume_data.selected_experiences:
                total += self._exp_costs.get(se.experience_id, 0)
                total += sum(self._exp_bullet_costs.get(se.experience_id, {}).get(bid, 0) for bid in se.bullet_ids)

        if resume_data.selected_projects:
            total += H
            for sp in resume_data.selected_projects:
                total += self._proj_costs.get(sp.project_id, 0)
                total += sum(self._proj_bullet_costs.get(sp.project_id, {}).get(bid, 0) for bid in sp.bullet_ids)

        return total

    def _build_system_prompt(self):
        candidate_dict = self.annotated_candidate.model_dump(
            exclude={"projects": {"__all__": {"github_links", "github_link_names"}}}
        )
        candidate_json = json.dumps(candidate_dict, indent=2)
        name = self.user_profile.name
        location = self.user_profile.location or ""
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

    def _build_user_message(self, job_info: JobDescription, resume_feedback, last_resume_content=None):
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