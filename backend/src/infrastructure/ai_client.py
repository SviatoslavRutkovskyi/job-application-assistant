import os
from openai import APIConnectionError, OpenAIError, RateLimitError
from openai import OpenAI


class AIClient:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("AI_MODEL", "gpt-4.1-mini")
        self.reasoning = os.getenv("AI_REASONING_MODEL", "o4-mini")

    def run(self, system_prompt, user_message, schema, reasoning=False, reasoning_effort="low"):
        try:
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

            response = self.client.responses.parse(**kwargs)
            return response.output_parsed
        except RateLimitError as e:
            raise ValueError(f"OpenAI rate limit exceeded: {e}") from e
        except APIConnectionError as e:
            raise ValueError(f"Could not connect to OpenAI: {e}") from e
        except OpenAIError as e:
            raise ValueError(f"OpenAI API error: {e}") from e