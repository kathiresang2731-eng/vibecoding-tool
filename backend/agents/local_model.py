import os

from openai import OpenAI

from .budget_config import AGENT_BUDGETS


DEFAULT_LOCAL_MODEL_NAME = "gpt-oss-120b"
DEFAULT_LOCAL_MODEL_BASE_URL = "http://173.234.75.166:8003/v1"


def env_value(name, fallback=""):
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) and value.strip() else fallback


class OpenAILLM____:

    def __init__(self, api_key="", model_name="", base_url=""):
        api_key = api_key or env_value("LOCAL_MODEL_API_KEY") or env_value("GPT_LOCAL_MODEL_API_KEY")
        model_name = model_name or env_value("LOCAL_MODEL_NAME") or env_value("GPT_LOCAL_MODEL_NAME") or DEFAULT_LOCAL_MODEL_NAME
        base_url = base_url or env_value("LOCAL_MODEL_BASE_URL") or env_value("LOCAL_MODEL_ENDPOINT") or env_value("GPT_LOCAL_MODEL_ENDPOINT") or DEFAULT_LOCAL_MODEL_BASE_URL
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model_name = model_name

    def run(self, messages, tools, reasoning_effort='low'):
        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            max_tokens=AGENT_BUDGETS.local_model_output_tokens,
            temperature=0.7,
            stream=False,
            reasoning_effort=reasoning_effort,
            tools=tools
        ).model_dump()

        return {
            "content": resp["choices"][0]["message"].get("content"),
            "tool_calls": resp["choices"][0]["message"].get("tool_calls"),
            "reasoning": resp["choices"][0]["message"].get("reasoning")
        }
