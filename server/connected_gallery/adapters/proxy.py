import os
from langchain_anthropic import ChatAnthropic


class ProxyGateway:
    def __init__(self):
        self.primary = os.getenv("CG_MODEL", "gpt-5.4-mini")
        self.fallback = os.getenv("CG_FALLBACK_MODEL", "claude-sonnet-5")

    async def invoke(self, messages, tool_schemas):
        last = None
        for name in (self.primary, self.primary, self.fallback):
            try:
                model = ChatAnthropic(
                    model=name,
                    api_key=os.environ["ANTHROPIC_API_KEY"],
                    base_url=os.environ["ANTHROPIC_BASE_URL"],
                    max_tokens=4096,
                    timeout=30,
                    max_retries=0,
                )
                options = {}
                if len(tool_schemas) == 1 and tool_schemas[0]["name"].startswith("submit_"):
                    options["tool_choice"] = tool_schemas[0]["name"]
                return await model.bind_tools(tool_schemas, **options).ainvoke(messages)
            except Exception as exc:
                last = type(exc).__name__
        # Do not persist provider error bodies: they can include request images or credentials.
        raise RuntimeError(f"Model unavailable ({last})")
