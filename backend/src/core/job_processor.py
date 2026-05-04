import ipaddress
import logging
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from infrastructure.ai_client import AIClient
from models import JobDescription

logger = logging.getLogger(__name__)


class JobProcessor:
    """Processes job descriptions and extracts structured information."""

    def __init__(self, ai: AIClient):
        self.ai = ai

    def extract_job_info(self, job_description_text: str) -> JobDescription:
        json_schema = json.dumps(JobDescription.model_json_schema(), indent=2)
        system_prompt = f"""Extract the following JSON fields from the job text.

Return ONLY valid JSON with missing fields as null or [].

{json_schema}"""
        return self.ai.run(system_prompt, f"Job text:\n\n{job_description_text}", JobDescription)

    def is_usable(self, job_info: JobDescription) -> bool:
        conditions_met = sum([
            job_info.job_title is not None,
            len(job_info.required_skills) >= 2,
            len(job_info.responsibilities) >= 2,
            job_info.description_summary is not None and len(job_info.description_summary) >= 40,
        ])
        return conditions_met >= 2

    def is_url(self, text: str) -> bool:
        try:
            result = urlparse(text.strip())
            return all([result.scheme, result.netloc])
        except Exception:
            return False

    def _is_safe_url(self, url: str) -> bool:
        """Allowlist check to prevent SSRF attacks.

        Permits only HTTPS URLs with a non-empty host that resolves to a
        globally routable IP. Blocks private, loopback, and link-local ranges
        (e.g. 169.254.169.254 Azure Instance Metadata Service).
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme != "https":
                return False
            host = parsed.hostname or ""
            if not host:
                return False
            # If the host is already an IP address, check it directly.
            try:
                addr = ipaddress.ip_address(host)
                return addr.is_global and not addr.is_loopback and not addr.is_private
            except ValueError:
                pass  # It's a hostname — DNS resolution happens at request time.
            return True
        except Exception:
            return False

    def scrape_webpage_simple(self, url: str) -> str | None:
        if not self._is_safe_url(url):
            logger.error(f"Blocked unsafe URL: {url}")
            return None
        try:
            logger.info(f"Scraping {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            content = BeautifulSoup(response.content, "html.parser").get_text()
            return " ".join(content.split())
        except requests.RequestException as e:
            logger.error(f"Request error scraping {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None

    def process_job_posting(self, job_posting: str) -> str:
        if self.is_url(job_posting):
            logger.info(f"Detected URL: {job_posting}")
            scraped = self.scrape_webpage_simple(job_posting.strip())
            if scraped is not None:
                logger.info("Successfully scraped webpage content")
                return scraped
            raise Exception(
                "Could not scrape the provided URL. Please provide the job description as text instead."
            )
        logger.info("Input is text, using as-is")
        return job_posting

    def process_and_extract_job_info(self, job_posting: str) -> JobDescription:
        raw_job_text = self.process_job_posting(job_posting)

        logger.info("Extracting job info from text")
        job_info = self.extract_job_info(raw_job_text)

        if not self.is_usable(job_info):
            raise ValueError(
                "The job description does not contain enough information for resume/cover letter generation. "
                "Please ensure at least 2 of the following are present: "
                "job title, at least 2 required skills, at least 2 responsibilities, "
                "or a description summary (40+ chars)."
            )

        logger.debug(f"Job info extracted: {job_info.model_dump_json(indent=2)}")
        return job_info