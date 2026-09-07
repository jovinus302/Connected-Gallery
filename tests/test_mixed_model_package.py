"""Mixed model proof provenance survives stage, sanitize, archive, extract and audit."""
from contextlib import closing
import json
import os
import sqlite3
from types import SimpleNamespace
import zipfile

import pytest

from connected_gallery.application.service import RunService
from connected_gallery.domain.context import CONTEXT_SPEC
from connected_gallery.domain.models import ExploreInput, RunRequest, SemanticAnchor
from test_demo_package import fixture as package_fixture, packager
from test_demo_profile_scripts import script
from test_stage_complete_demo import dataset


PRIMARY, OLD = "gpt-5.4", "claude-sonnet-5"


def rows(root):
    with closing(sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
        return list(db.execute("SELECT key,revision,CAST(data AS BLOB) FROM cache ORDER BY key"))


def mixed_stage(dataset, monkeypatch, positive_model=PRIMARY):
    root = dataset.args.data_dir
    empty_model = OLD if positive_model == PRIMARY else PRIMARY
    monkeypatch.setenv("CG_MODEL", PRIMARY)
    monkeypatch.setenv("CG_CONTEXT_MODEL", PRIMARY)
    monkeypatch.setenv("CG_COMPATIBLE_CONNECTION_MODELS", json.dumps([OLD]))
    (root / "synthetic-demo.json").write_text(json.dumps({
        "synthetic": True, "model": PRIMARY, "context_model": PRIMARY,
        "compatible_connection_models": [OLD], "private": "fixture-private-profile"}))
    keys = {}
    with sqlite3.connect(root / "gallery.sqlite") as db:
        store = packager.PackagingGallery(db)
        service = RunService(store, None)
        for pid, model in (("a", positive_model), ("b", empty_model)):
            region = store.analysis(pid)["regions"][0]
            query = ExploreInput(anchor=SemanticAnchor(photo_id=pid, region_id=region["id"],
                                kind=region["kind"], box=region["box"], label=region["label"]))
            value = json.loads(db.execute("SELECT data FROM cache WHERE key=?", (dataset.connections[pid],)).fetchone()[0])
            if value["items"]:
                key = service.cache_key(RunRequest(role="explorer", explore=query), model=model)
            else:
                value["empty_evidence"]["cache_model"] = model
                key = service.empty_cache_key(query, model=model)
            # These are explicitly fabricated model outputs in a temporary
            # fixture. The byte-preservation baseline starts after fabrication.
            db.execute("UPDATE cache SET key=?,data=? WHERE key=?", (key, json.dumps(value, ensure_ascii=False, indent=3), dataset.connections[pid]))
            db.execute("UPDATE cache SET key=? WHERE key=?", (service.contexts.key(pid), dataset.contexts[pid]))
            keys[pid] = key
    before = rows(root)
    report = script("stage-complete-demo.py").stage(dataset.args)
    staged = dataset.args.stage_dir
    assert rows(root) == before and report["retained_payload_bytes_and_revisions_unchanged"]
    assert report["agent_spec"] == 18 and report["context_spec"] == CONTEXT_SPEC
    assert report["validation"]["confirmed_empty_connect"] == 1
    assert {row["cache_model"] for row in report["validation"]["cache_records"] if row["kind"] == "connect"} == {PRIMARY, OLD}
    return staged, keys, empty_model


@pytest.mark.parametrize("positive_model", [PRIMARY, OLD])
def test_stage_package_extract_audit_preserves_exact_mixed_namespaces_and_payload_bytes(
        dataset, package_fixture, tmp_path, monkeypatch, positive_model):
    staged, keys, empty_model = mixed_stage(dataset, monkeypatch, positive_model)
    before, environment = rows(staged), dict(os.environ)
    args = SimpleNamespace(source_dir=package_fixture.source_dir, data_dir=staged, output_dir=package_fixture.output_dir)
    report = packager.package(args)
    assert rows(staged) == before and dict(os.environ) == environment
    assert report["model"] == report["context_model"] == PRIMARY and report["compatible_connection_models"] == [OLD]
    assert report["staging_inventory_sha256"] is not None
    assert report["database"]["connection_cache"] == report["database"]["photo_context_cache"] == 2
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(args.output_dir / "connected-gallery-ready-data.zip") as archive:
        assert all(b"fixture-private-profile" not in archive.read(name) for name in archive.namelist())
        archive.extractall(extracted)
    root = extracted / ".runtime" / "demo"
    assert rows(root) == before
    accepted = script("audit-complete-demo.py").audit(SimpleNamespace(
        data_dir=root, report=tmp_path / "post-extraction-audit.json", fixture=None, manifest=None,
        expected_photos=2, expected_regions=2, minimum_route_starts=0, probe_photo_id=None,
        probe_region_id=None, require_context_beyond_connect=False))
    assert accepted["all_preparation_complete"] and accepted["read_only_verified"]
    assert accepted["execution_attempts"] == 0
    assert {row["cache_model"] for row in accepted["connect"]["choices"]} == {PRIMARY, OLD}
    assert rows(root) == before
    with closing(sqlite3.connect((root / "gallery.sqlite").as_uri() + "?mode=ro", uri=True)) as db:
        proof = json.loads(db.execute("SELECT data FROM cache WHERE key=?", (keys["b"],)).fetchone()[0])["empty_evidence"]
        assert proof["cache_model"] == empty_model
        assert all(db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0 for table in ("runs", "events", "spaces", "feedback"))


@pytest.mark.parametrize("damage", ["wrong_empty_model", "missing_negative_proof", "stale_negative_spec",
                                     "unlisted_positive_key", "wrong_source_key", "invalid_positive_groups",
                                     "stale_positive_revision", "wrong_context_model_key",
                                     "relabel_positive_to_compatible", "rewrite_supported_positive_text"])
def test_post_staging_tamper_is_rejected_before_any_archive_or_source_mutation(
        dataset, package_fixture, monkeypatch, damage):
    staged, keys, _ = mixed_stage(dataset, monkeypatch)
    with sqlite3.connect(staged / "gallery.sqlite") as db:
        target = keys["b"] if damage in {"wrong_empty_model", "missing_negative_proof", "stale_negative_spec"} else keys["a"]
        value = json.loads(db.execute("SELECT data FROM cache WHERE key=?", (target,)).fetchone()[0])
        if damage == "wrong_empty_model": value["empty_evidence"]["cache_model"] = PRIMARY
        if damage == "missing_negative_proof": del value["empty_evidence"]
        if damage == "stale_negative_spec": value["empty_evidence"]["spec"] = 0
        if damage == "invalid_positive_groups": value["groups"] = []
        if damage == "rewrite_supported_positive_text": value["items"][0]["reason"] = "Changed text after staging"
        if damage in {"wrong_empty_model", "missing_negative_proof", "stale_negative_spec", "invalid_positive_groups", "rewrite_supported_positive_text"}:
            db.execute("UPDATE cache SET data=? WHERE key=?", (json.dumps(value), target))
        if damage == "stale_positive_revision": db.execute("UPDATE cache SET revision=revision-1 WHERE key=?", (target,))
        store = packager.PackagingGallery(db)
        service = RunService(store, None)
        if damage in {"unlisted_positive_key", "wrong_source_key", "relabel_positive_to_compatible"}:
            source = "b" if damage == "wrong_source_key" else "a"
            region = store.analysis(source)["regions"][0]
            query = ExploreInput(anchor=SemanticAnchor(photo_id=source, region_id=region["id"],
                box=region["box"], label=region["label"], kind=region["kind"]))
            key = service.cache_key(RunRequest(role="explorer", explore=query),
                model="unlisted-model" if damage == "unlisted_positive_key" else OLD if damage == "relabel_positive_to_compatible" else PRIMARY)
            db.execute("UPDATE cache SET key=? WHERE key=?", (key, target))
        if damage == "wrong_context_model_key":
            key = service.contexts.key("a")
            db.execute("UPDATE cache SET key=? WHERE key=?", ("copied-context-namespace", key))
    before, environment = rows(staged), dict(os.environ)
    args = SimpleNamespace(source_dir=package_fixture.source_dir, data_dir=staged, output_dir=package_fixture.output_dir)
    with pytest.raises(ValueError):
        packager.package(args)
    assert not args.output_dir.exists() and rows(staged) == before and dict(os.environ) == environment
