import os
from openai import OpenAI

class AIClient:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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

        response = self.client.responses.parse(**kwargs)
        return response.output_parsed