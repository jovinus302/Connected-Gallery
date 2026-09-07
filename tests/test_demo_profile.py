import asyncio
import importlib.util
import json
import os
from pathlib import Path

import pytest

from connected_gallery.application.demo_profile import apply_demo_model, prepare_demo_profile, read_demo_model, validate_demo_model
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor
from test_contracts import store

spec = importlib.util.spec_from_file_location("demo_preparation", Path(__file__).resolve().parents[1] / "scripts" / "prepare-demo.py")
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


@pytest.mark.parametrize("value", [None, "", " ", "model name", "model\n", "https://example.invalid/model", "../model", "a" * 129, 7])
def test_invalid_public_model_is_rejected(value):
    with pytest.raises(ValueError, match="public model name"):
        validate_demo_model(value)


def test_profile_preserves_marker_and_changes_only_model_environment(tmp_path, monkeypatch):
    marker = tmp_path / "synthetic-demo.json"
    marker.write_text(json.dumps({"synthetic": True, "source": "existing", "custom": {"retain": True}}))
    monkeypatch.setenv("CG_MODEL", "old-model")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "existing-fallback")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-private-key")
    assert prepare_demo_profile(tmp_path, "claude-sonnet-5") == "claude-sonnet-5"
    assert json.loads(marker.read_text()) == {"synthetic": True, "source": "existing", "custom": {"retain": True}, "model": "claude-sonnet-5"}
    assert os.environ["CG_MODEL"] == "claude-sonnet-5"
    assert os.environ["CG_FALLBACK_MODEL"] == "existing-fallback"
    assert os.environ["ANTHROPIC_API_KEY"] == "test-private-key"
    assert "test-private-key" not in marker.read_text()
    assert prepare_demo_profile(tmp_path) == "claude-sonnet-5"


def test_no_model_marker_remains_backward_compatible(tmp_path, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "existing-model")
    assert apply_demo_model(tmp_path) is None
    (tmp_path / "synthetic-demo.json").write_text('{"synthetic":true}')
    assert apply_demo_model(tmp_path) is None
    assert os.environ["CG_MODEL"] == "existing-model"


def test_invalid_profile_is_rejected_before_mutation(tmp_path, monkeypatch):
    marker = tmp_path / "synthetic-demo.json"
    marker.write_text('{"synthetic":true,"model":"bad model"}')
    before = marker.read_bytes()
    monkeypatch.setenv("CG_MODEL", "original-model")
    with pytest.raises(ValueError):
        apply_demo_model(tmp_path)
    with pytest.raises(ValueError):
        prepare_demo_profile(tmp_path)
    assert marker.read_bytes() == before and os.environ["CG_MODEL"] == "original-model"


def test_profile_selects_matching_cache_without_model_execution(store, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "claude-sonnet-5")
    service = RunService(store, None)
    explore = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    request = RunRequest(role="explorer", explore=explore)
    result = {"label": "prepared", "items": [], "complete": True, "groups": [], "grouping_status": "ready"}
    selected_key = service.cache_key(request)
    store.cache_put(selected_key, result)
    monkeypatch.delenv("CG_MODEL")
    assert service.cache_key(request) != selected_key and service.ready(explore)["state"] == "pending"
    (store.root / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5"}')
    before = {table: store.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] for table in ("cache", "runs", "events")}
    apply_demo_model(store.root)
    assert service.ready(explore)["result"] == result
    assert before == {table: store.rows(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] for table in before}


@pytest.mark.asyncio
@pytest.mark.parametrize("workers", [1, 2])
async def test_preparation_starts_only_bounded_jobs_and_processes_all(workers):
    consumed, active, peak = [], 0, 0
    entered, release = asyncio.Event(), asyncio.Event()

    def items():
        for index in range(6):
            consumed.append(index)
            yield index

    async def run_one(item):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == workers:
            entered.set()
        try:
            await release.wait()
            await asyncio.sleep(.01)
            return item
        finally:
            active -= 1

    async def consume():
        return [value async for value in preparation.bounded_prepare(items(), run_one, workers)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 1)
    assert consumed == list(range(workers)) and active == workers
    release.set()
    assert sorted(await task) == list(range(6))
    assert peak == workers and active == 0


@pytest.mark.asyncio
async def test_closed_preparation_iterator_cancels_pending_jobs():
    active = set()

    async def run_one(item):
        active.add(item)
        try:
            await asyncio.sleep(.01 if item == 0 else 60)
            return item
        finally:
            active.remove(item)

    iterator = preparation.bounded_prepare(range(5), run_one, 2)
    assert await anext(iterator) == 0 and active == {1}
    await iterator.aclose()
    assert active == set()
