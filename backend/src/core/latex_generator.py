"""Build resume .tex from AnnotatedCandidate + UserProfile + ResumeData and a LaTeX preamble template."""

from __future__ import annotations

import re
import logging
from pathlib import Path

from core.core_models import (
    AnnotatedCandidate,
    AnnotatedCertificateEntry,
    AnnotatedEducationEntry,
    AnnotatedExperience,
    AnnotatedProject,
    ResumeData,
    ResumeLayoutConfig,
)
from models import AppConfig, UserProfile

logger = logging.getLogger(__name__)


def _line_start(s: str, idx: int) -> int:
    prev = s.rfind("\n", 0, idx)
    return 0 if prev == -1 else prev + 1


def _line_end_after(s: str, idx: int) -> int:
    n = s.find("\n", idx)
    return len(s) if n == -1 else n + 1


def _replace_marked_block(tex: str, tag: str, body: str, *, path: Path) -> str:
    doc_start = tex.find(r"\begin{document}")
    if doc_start == -1:
        raise ValueError(f"Template {path} missing \\begin{{document}}")
    begin = f"% resume-generator:begin {tag}"
    end = f"% resume-generator:end {tag}"
    i = tex.find(begin, doc_start)
    if i == -1:
        raise ValueError(f"Template {path} missing {begin!r}")
    j = tex.find(end, i + len(begin))
    if j == -1:
        raise ValueError(f"Template {path} missing {end!r} after {begin!r}")
    ls = _line_start(tex, i)
    le = _line_end_after(tex, j)
    if not body.endswith("\n"):
        body += "\n"
    return tex[:ls] + body + tex[le:]


def _tel_href(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    return digits if digits else phone


def _resolve(source: list, selected_ids: list[int]) -> list:
    """Return source items whose .id appears in selected_ids, in selection order."""
    by_id = {item.id: item for item in source}
    return [by_id[i] for i in selected_ids if i in by_id]


def _resolve_text(items: list, selected_ids: list[int]) -> list[str]:
    """Return .text values whose .id appears in selected_ids, in selection order."""
    by_id = {b.id: b.text for b in items}
    return [by_id[i] for i in selected_ids if i in by_id]


class LatexGenerator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.layout = ResumeLayoutConfig(section_order=config.section_order)

    _REPLACEMENTS = {
        "\\": "\\textbackslash{}",
        "&":  "\\&",
        "%":  "\\%",
        "$":  "\\$",
        "#":  "\\#",
        "^":  "\\textasciicircum{}",
        "_":  "\\_",
        "{":  "\\{",
        "}":  "\\}",
        "~":  "\\textasciitilde{}",
    }
    _ESCAPE_PATTERN = re.compile("|".join(re.escape(k) for k in _REPLACEMENTS))

    def _e(self, text: str) -> str:
        return self._ESCAPE_PATTERN.sub(lambda m: self._REPLACEMENTS[m.group()], text)

    def _github_link_tex(self, link: str, label: str) -> str:
        return r"\href{" + link + r"}{\large{\underline{" + self._e(label) + r"}}}"

    def convert_to_latex(
        self,
        corpus: AnnotatedCandidate,
        personal: UserProfile,
        resume_data: ResumeData,
        layout: ResumeLayoutConfig | None = None,
    ) -> str | None:
        template_path = Path(self.config.resume_template_tex)
        try:
            tex = template_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"Error reading resume template {template_path}: {e}")
            return None

        body = self._build_body(corpus, personal, resume_data, layout or self.layout)
        try:
            return _replace_marked_block(tex, "body", body, path=template_path)
        except ValueError as e:
            logger.error(f"Error creating LaTeX content: {e}")
            return None

    def _build_body(self, corpus: AnnotatedCandidate, personal: UserProfile, data: ResumeData, layout: ResumeLayoutConfig) -> str:
        parts: list[str] = [self._render_header(personal), self._render_ordered_sections(corpus, data, layout)]
        return "\n".join(p for p in parts if p)

    def _render_header(self, personal: UserProfile) -> str:
        p = personal
        lines: list[str] = [r"\begin{center}", r"    {\Huge \scshape " + self._e(p.name) + r"} \\ \vspace{1pt}"]

        if p.location:
            lines.append("    " + self._e(p.location) + r" \\ \vspace{1pt}")

        contact_bits: list[str] = []
        if p.phone:
            tel = _tel_href(p.phone)
            contact_bits.append(
                r"\href{tel:" + tel + r"}{ \raisebox{-0.1\height}\faPhone\ \underline{" + self._e(p.phone) + r"}}"
            )
        if p.email:
            contact_bits.append(
                r"\href{mailto:"
                + p.email
                + r"}{\raisebox{-0.2\height}\faEnvelope\  \underline{"
                + self._e(p.email)
                + r"}}"
            )
        if p.linkedin_url:
            label = p.linkedin_label or "LinkedIn"
            contact_bits.append(
                r"\href{"
                + p.linkedin_url
                + r"}{\raisebox{-0.2\height}\faLinkedinSquare\ \underline{"
                + self._e(label)
                + r"}}"
            )

        if contact_bits:
            lines.append(r"    \small " + r" ~ ".join(contact_bits) + r" ~")

        lines.extend([r"    \vspace{-8pt}", r"\end{center}", ""])
        return "\n".join(lines)

    def _render_ordered_sections(self, corpus: AnnotatedCandidate, data: ResumeData, layout: ResumeLayoutConfig) -> str:
        chunks: list[str] = []

        for section in layout.section_order:
            if section == "profile":
                chunks.append(self._render_profile(data.profile))
            elif section == "education":
                entries = _resolve(corpus.education, data.selected_education_ids)
                if entries:
                    chunks.append(self._render_education(entries))
            elif section == "experience":
                blocks = [(e, _resolve_text(e.bullet_points, se.bullet_ids))
                          for se in data.selected_experiences
                          for e in _resolve(corpus.experience, [se.experience_id])]
                blocks = [(e, b) for e, b in blocks if b]
                if blocks:
                    chunks.append(self._render_experience_blocks(blocks))
            elif section == "projects":
                blocks = [(p, _resolve_text(p.bullet_points, sp.bullet_ids))
                          for sp in data.selected_projects
                          for p in _resolve(corpus.projects, [sp.project_id])]
                blocks = [(p, b) for p, b in blocks if b]
                if blocks:
                    chunks.append(self._render_project_blocks(blocks))
            elif section == "skills":
                rows = [(cat.name, _resolve_text(cat.skills, sel.skill_ids))
                        for sel in data.selected_skills
                        for cat in _resolve(corpus.skills, [sel.category_id])]
                rows = [(name, names) for name, names in rows if names]
                if rows:
                    chunks.append(self._render_skill_section(rows))
            elif section == "certificates":
                certs = _resolve(corpus.certificates, data.selected_certificate_ids)
                if certs:
                    chunks.append(self._render_certificate_section(certs))

        return "\n".join(chunks)

    def _render_profile(self, profile: str) -> str:
        return (
            "%-----------PROFILE-----------\n"
            "\\section{PROFILE}\n"
            f"      {{{self._e(profile)}}}\n"
        )

    def _render_education(self, entries: list[AnnotatedEducationEntry]) -> str:
        lines = [
            "%-----------EDUCATION-----------",
            r"\section{EDUCATION}",
            r"\resumeSubHeadingListStart",
        ]
        for edu in entries:
            degree_text = edu.degree_line + (f" | GPA: {edu.gpa}" if edu.gpa else "")
            lines.append(
                r"    \ResumeEducationEntry{"
                + self._e(edu.institution) + "}{"
                + self._e(edu.start_date + " -- " + edu.end_date) + "}{"
                + self._e(degree_text) + "}{"
                + self._e(edu.location) + "}"
            )
        lines.append(r"\resumeSubHeadingListEnd")
        return "\n".join(lines) + "\n"

    def _render_project_blocks(self, blocks: list[tuple[AnnotatedProject, list[str]]]) -> str:
        lines = [
            "%-----------PROJECTS-----------",
            r"\section{PROJECTS}",
            r"\vspace{6pt}",
            r"\resumeSubHeadingListStart",
        ]
        for project, bullets in blocks:
            github_suffix = ""
            if project.github_links:
                parts = [
                    self._github_link_tex(link.url, link.name)
                    for link in project.github_links
                ]
                github_suffix = " $|$ " + " ".join(parts)

            title = r"\textbf{\large{" + self._e(project.name) + "}}"
            lines.append(
                r"      \ResumeProjectHeadingRow{"
                + title + github_suffix + "}{"
                + project.date + "}"
            )
            lines.append(r"          \resumeItemListStart")
            for bullet in bullets:
                lines.append(r"            \ResumeBulletItem{" + self._e(bullet) + "}")
            lines.append(r"          \resumeItemListEnd")

        lines.append(r"\resumeSubHeadingListEnd")
        return "\n".join(lines) + "\n"

    def _render_skill_section(self, rows: list[tuple[str, list[str]]]) -> str:
        lines = [
            "%-----------PROGRAMMING SKILLS-----------",
            r"\section{TECHNICAL SKILLS}",
            r" \begin{itemize}[leftmargin=0.15in, label={}]",
            r"    \small{\item{",
        ]
        for cat_name, skills in rows:
            skills_list = ", ".join(self._e(s) for s in skills)
            lines.append(
                r"\ResumeSkillCategoryRow{"
                + self._e(cat_name) + "}{"
                + skills_list + "}"
            )
        lines.extend([r"    }}", r" \end{itemize}"])
        return "\n".join(lines) + "\n"

    def _render_experience_blocks(self, blocks: list[tuple[AnnotatedExperience, list[str]]]) -> str:
        lines = [
            "%-----------EXPERIENCE-----------",
            r"\section{EXPERIENCE}",
            r"\resumeSubHeadingListStart",
        ]
        for exp, bullets in blocks:
            lines.append(
                r"    \ResumeJobHeading{"
                + self._e(exp.company_name) + "}{"
                + exp.start_date + " -- " + exp.end_date + "}{"
                + self._e(exp.job_title) + "}{"
                + self._e(exp.location) + "}"
            )
            lines.append(r"      \resumeItemListStart")
            for bullet in bullets:
                lines.append(r"        \ResumeBulletItem{" + self._e(bullet) + "}")
            lines.append(r"      \resumeItemListEnd")

        lines.append(r"\resumeSubHeadingListEnd")
        return "\n".join(lines) + "\n"

    def _render_certificate_section(self, certificates: list[AnnotatedCertificateEntry]) -> str:
        lines = [
            "%-----------CERTIFICATIONS-----------",
            r"\section{CERTIFICATIONS}",
            r"\resumeSubHeadingListStart",
        ]
        for c in certificates:
            sub = []
            if c.issuer:
                sub.append(self._e(c.issuer))
            if c.date:
                sub.append(self._e(c.date))
            mid = ", ".join(sub)
            lines.append(
                r"    \ResumeCertRow{"
                + self._e(c.name) + "}{"
                + (mid if mid else "") + "}"
            )
        lines.extend([r"\resumeSubHeadingListEnd", ""])
        return "\n".join(lines)