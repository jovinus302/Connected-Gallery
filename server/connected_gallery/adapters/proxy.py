import os
import asyncio
from langchain_anthropic import ChatAnthropic

_DEFAULT_FALLBACK = object()


class ProxyGateway:
    def __init__(self, attempt_timeout=30, repeat_primary=True, *, primary=None, fallback=_DEFAULT_FALLBACK):
        self.primary = primary if primary is not None else os.getenv("CG_MODEL", "gpt-5.4-mini")
        self.fallback = os.getenv("CG_FALLBACK_MODEL", "claude-sonnet-5") if fallback is _DEFAULT_FALLBACK else fallback
        self.attempt_timeout = attempt_timeout
        self.repeat_primary = repeat_primary

    async def invoke(self, messages, tool_schemas):
        last = None
        names = [self.primary] * (2 if self.repeat_primary else 1)
        if self.fallback is not None:
            names.append(self.fallback)
        for name in names:
            try:
                model = ChatAnthropic(
                    model=name,
                    api_key=os.environ["ANTHROPIC_API_KEY"],
                    base_url=os.environ["ANTHROPIC_BASE_URL"],
                    max_tokens=4096,
                    timeout=self.attempt_timeout,
                    max_retries=0,
                )
                options = {}
                if len(tool_schemas) == 1 and tool_schemas[0]["name"].startswith("submit_"):
                    options["tool_choice"] = tool_schemas[0]["name"]
                # SDK transport timeouts apply to individual I/O operations.
                # Also bound the complete attempt so retries cannot silently
                # consume the whole exploration budget before fallback starts.
                return await asyncio.wait_for(
                    model.bind_tools(tool_schemas, **options).ainvoke(messages),
                    timeout=self.attempt_timeout,
                )
            except Exception as exc:
                last = type(exc).__name__
        # Do not persist provider error bodies: they can include request images or credentials.
        raise RuntimeError(f"Model unavailable ({last})")
