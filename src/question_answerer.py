import json

from ai_client import AIClient
from models import CandidateProfile, JobDescription, PersonalSummary, TextResponse, UserProfile


class QuestionAnswerer:
    """Class for answering interview questions from the candidate's perspective."""

    def __init__(self, ai: AIClient):
        self.ai = ai

    def answer_question(
        self,
        job_info: JobDescription,
        question: str,
        candidate: CandidateProfile,
        user_profile: UserProfile,
        personal_summary: PersonalSummary,
    ) -> str:
        summary = json.dumps(personal_summary.model_dump(), indent=2, ensure_ascii=False)
        system_prompt = self._build_system_prompt(summary, candidate.model_dump_json(indent=2), user_profile.name)
        return self.ai.run(system_prompt, self._build_user_message(job_info, question), TextResponse).text

    def _build_system_prompt(self, summary: str, candidate_json: str, name: str) -> str:
        return f"""You are answering open-ended job application questions on behalf of {name}. Answers will be submitted directly — write in first person.

Rules:
- Do not fabricate. Only use facts from the candidate data and personal context.
- If the data doesn't support a full answer, say what you can honestly — do not fill gaps with generic statements.
- If the question relates to the job description, connect {name}'s actual experience to what the role asks for.
- Write 1-3 sentences. Be direct and human — no filler, no corporate tone, no restating the question.

Respond with the answer text only.

## Candidate Data:
{candidate_json}

## Personal Context:
{summary}
"""

    def _build_user_message(self, job_info: JobDescription, question: str) -> str:
        return f"Job Posting Information:\n{job_info.model_dump_json(indent=2)}\n\nQuestion to answer:\n{question}"