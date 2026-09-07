"""Context-only writer selection preserves Connect and injected offline gateways."""
import hashlib
import json
import os
from types import SimpleNamespace
import zipfile

import pytest

from connected_gallery.adapters.proxy import ProxyGateway
from connected_gallery.adapters.store import Store, encoded
from connected_gallery.agent_runtime.runner import GraphAgentRunner
from connected_gallery.application.demo_profile import (
    apply_demo_model, effective_context_model, prepare_demo_profile, public_demo_marker,
)
from connected_gallery.application.service import RunService
from connected_gallery.domain.context import CONTEXT_WORDING_MODEL, context_wording_fields
from connected_gallery.domain.models import ExploreInput, PhotoAsset, RunRequest, SemanticAnchor
from test_contracts import store
from test_demo_profile_scripts import script
from test_demo_package import fixture as package_fixture, packager, prepare_fixture_connection


def context_value(store, source="a", member="b"):
    value = {"summary": "사진 속 모습을 비교할 수 있어요.", "complete": True,
             "groups": [{"id": "g", "title": "관계", "reason": "사진에서 확인한 근거", "photo_ids": [member]}]}
    value["evidence"] = {"gallery_revision": store.revision, "source_version": store.photo(source).version,
        "inspected_photo_ids": [source, member], "photo_versions": {p: store.photo(p).version for p in (source, member)},
        "reviewed_members": [{"group_id": "g", "photo_id": member}], "summary_reviewed": True,
        "planned_photo_ids": [member], "wording_review_model": CONTEXT_WORDING_MODEL, "wording_reviewed": True,
        "wording_checked_paths": [f["path"] for f in context_wording_fields(value)]}
    return value


def test_context_profile_preserves_connect_credentials_and_existing_marker_fields(tmp_path, monkeypatch):
    marker = tmp_path / "synthetic-demo.json"
    marker.write_text(json.dumps({"synthetic": True, "model": "claude-sonnet-5", "custom": "retain"}))
    monkeypatch.setenv("CG_MODEL", "other")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "stale")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "existing-fallback")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-fixture")
    assert prepare_demo_profile(tmp_path, context_model="gpt-5.4-mini") == "claude-sonnet-5"
    assert json.loads(marker.read_text()) == {"synthetic": True, "model": "claude-sonnet-5",
                                            "custom": "retain", "context_model": "gpt-5.4-mini"}
    assert os.environ["CG_MODEL"] == "claude-sonnet-5" and effective_context_model() == "gpt-5.4-mini"
    assert os.environ["CG_FALLBACK_MODEL"] == "existing-fallback" and os.environ["ANTHROPIC_API_KEY"] == "private-fixture"
    prepare_demo_profile(tmp_path, "next-connect-model")
    assert os.environ["CG_MODEL"] == "next-connect-model" and effective_context_model() == "gpt-5.4-mini"
    assert public_demo_marker(tmp_path) == {"synthetic": True, "source": "generated starter gallery",
                                          "model": "next-connect-model", "context_model": "gpt-5.4-mini"}


@pytest.mark.parametrize("bad", [None, "", " ", "bad model", "https://example.invalid", "../key", "a" * 129, 9])
def test_invalid_context_marker_is_rejected_before_environment_or_file_mutation(tmp_path, monkeypatch, bad):
    marker = tmp_path / "synthetic-demo.json"
    marker.write_text(json.dumps({"synthetic": True, "model": "valid-new-connect", "context_model": bad}))
    before = marker.read_bytes()
    monkeypatch.setenv("CG_MODEL", "existing-connect")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "existing-context")
    with pytest.raises(ValueError, match="public model name"):
        apply_demo_model(tmp_path)
    with pytest.raises(ValueError, match="public model name"):
        prepare_demo_profile(tmp_path)
    assert marker.read_bytes() == before
    assert os.environ["CG_MODEL"] == "existing-connect" and os.environ["CG_CONTEXT_MODEL"] == "existing-context"


@pytest.mark.parametrize("primary", ["next-connect-model", None])
def test_switching_to_a_marker_without_context_override_clears_previous_demo_override(tmp_path, monkeypatch, primary):
    monkeypatch.setenv("CG_MODEL", "current-connect-model")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "stale-context-model")
    marker = {"synthetic": True, **({"model": primary} if primary else {})}
    (tmp_path / "synthetic-demo.json").write_text(json.dumps(marker))
    apply_demo_model(tmp_path)
    assert "CG_CONTEXT_MODEL" not in os.environ
    assert effective_context_model() == (primary or "current-connect-model")


def test_override_selects_independent_context_key_without_invalidating_connect_or_old_context(store, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "claude-sonnet-5")
    monkeypatch.delenv("CG_CONTEXT_MODEL", raising=False)
    service = RunService(store, None)
    query = ExploreInput(anchor=SemanticAnchor(photo_id="a"))
    req = RunRequest(role="explorer", explore=query)
    result = {"label": "검토한 관계", "complete": True, "grouping_status": "ready",
              "items": [{"photo_id": "b", "reason": "확인한 관계"}],
              "groups": [{"id": "g", "title": "관계", "reason": "확인한 관계", "photo_ids": ["b"]}]}
    connect_key, old_context_key = service.cache_key(req), service.contexts.key("a")
    store.cache_put(connect_key, result)
    cached = service.contexts.cache_value("a", context_value(store))
    store.cache_put(old_context_key, cached)
    assert service.context_ready("a")["state"] == "ready"
    monkeypatch.setenv("CG_CONTEXT_MODEL", "gpt-5.4-mini")
    assert service.contexts.key("a") != old_context_key
    assert service.cache_key(req) == connect_key and service.ready(query)["state"] == "ready"
    assert service.context_ready("a")["state"] == "pending"
    assert store.cache_get(old_context_key) == cached
    store.cache_put(service.contexts.key("a"), cached)
    assert service.context_ready("a")["state"] == "ready"
    assert store.rows("SELECT count(*) AS n FROM cache")[0]["n"] == 3
    assert not store.rows("SELECT * FROM runs") and not store.rows("SELECT * FROM events")
    assert CONTEXT_WORDING_MODEL == "gpt-5.4-mini"


@pytest.mark.asyncio
@pytest.mark.parametrize("override,custom", [(True, False), (False, False), (True, True)])
async def test_context_only_replaces_production_gateway_and_keeps_attempt_timeout(store, monkeypatch, override, custom):
    monkeypatch.setenv("CG_MODEL", "connect-model")
    if override:
        monkeypatch.setenv("CG_CONTEXT_MODEL", "gpt-5.4-mini")
    else:
        monkeypatch.delenv("CG_CONTEXT_MODEL", raising=False)
    gateway = object() if custom else ProxyGateway(attempt_timeout=17, primary="connect-model", fallback="connect-fallback")
    used = []

    class ProbeAgent:
        def __init__(self, s, models, selected):
            used.append(selected)

        async def execute(self, *args):
            return {"probe": True}

    monkeypatch.setattr("connected_gallery.agent_runtime.context.PhotoContextAgent", ProbeAgent)
    runner = GraphAgentRunner(store, None, gateway)
    assert await runner.execute("probe", RunRequest(role="context", photo_ids=["a"])) == {"probe": True}
    assert runner.gateway is gateway and runner.explorer_gateway is gateway
    if override and not custom:
        assert used[0] is not gateway and type(used[0]) is ProxyGateway
        assert (used[0].primary, used[0].fallback, used[0].repeat_primary, used[0].attempt_timeout) == ("gpt-5.4-mini", None, False, 17)
        assert gateway.primary == "connect-model" and gateway.fallback == "connect-fallback"
    else:
        assert used == [gateway]


@pytest.mark.asyncio
async def test_explicit_context_agent_has_precedence_and_never_constructs_a_live_gateway(store, monkeypatch):
    monkeypatch.setenv("CG_CONTEXT_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr("connected_gallery.agent_runtime.context.PhotoContextAgent", lambda *args: pytest.fail("Explicit agent was replaced"))

    class ExplicitAgent:
        async def execute(self, rid, request):
            return {"run_id": rid}

    assert await GraphAgentRunner(store, None, object(), context_agent=ExplicitAgent()).execute(
        "explicit", RunRequest(role="context", photo_ids=["a"])) == {"run_id": "explicit"}


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    root = tmp_path / "source"
    monkeypatch.setenv("CG_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "gpt-5.4-mini")
    setup = Store(root)
    for pid in "ab":
        setup.upsert(PhotoAsset(id=pid, device_id="synthetic-demo", version="v1", width=40, height=30))
        region = {"id": "r" + pid, "photo_id": pid, "box": {"x": 0, "y": 0, "width": 1, "height": 1},
                  "kind": "object", "label": "관계", "evidence": "fixture"}
        setup.write("INSERT INTO analyses VALUES(?,?)", (pid, encoded({"photo_id": pid, "description": "fixture", "regions": [region]})))
        setup.image_path(pid).write_bytes(b"isolated synthetic image fixture")
    service = RunService(setup, None)
    keys = []
    for pid, member in zip("ab", "ba"):
        region = setup.analysis(pid)["regions"][0]
        query = ExploreInput(anchor=SemanticAnchor(photo_id=pid, region_id=region["id"], label=region["label"], kind="object", box=region["box"]))
        key = service.cache_key(RunRequest(role="explorer", explore=query))
        keys.append(key)
        setup.cache_put(key, {"label": "관계", "complete": True, "grouping_status": "ready",
                             "items": [{"photo_id": member, "reason": "확인한 관계"}],
                             "groups": [{"id": "g", "title": "관계", "reason": "확인한 관계", "photo_ids": [member]}]})
        setup.cache_put(service.contexts.key(pid), service.contexts.cache_value(pid, context_value(setup, pid, member)))
    setup.db.execute("PRAGMA journal_mode=DELETE")
    setup.close()
    (root / "synthetic-demo.json").write_text(json.dumps({"synthetic": True, "model": "claude-sonnet-5",
        "context_model": "gpt-5.4-mini", "private_fixture": "never-copy"}))
    return root, keys


def test_stage_and_readonly_audit_select_context_override_and_restore_caller_environment(synthetic, tmp_path, monkeypatch):
    root, connect_keys = synthetic
    monkeypatch.setenv("CG_MODEL", "caller-connect")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "caller-context")
    staging = script("stage-complete-demo.py")
    destination = tmp_path / "staged"
    report = staging.stage(SimpleNamespace(data_dir=root, stage_dir=destination, expected_photos=2, expected_regions=2))
    marker = json.loads((destination / "synthetic-demo.json").read_text())
    assert marker == {"synthetic": True, "source": "generated starter gallery", "model": "claude-sonnet-5", "context_model": "gpt-5.4-mini"}
    assert report["context_model"] == "gpt-5.4-mini" and report["validation"]["contexts"] == 2
    assert os.environ["CG_MODEL"] == "caller-connect" and os.environ["CG_CONTEXT_MODEL"] == "caller-context"
    audit = script("audit-complete-demo.py")
    accepted = audit.audit(SimpleNamespace(data_dir=destination, report=tmp_path / "audit.json", fixture=None, manifest=None,
        expected_photos=2, expected_regions=2, minimum_route_starts=0, probe_photo_id=None, probe_region_id=None,
        require_context_beyond_connect=False))
    assert accepted["all_preparation_complete"] and accepted["contexts"]["prepared"] == 2
    assert accepted["cache_model"] == "claude-sonnet-5" and accepted["context_model"] == "gpt-5.4-mini"
    assert accepted["read_only_verified"] and accepted["execution_attempts"] == 0
    assert os.environ["CG_MODEL"] == "caller-connect" and os.environ["CG_CONTEXT_MODEL"] == "caller-context"


def test_package_preserves_only_validated_public_context_profile(package_fixture):
    marker = package_fixture.data_dir / "synthetic-demo.json"
    marker.write_text(json.dumps({"synthetic": True, "model": "claude-sonnet-5", "context_model": "gpt-5.4-mini", "secret": "never-copy"}))
    prepare_fixture_connection(package_fixture)
    report = packager.package(package_fixture)
    assert report["model"] == "claude-sonnet-5" and report["context_model"] == "gpt-5.4-mini"
    with zipfile.ZipFile(package_fixture.output_dir / "connected-gallery-ready-data.zip") as archive:
        public = json.loads(archive.read(".runtime/demo/synthetic-demo.json"))
    assert public == {"synthetic": True, "source": "generated starter gallery", "model": "claude-sonnet-5", "context_model": "gpt-5.4-mini"}


@pytest.mark.asyncio
@pytest.mark.parametrize("flags,expected_connect,expected_context", [
    (["--context-model", "gpt-5.4-mini"], "claude-sonnet-5", "gpt-5.4-mini"),
    (["--model", "new-connect-model"], "new-connect-model", "new-connect-model"),
])
async def test_prepare_context_cli_reports_actual_writer_and_preserves_model_flag(synthetic, tmp_path, monkeypatch, flags, expected_connect, expected_context):
    root, _ = synthetic
    (root / "synthetic-demo.json").write_text('{"synthetic":true,"model":"claude-sonnet-5"}')
    setup = Store(root)
    setup.write("DELETE FROM cache WHERE json_extract(data,'$.kind')='photo_context'")
    setup.close()
    for name in ("CG_AUTO_ORGANIZE", "CG_ANALYSIS_CONCURRENCY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, os.getenv(name, ""))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-fixture-key")
    monkeypatch.setattr("connected_gallery.adapters.models.LocalModels", lambda *args: None)

    class NoModelRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, rid, req):
            return {"summary": "불완전한 fixture", "groups": [], "complete": False}

    monkeypatch.setattr("connected_gallery.agent_runtime.runner.GraphAgentRunner", NoModelRunner)
    prepare = script("prepare-contexts.py")
    args = prepare.parser().parse_args(["--data-dir", str(root), "--photo-id", "a", *flags])
    assert await prepare.main(args) == 2
    report = json.loads((root / "context-preparation-report.json").read_text())
    assert report["model"] == report["context_model"] == expected_context
    assert report["connection_model"] == expected_connect and report["wording_review_model"] == CONTEXT_WORDING_MODEL
    assert report["attempts"][-1]["context_model"] == expected_context
    assert report["attempts"][-1]["connection_model"] == expected_connect
    assert os.environ["CG_MODEL"] == expected_connect and effective_context_model() == expected_context
