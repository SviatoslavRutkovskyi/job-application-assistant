import io
import logging

from pydantic import BaseModel

from infrastructure.ai_client import AIClient
from models import CandidateProfile, UserProfile

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


class ExtractedResume(BaseModel):
    """Combined extraction target for a single AI call."""
    personal: UserProfile
    candidate: CandidateProfile


_SYSTEM_PROMPT = """\
You are a resume parser. Extract structured information from the provided resume text.

Rules:
- Only extract information explicitly present in the resume. Do not invent or infer anything.
- For dates use the format "Mon YYYY" (e.g. "Jan 2023"). Use "Present" for current roles.
- profile: a concise 2–3 sentence professional summary. If none exists in the resume, write one from the content.
- bullet_points: copy them as-is from the resume, one per item.
- skills: group into logical categories (e.g. "Languages", "Frameworks", "Tools").
- linkedin_label: the display text for the LinkedIn link (e.g. "linkedin.com/in/username"). If only a URL is present, derive the label from it.
- Return empty lists for sections not present in the resume. Never hallucinate employers, dates, or credentials.
"""


class ResumeExtractor:
    def __init__(self, ai: AIClient):
        self.ai = ai

    def extract_text_from_pdf(self, file_bytes: bytes) -> str:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
        if not text:
            raise ValueError(
                "Could not extract text from this PDF. It may be scanned or image-based. "
                "Try uploading a DOCX or TXT version instead."
            )
        return text

    def extract_text_from_docx(self, file_bytes: bytes) -> str:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs).strip()
        if not text:
            raise ValueError("Could not extract text from this DOCX file.")
        return text

    def extract_text(self, file_bytes: bytes, filename: str) -> str:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == ".pdf":
            return self.extract_text_from_pdf(file_bytes)
        elif ext == ".docx":
            return self.extract_text_from_docx(file_bytes)
        elif ext == ".txt":
            return file_bytes.decode("utf-8", errors="replace").strip()
        else:
            raise ValueError(f"Unsupported file type '{ext}'. Upload a PDF, DOCX, or TXT file.")

    def parse(self, resume_text: str) -> ExtractedResume:
        logger.info("Extracting resume data via AI (text length: %d chars)", len(resume_text))
        return self.ai.run(_SYSTEM_PROMPT, f"Resume text:\n\n{resume_text}", ExtractedResume)
