import asyncio

import pytest

from connected_gallery.adapters.proxy import ProxyGateway


@pytest.mark.asyncio
async def test_interactive_attempt_has_wall_clock_limit_and_uses_fallback_once(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CG_MODEL", "primary")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "fallback")
    names, cancelled = [], []

    class Model:
        def __init__(self, **kwargs):
            self.name = kwargs["model"]
            names.append(self.name)

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            if self.name == "primary":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(self.name)
            return "fallback result"

    monkeypatch.setattr("connected_gallery.adapters.proxy.ChatAnthropic", Model)
    gateway = ProxyGateway(attempt_timeout=.02, repeat_primary=False)
    assert await gateway.invoke([], []) == "fallback result"
    assert names == ["primary", "fallback"]
    assert cancelled == ["primary"]


@pytest.mark.asyncio
async def test_cancellation_does_not_start_a_fallback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    names = []
    entered = asyncio.Event()

    class Model:
        def __init__(self, **kwargs):
            names.append(kwargs["model"])

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr("connected_gallery.adapters.proxy.ChatAnthropic", Model)
    task = asyncio.create_task(ProxyGateway(repeat_primary=False).invoke([], []))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(names) == 1


@pytest.mark.asyncio
async def test_explicit_model_with_no_fallback_makes_exactly_one_attempt(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CG_MODEL", "original-primary")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "original-fallback")
    names = []

    class FailingModel:
        def __init__(self, **kwargs):
            names.append(kwargs["model"])
            assert kwargs["max_retries"] == 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            raise ValueError("Provider body must not be exposed")

    monkeypatch.setattr("connected_gallery.adapters.proxy.ChatAnthropic", FailingModel)
    gateway = ProxyGateway(primary="gpt-5.4-mini", fallback=None, repeat_primary=False)
    with pytest.raises(RuntimeError, match=r"^Model unavailable \(ValueError\)$"):
        await gateway.invoke([], [])
    assert names == ["gpt-5.4-mini"]


@pytest.mark.asyncio
async def test_default_proxy_preserves_primary_repeat_then_configured_fallback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CG_MODEL", "primary")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "fallback")
    names = []

    class Model:
        def __init__(self, **kwargs):
            self.name = kwargs["model"]
            names.append(self.name)

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            if self.name == "primary":
                raise TimeoutError()
            return "done"

    monkeypatch.setattr("connected_gallery.adapters.proxy.ChatAnthropic", Model)
    assert await ProxyGateway().invoke([], []) == "done"
    assert names == ["primary", "primary", "fallback"]
