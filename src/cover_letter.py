import logging
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from ai_client import AIClient
from models import AppConfig, CandidateProfile, Evaluation, JobDescription, TextResponse, UserProfile
from utils import load_json_model

logger = logging.getLogger(__name__)


class CoverLetter:
    def __init__(
        self,
        config: AppConfig,
        ai: AIClient,
        eval_limit: int,
        include_feedback: bool,
    ):
        self.config = config
        self.ai = ai
        self.eval_limit = eval_limit
        self.include_feedback = include_feedback

        with open(self.config.cover_letter_template, encoding="utf-8") as f:
            self.cover_letter_template = f.read()

        candidate_data = load_json_model(self.config.candidate_json, CandidateProfile, "candidate")
        user_profile = load_json_model(self.config.personal_json, UserProfile, "personal")
        candidate_json = candidate_data.model_dump_json(indent=2)
        name = user_profile.name

        self.system_prompt = f"""
You are a professional cover letter writer writing on behalf of {name}.

You are given {name}'s resume data and a job description.

- Select the most relevant projects and experiences for this specific role
- Use only information from the candidate data — do not fabricate metrics, percentages, or figures not present in the data
- Respond with cover letter text only — no preamble or commentary
- Write between 200 and 300 words

If given a rejected cover letter and feedback, treat each criticism as a specific failure mode to fix, not a suggestion to acknowledge.

## Candidate Data:
{candidate_json}
"""

        self.evaluator_system_prompt = f"""
You are a professional hiring manager evaluating a cover letter for submission.
Your job is to determine whether the cover letter is ready to send based on five dimensions.

You are provided with:
- The candidate's resume data
- The job description
- The cover letter to evaluate

Opening (0–20 pts): The opening connects the candidate's background to this specific role. A strong opening references something concrete from the candidate's experience and ties it to the role or company. A weak opening is purely generic and could have been written by any applicant.

Depth & Framing (0–25 pts): The letter explains why projects were built, what problem was being solved, and how technical decisions affected the user or end customer. It adds perspective the resume cannot. A strong body shows how the candidate thinks, not just what they built. A weak body lists technologies and actions without explaining purpose or impact.

Role Fit (0–25 pts): The letter directly engages with the specific angle of this role using only the candidate's actual experience. Evaluate how well the candidate connects what they have built to what this role requires. Do not penalize for skills or experience absent from the candidate data — only evaluate the strength of the connections that are made.

Company Specificity (0–20 pts): The closing demonstrates genuine understanding of what this company does and connects it to something the candidate has built. If the job description provides limited company or technical context, evaluate whether the candidate makes a reasonable connection to what is available. Do not penalize for specificity that the job description itself cannot support.

Clarity & Professionalism (0–10 pts): The letter is clean, concise, and free of errors. No unfilled placeholders. Uses only information present in the candidate data.

Before scoring, verify every outcome or result claim in the letter against the candidate data:
1. Identify each claim of outcome, impact, or result in the letter
2. Find the corresponding project or experience in the candidate data
3. If the claim cannot be traced directly to the candidate data, it is fabrication — quote what the candidate data actually says about that project and include it in your feedback so the generator can use accurate information instead
Mark acceptable: false if any fabrication is found.

Scoring rules:
- If the letter has clear fixable weaknesses, provide direct feedback of 2-4 sentences ordered by impact and mark acceptable: false
- Otherwise mark acceptable: true
- Do not suggest skills or experience not present in the candidate data
- Do not suggest adding metrics, percentages, or quantified results not present in the candidate data. If no metrics exist, evaluate whether the candidate explains the reasoning behind technical decisions
- If the job description provides insufficient context to identify a specific technical challenge, do not require company-specific technical connections in the closing. A reasonable connection to the company's stated focus is sufficient

## Candidate Data:
{candidate_json}
"""

    def evaluate(self, job_info: JobDescription, cover_letter: str) -> Evaluation:
        return self.ai.run(
            self.evaluator_system_prompt,
            f"Job Description:\n{job_info.model_dump_json(indent=2)}\n\nCover Letter:\n{cover_letter}",
            Evaluation,
        )

    def request_letter(self, job_info: JobDescription):
        logger.info("Requesting cover letter")
        logger.info(f"Job: {job_info.job_title or 'N/A'} at {job_info.company_name or 'N/A'}")

        job_section = "## Job Posting\n" + job_info.model_dump_json(indent=2)
        current_message = "\n\n".join([
            job_section,
            "## Cover Letter Template (Use as starting point. Replace all bracketed placeholders with actual content from the candidate data and job description)\n"
            + self.cover_letter_template,
        ])

        max_score = -1
        best_cover_letter = None
        best_feedback = ""

        for i in range(self.eval_limit):
            cover_letter = self.ai.run(self.system_prompt, current_message, TextResponse).text
            evaluation = self.evaluate(job_info, cover_letter)

            logger.info(f"[attempt {i + 1}/{self.eval_limit}] score: {evaluation.score} — {'passed' if evaluation.is_acceptable else 'retrying'}")
            logger.info(f"    cover letter: {cover_letter}")
            logger.info(f"    feedback: {evaluation.feedback}")

            if evaluation.score > max_score:
                max_score = evaluation.score
                best_cover_letter = cover_letter
                best_feedback = evaluation.feedback

            if evaluation.is_acceptable:
                if self.include_feedback:
                    return cover_letter + "\n\n\n" + evaluation.feedback
                return cover_letter

            current_message = "\n\n".join([
                job_section,
                "## Previous Attempt (rejected)\n" + cover_letter,
                "## Feedback\n" + evaluation.feedback,
            ])

        logger.warning(f"Eval limit reached — returning best attempt (score: {max_score})")
        logger.warning(f"    feedback: {best_feedback}")
        return best_cover_letter

    def convert_cover_letter_to_pdf(self, cover_letter_text: str):
        if not cover_letter_text or not cover_letter_text.strip():
            logger.warning("No cover letter text provided for PDF conversion")
            return None

        try:
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer, pagesize=letter,
                rightMargin=72, leftMargin=72,
                topMargin=72, bottomMargin=72,
            )

            styles = getSampleStyleSheet()
            normal_style = styles["Normal"]
            normal_style.fontSize = 11
            normal_style.leading = 14
            normal_style.spaceAfter = 12

            story = []
            for para in cover_letter_text.split("\n\n"):
                if not para.strip():
                    continue
                for line in para.split("\n"):
                    if line.strip():
                        story.append(Paragraph(line.strip(), normal_style))
                story.append(Spacer(1, 12))

            doc.build(story)
            logger.info("Cover letter PDF created")
            return buffer.getvalue()

        except Exception as e:
            logger.error(f"Error creating cover letter PDF: {e}")
            return None