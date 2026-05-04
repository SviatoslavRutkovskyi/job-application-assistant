import logging
import os
import time
from openai import APIConnectionError, OpenAIError, RateLimitError
from openai import OpenAI

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 2  # seconds


class AIClient:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("AI_MODEL", "gpt-4.1-mini")
        self.reasoning = os.getenv("AI_REASONING_MODEL", "o4-mini")

    def run(self, system_prompt, user_message, schema, reasoning=False, reasoning_effort="low"):
        kwargs = dict(
            model=self.reasoning if reasoning else self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            text_format=schema,
        )
        if reasoning:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        for attempt in range(_MAX_RETRIES):
            try:
                response = self.client.responses.parse(**kwargs)
                return response.output_parsed
            except (RateLimitError, APIConnectionError) as e:
                if attempt == _MAX_RETRIES - 1:
                    raise ValueError(f"OpenAI transient error after {_MAX_RETRIES} attempts: {e}") from e
                wait = _BASE_DELAY * (2 ** attempt)
                logger.warning(f"OpenAI transient error — retrying in {wait}s (attempt {attempt + 1}/{_MAX_RETRIES}): {e}")
                time.sleep(wait)
            except OpenAIError as e:
                # Not retried — these are request errors (bad schema, invalid model, etc.)
                raise ValueError(f"OpenAI API error: {e}") from e