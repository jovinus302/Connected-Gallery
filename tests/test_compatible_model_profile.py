"""Explicit old model namespaces preserve verified rows; no live runtime or model."""
from contextlib import closing
import json
import os
import sqlite3
from types import SimpleNamespace
import zipfile

import pytest

from connected_gallery.application.demo_profile import (
    apply_demo_model, connection_models, normalize_compatible_connection_models,
    prepare_demo_profile, public_demo_marker, read_demo_models,
)
from test_context_model_profile import synthetic
from test_demo_package import fixture as package_fixture, packager, prepare_fixture_connection
from test_demo_profile_scripts import script


@pytest.fixture(autouse=True)
def restore_environment(monkeypatch):
    for name in ("CG_MODEL", "CG_CONTEXT_MODEL", "CG_COMPATIBLE_CONNECTION_MODELS", "CG_AUTO_ORGANIZE",
                 "CG_ANALYSIS_CONCURRENCY", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        if name in os.environ:
            monkeypatch.setenv(name, os.environ[name])
        else:
            monkeypatch.delenv(name, raising=False)


def marker(root, **fields):
    path = root / "synthetic-demo.json"
    path.write_text(json.dumps({"synthetic": True, **fields}), encoding="utf-8")
    return path


def test_read_apply_and_public_copy_normalize_without_rewriting_source(tmp_path, monkeypatch):
    path = marker(tmp_path, model="gpt-5.4", context_model="context-model", secret="private-marker",
                  compatible_connection_models=["claude-sonnet-5", "gpt-5.4", "claude-sonnet-5", "older"])
    before = path.read_bytes()
    monkeypatch.setenv("CG_FALLBACK_MODEL", "provider-fallback")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-fixture")
    assert read_demo_models(tmp_path)["compatible_connection_models"] == ["claude-sonnet-5", "older"]
    assert apply_demo_model(tmp_path) == "gpt-5.4"
    assert connection_models() == ["gpt-5.4", "claude-sonnet-5", "older"]
    assert connection_models("older") == ["older", "claude-sonnet-5"]
    assert os.environ["CG_CONTEXT_MODEL"] == "context-model"
    assert os.environ["CG_FALLBACK_MODEL"] == "provider-fallback"
    assert os.environ["ANTHROPIC_API_KEY"] == "private-fixture"
    assert path.read_bytes() == before
    assert public_demo_marker(tmp_path) == {
        "synthetic": True, "source": "generated starter gallery", "model": "gpt-5.4",
        "context_model": "context-model", "compatible_connection_models": ["claude-sonnet-5", "older"]}


@pytest.mark.parametrize("bad", [None, "claude-sonnet-5", {}, 9, True, [None], [""], ["bad model"],
                                       ["https://private.invalid"], ["a" * 129], ["a", "b", "c", "d", "e"]])
def test_invalid_compatibility_marker_rejected_before_any_mutation(tmp_path, monkeypatch, bad):
    path = marker(tmp_path, model="gpt-5.4", context_model="new-context", compatible_connection_models=bad)
    before = path.read_bytes()
    monkeypatch.setenv("CG_MODEL", "current")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "current-context")
    monkeypatch.setenv("CG_COMPATIBLE_CONNECTION_MODELS", '["current-old"]')
    for action in (read_demo_models, apply_demo_model, prepare_demo_profile, public_demo_marker):
        with pytest.raises(ValueError):
            action(tmp_path)
    assert path.read_bytes() == before
    assert os.environ["CG_MODEL"] == "current" and os.environ["CG_CONTEXT_MODEL"] == "current-context"
    assert connection_models() == ["current", "current-old"]


def test_limit_applies_after_primary_and_duplicate_normalization():
    assert normalize_compatible_connection_models(["p", "a", "a", "b", "c", "d", "p"], primary="p") == ["a", "b", "c", "d"]
    with pytest.raises(ValueError):
        normalize_compatible_connection_models(("a",))


def test_preparation_preserves_old_profile_and_normalizes_new_primary_atomically(tmp_path):
    path = marker(tmp_path, model="old-primary", context_model="context", custom="keep",
                  compatible_connection_models=["gpt-5.4", "oldest"])
    prepare_demo_profile(tmp_path, "gpt-5.4")
    assert json.loads(path.read_text())["compatible_connection_models"] == ["oldest"]
    assert json.loads(path.read_text())["custom"] == "keep"
    assert not path.with_suffix(".tmp").exists()
    prepare_demo_profile(tmp_path, compatible_connection_models=["claude-sonnet-5", "gpt-5.4", "claude-sonnet-5"])
    assert connection_models() == ["gpt-5.4", "claude-sonnet-5"]
    prepare_demo_profile(tmp_path, context_model="new-context")
    assert connection_models() == ["gpt-5.4", "claude-sonnet-5"]
    prepare_demo_profile(tmp_path, compatible_connection_models=[])
    assert connection_models() == ["gpt-5.4"]


def test_invalid_new_list_preserves_file_and_all_model_environment(tmp_path, monkeypatch):
    path = marker(tmp_path, model="current")
    before = path.read_bytes()
    monkeypatch.setenv("CG_MODEL", "current")
    with pytest.raises(ValueError):
        prepare_demo_profile(tmp_path, "next", compatible_connection_models=["not a public name"])
    assert path.read_bytes() == before and os.environ["CG_MODEL"] == "current"


@pytest.mark.parametrize("has_marker", [False, True])
def test_no_compatibility_profile_clears_previous_gallery_namespace(tmp_path, monkeypatch, has_marker):
    monkeypatch.setenv("CG_MODEL", "current")
    monkeypatch.setenv("CG_COMPATIBLE_CONNECTION_MODELS", '["stale-other-gallery"]')
    if has_marker:
        marker(tmp_path, model="next")
    apply_demo_model(tmp_path)
    assert "CG_COMPATIBLE_CONNECTION_MODELS" not in os.environ
    assert connection_models() == ["next" if has_marker else "current"]


@pytest.mark.parametrize("value", ["not-json-private", '"model"', '["bad name"]', "null"])
def test_malformed_environment_list_is_rejected_safely(monkeypatch, value):
    monkeypatch.setenv("CG_COMPATIBLE_CONNECTION_MODELS", value)
    with pytest.raises(ValueError) as error:
        connection_models()
    assert value not in str(error.value)


def cache_rows(root):
    with closing(sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
        return list(db.execute("SELECT key,revision,data FROM cache ORDER BY key"))


def test_stage_and_audit_keep_old_namespace_payloads_and_restore_caller(synthetic, tmp_path, monkeypatch):
    root, old_keys = synthetic
    path = marker(root, model="gpt-5.4", context_model="gpt-5.4-mini",
                  compatible_connection_models=["gpt-5.4", "claude-sonnet-5", "claude-sonnet-5"], private="never-copy")
    before, marker_before = cache_rows(root), path.read_bytes()
    monkeypatch.setenv("CG_MODEL", "caller-primary")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "caller-context")
    monkeypatch.setenv("CG_COMPATIBLE_CONNECTION_MODELS", '["caller-compatible"]')
    destination = tmp_path / "staged"
    report = script("stage-complete-demo.py").stage(SimpleNamespace(
        data_dir=root, stage_dir=destination, expected_photos=2, expected_regions=2))
    assert report["model"] == "gpt-5.4" and report["compatible_connection_models"] == ["claude-sonnet-5"]
    assert {r["key"] for r in report["validation"]["cache_records"] if r["kind"] == "connect"} == set(old_keys)
    assert all(r["cache_model"] == "claude-sonnet-5" for r in report["validation"]["cache_records"] if r["kind"] == "connect")
    assert cache_rows(root) == cache_rows(destination) == before and path.read_bytes() == marker_before
    assert public_demo_marker(destination)["compatible_connection_models"] == ["claude-sonnet-5"]
    assert "private" not in json.loads((destination / "synthetic-demo.json").read_text())
    accepted = script("audit-complete-demo.py").audit(SimpleNamespace(
        data_dir=destination, report=tmp_path / "audit.json", fixture=None, manifest=None,
        expected_photos=2, expected_regions=2, minimum_route_starts=0, probe_photo_id=None,
        probe_region_id=None, require_context_beyond_connect=False))
    assert accepted["all_preparation_complete"] and accepted["read_only_verified"]
    assert accepted["compatible_connection_models"] == ["claude-sonnet-5"]
    assert all(row["cache_model"] == "claude-sonnet-5" for row in accepted["connect"]["choices"])
    assert os.environ["CG_CONTEXT_MODEL"] == "caller-context"
    assert connection_models() == ["caller-primary", "caller-compatible"]


def test_package_keeps_only_public_compatible_profile_and_does_not_rewrite_cache(package_fixture):
    root = package_fixture.data_dir
    marker(root, model="gpt-5.4", context_model="gpt-5.4", compatible_connection_models=["claude-sonnet-5"], private="never-copy")
    prepare_fixture_connection(package_fixture, "claude-sonnet-5")
    before = cache_rows(root)
    report = packager.package(package_fixture)
    assert report["compatible_connection_models"] == ["claude-sonnet-5"]
    with zipfile.ZipFile(package_fixture.output_dir / "connected-gallery-ready-data.zip") as archive:
        public = json.loads(archive.read(".runtime/demo/synthetic-demo.json"))
    assert public["compatible_connection_models"] == ["claude-sonnet-5"] and "private" not in public
    assert cache_rows(root) == before


@pytest.mark.asyncio
async def test_prepare_cli_switches_primary_but_skips_verified_compatible_results(synthetic, monkeypatch):
    root, _ = synthetic
    before = cache_rows(root)
    monkeypatch.setattr("connected_gallery.adapters.models.LocalModels", lambda *args: None)

    class NeverExecute:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, *args):
            pytest.fail("Verified compatible result must not start preparation")

    monkeypatch.setattr("connected_gallery.agent_runtime.runner.GraphAgentRunner", NeverExecute)
    preparation = script("prepare-demo.py")
    args = preparation.argument_parser().parse_args([
        "--data-dir", str(root), "--samples", str(root / "images"), "--stage", "prepare", "--model", "gpt-5.4",
        "--compatible-model", "claude-sonnet-5", "--compatible-model", "gpt-5.4", "--compatible-model", "claude-sonnet-5"])
    await preparation.main(args)
    report = json.loads((root / "preparation-report.json").read_text())
    assert report["connection_model"] == "gpt-5.4" and report["compatible_connection_models"] == ["claude-sonnet-5"]
    assert report["connections"] == {} and cache_rows(root) == before
    assert connection_models() == ["gpt-5.4", "claude-sonnet-5"]


@pytest.mark.asyncio
async def test_explicit_refresh_only_runs_selected_choice_and_reports_preserved_compatible_result(synthetic, monkeypatch):
    root, _ = synthetic
    before = cache_rows(root)
    called = []
    monkeypatch.setattr("connected_gallery.adapters.models.LocalModels", lambda *args: None)

    class IncompleteFixtureRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, run_id, request):
            called.append((request.explore.anchor.photo_id, request.explore.anchor.region_id))
            return {"label": "Unresolved fixture", "items": [], "groups": [],
                    "complete": False, "grouping_status": "failed"}

    monkeypatch.setattr("connected_gallery.agent_runtime.runner.GraphAgentRunner", IncompleteFixtureRunner)
    preparation = script("prepare-demo.py")
    args = preparation.argument_parser().parse_args([
        "--data-dir", str(root), "--samples", str(root / "images"), "--stage", "prepare", "--model", "gpt-5.4",
        "--compatible-model", "claude-sonnet-5", "--refresh", "--photo-id", "a", "--region-id", "ra"])
    await preparation.main(args)
    report = json.loads((root / "preparation-report.json").read_text())
    assert called == [("a", "ra")] and report["refresh_requested"] is True
    assert set(report["connections"]) == {"ra"}
    record = report["connections"]["ra"]
    assert record["model"] == "gpt-5.4" and record["refresh_requested"] is True
    assert record["ready"] is True and record["ready_cache_model"] == "claude-sonnet-5"
    assert record["grouping_status"] == "failed" and cache_rows(root) == before
