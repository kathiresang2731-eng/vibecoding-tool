from openai import OpenAI


class OpenAILLM:

    def __init__(
        self,
        api_key="123",
        model_name="worktual-gemma",
        base_url="http://173.234.75.166:8011/v1",
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    def run(self, messages, tools=None, tool_choice=None):
        tools = tools or []
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.1,
            "presence_penalty": 0.0,
            "stream": False,
            "extra_body": {
                "top_k": 64,
                "top_p": 0.95,
                "repetition_penalty": 1.05,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        }

        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        resp = self.client.chat.completions.create(**kwargs).model_dump()

        message = resp["choices"][0]["message"]
        result = {
            "content": message.get("content"),
            "tool_calls": message.get("tool_calls"),
            "reasoning": message.get("reasoning"),
        }
        print(result)
        return result
