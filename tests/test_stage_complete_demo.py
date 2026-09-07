from connected_gallery.domain.context import CONTEXT_WORDING_MODEL, context_wording_fields
"""Exercise staging with isolated tiny databases, never the running demo."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from connected_gallery.adapters.store import Store
from connected_gallery.application.service import RunService
from connected_gallery.domain.models import ExploreInput, PhotoAsset, RunRequest, SemanticAnchor

spec = importlib.util.spec_from_file_location("stage_complete_demo", Path(__file__).resolve().parents[1] / "scripts" / "stage-complete-demo.py")
stager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stager)
SECRET = "fixture-history-and-credentials-do-not-include-in-report"


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    root = tmp_path / "source-synthetic"
    root.mkdir()
    (root / "synthetic-demo.json").write_text(json.dumps({"synthetic": True, "model": "fixture-model", "credentials": SECRET}))
    monkeypatch.setenv("CG_MODEL", "fixture-model")
    store = Store(root)
    for pid in "ab":
        store.upsert(PhotoAsset(id=pid, device_id="synthetic-demo", version="v1", width=40, height=30,
                               local_uri="fixture-local-path", captured_at="2026-06-14T12:00:00+09:00" if pid == "a" else None,
                               time_source="demo_fixture" if pid == "a" else "unknown"))
        regions = [{"id": "r" + pid, "photo_id": pid, "box": {"x": .1, "y": .1, "width": .4, "height": .4},
                    "kind": "object", "label": "Visible " + pid, "evidence": "Isolated synthetic fixture"}]
        store.write("INSERT INTO analyses VALUES(?,?)", (pid, json.dumps({"photo_id": pid, "description": "Fixture", "regions": regions})))
        (root / "images" / (hashlib.sha256(pid.encode()).hexdigest() + ".jpg")).write_bytes(b"synthetic fixture bytes " + pid.encode())
    service = RunService(store, stager.NoExecution())
    connections, contexts = {}, {}
    for pid, member in zip("ab", "ba"):
        region = store.analysis(pid)["regions"][0]
        anchor = SemanticAnchor(photo_id=pid, region_id=region["id"], box=region["box"], kind="object", label=region["label"])
        key = service.cache_key(RunRequest(role="explorer", explore=ExploreInput(anchor=anchor)))
        result = {"label": "검토한 관계", "complete": True, "grouping_status": "ready",
                  "items": [{"photo_id": member, "reason": "Visible evidence"}] if pid == "a" else [],
                  "groups": [{"id": "g", "title": "Related", "reason": "Visible relation", "photo_ids": [member]}] if pid == "a" else []}
        # Preserve whitespace and Unicode exactly, not by reserializing kept rows.
        store.write("INSERT INTO cache VALUES(?,?,?)", (key, store.revision, json.dumps(result, ensure_ascii=False, indent=3)))
        connections[pid] = key
        members = [member] if pid == "a" else []
        context = {"summary": "Visible context", "complete": True,
                   "groups": [{"id": "cg", "title": "Seen together", "reason": "Inspected evidence", "photo_ids": members}] if members else [],
                   "evidence": {"gallery_revision": store.revision, "source_version": "v1",
                                "inspected_photo_ids": list("ab"), "photo_versions": dict.fromkeys("ab", "v1"),
                                "reviewed_members": [{"group_id": "cg", "photo_id": value} for value in members],
                                "summary_reviewed": True}}
        context["evidence"].update(planned_photo_ids=[other for other in context["evidence"]["inspected_photo_ids"] if other != pid],
            wording_review_model=CONTEXT_WORDING_MODEL, wording_reviewed=True,
            wording_checked_paths=[f["path"] for f in context_wording_fields(context)])
        key = service.contexts.key(pid)
        envelope = service.contexts.cache_value(pid, context)
        store.cache_put(key, envelope)
        contexts[pid] = key
    obsolete_context = {**envelope, "context_spec": stager.CONTEXT_SPEC - 1, "context_policy": "obsolete-context-policy"}
    for key, payload in [("old-connect-key", json.dumps(result)), ("old-context-key", json.dumps(obsolete_context)),
                         ("old-corrupt-key", "corrupt obsolete JSON " + SECRET)]:
        store.write("INSERT INTO cache VALUES(?,?,?)", (key, store.revision, payload))
    request = RunRequest(role="analyst", photo_ids=["a"])
    store.write("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", ("historical", request.idempotency_key, request.model_dump_json(), "completed", SECRET, None, 1))
    store.write("INSERT INTO events(run_id,kind,data,at) VALUES(?,?,?,?)", ("historical", "provider", SECRET, 1))
    store.close()
    for name in ("credentials.json", "server-token.txt", "demo-launch.html", "checkpoints.sqlite"):
        (root / name).write_text(SECRET)
    (root / "images" / "unlisted.jpg").write_text(SECRET)
    monkeypatch.setenv("CG_MODEL", "unrelated-caller-model")
    return SimpleNamespace(args=SimpleNamespace(data_dir=root, stage_dir=tmp_path / "new-staging", expected_photos=2, expected_regions=2),
                           connections=connections, contexts=contexts)


def cache_rows(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return {row[0]: (row[1], row[2]) for row in db.execute("SELECT key,revision,CAST(data AS BLOB) FROM cache")}


def damage(dataset, sql, values=()):
    with sqlite3.connect(dataset.args.data_dir / "gallery.sqlite") as db:
        db.execute(sql, values)


def test_current_keys_only_payloads_and_source_preserved_and_final_packager_boundary(dataset, monkeypatch):
    root, destination = dataset.args.data_dir, dataset.args.stage_dir
    source_bytes = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    before = cache_rows(root / "gallery.sqlite")
    monkeypatch.setattr(RunService, "start", lambda *a: pytest.fail("Staging started a run"))
    monkeypatch.setattr(RunService, "prepare_context", lambda *a: pytest.fail("Staging started context preparation"))
    report = stager.stage(dataset.args)
    expected_keys = set(dataset.connections.values()) | set(dataset.contexts.values())
    assert cache_rows(destination / "gallery.sqlite") == {key: before[key] for key in expected_keys}
    assert cache_rows(root / "gallery.sqlite") == before
    assert all((root / name).read_bytes() == content for name, content in source_bytes.items())
    assert report["cache_before"] == 7 and report["cache_after"] == 4 and report["obsolete_cache_removed"] == 3
    assert report["source_state_before"] == report["source_state_after"]
    assert report["retained_payload_bytes_and_revisions_unchanged"] and report["non_cache_records_unchanged"]
    assert report["validation"]["confirmed_empty_connect"] == report["validation"]["confirmed_empty_context"] == 1
    assert report["validation"]["execution_attempts"] == 0
    assert report["model"] == "fixture-model" and os.environ["CG_MODEL"] == "unrelated-caller-model"
    marker = json.loads((destination / "synthetic-demo.json").read_text())
    assert marker == {"synthetic": True, "source": "generated starter gallery", "model": "fixture-model"}
    expected_files = {"gallery.sqlite", "synthetic-demo.json", "stage-report.json"} | {row["file"] for row in report["images"]}
    assert {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()} == expected_files
    assert SECRET not in (destination / "stage-report.json").read_text() + (destination / "synthetic-demo.json").read_text()
    for row in report["images"]:
        assert (destination / row["file"]).read_bytes() == (root / row["file"]).read_bytes()
    # Staging retains original execution evidence ONLY inside its database.
    # Existing package-demo.py must strip it before public distribution.
    with sqlite3.connect(destination / "gallery.sqlite") as db:
        assert db.execute("SELECT result FROM runs").fetchone()[0] == SECRET
        assert db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0] == report["revision"]
    package_spec = importlib.util.spec_from_file_location("stage_packager_check", Path(__file__).resolve().parents[1] / "scripts" / "package-demo.py")
    package = importlib.util.module_from_spec(package_spec)
    package_spec.loader.exec_module(package)
    with sqlite3.connect(destination / "gallery.sqlite") as db:
        assert len(package.checked_photos(db)) == 2


@pytest.mark.parametrize("kind", ["connect", "context"])
@pytest.mark.parametrize("failure", ["missing", "corrupt", "stale", "incomplete"])
def test_current_key_failures_never_fall_back_to_obsolete_data(dataset, kind, failure):
    key = (dataset.connections if kind == "connect" else dataset.contexts)["a"]
    if failure == "missing":
        damage(dataset, "DELETE FROM cache WHERE key=?", (key,))
    elif failure == "corrupt":
        damage(dataset, "UPDATE cache SET data=? WHERE key=?", ("invalid " + SECRET, key))
    elif failure == "stale":
        damage(dataset, "UPDATE cache SET revision=revision-1 WHERE key=?", (key,))
    else:
        payload = json.loads(cache_rows(dataset.args.data_dir / "gallery.sqlite")[key][1])
        (payload if kind == "connect" else payload["context"])["complete"] = False
        damage(dataset, "UPDATE cache SET data=? WHERE key=?", (json.dumps(payload), key))
    before = cache_rows(dataset.args.data_dir / "gallery.sqlite")
    with pytest.raises(stager.StageError) as raised:
        stager.stage(dataset.args)
    assert SECRET not in str(raised.value)
    assert cache_rows(dataset.args.data_dir / "gallery.sqlite") == before
    assert not dataset.args.stage_dir.exists()
    assert os.environ["CG_MODEL"] == "unrelated-caller-model"


def test_unreviewed_context_is_not_a_ready_cache_even_with_matching_key(dataset):
    key = dataset.contexts["a"]
    payload = json.loads(cache_rows(dataset.args.data_dir / "gallery.sqlite")[key][1])
    payload["evidence"]["reviewed_members"] = []
    damage(dataset, "UPDATE cache SET data=? WHERE key=?", (json.dumps(payload), key))
    with pytest.raises(stager.StageError):
        stager.stage(dataset.args)
    assert not dataset.args.stage_dir.exists()


@pytest.mark.parametrize("failure", ["active", "private", "existing", "count"])
def test_unsafe_or_incomplete_inputs_are_rejected(dataset, failure, monkeypatch):
    if failure == "active":
        damage(dataset, "UPDATE runs SET status='running'")
        monkeypatch.setattr(stager, "current_inventory", lambda *a: pytest.fail("Active gallery was copied"))
    elif failure == "private":
        with sqlite3.connect(dataset.args.data_dir / "gallery.sqlite") as db:
            photo = json.loads(db.execute("SELECT data FROM photos WHERE id='a'").fetchone()[0])
        photo["device_id"], photo["time_source"] = "private-phone", "unknown"
        damage(dataset, "UPDATE photos SET data=? WHERE id='a'", (json.dumps(photo),))
    elif failure == "existing":
        dataset.args.stage_dir.mkdir()
        (dataset.args.stage_dir / "preserve.txt").write_text("keep")
    else:
        dataset.args.expected_regions = 47
    with pytest.raises(stager.StageError):
        stager.stage(dataset.args)
    if failure == "existing":
        assert (dataset.args.stage_dir / "preserve.txt").read_text() == "keep"
    else:
        assert not dataset.args.stage_dir.exists()


@pytest.mark.parametrize("change", ["database", "image", "marker"])
def test_concurrent_source_changes_prevent_publication(dataset, monkeypatch, change):
    real = stager.current_inventory

    def mutate_after_validation(*args):
        value = real(*args)
        if change == "database":
            damage(dataset, "UPDATE cache SET data='externally changed' WHERE key='old-connect-key'")
        elif change == "image":
            image = dataset.args.data_dir / "images" / (hashlib.sha256(b"a").hexdigest() + ".jpg")
            image.write_bytes(b"external image change")
        else:
            (dataset.args.data_dir / "synthetic-demo.json").write_text('{"synthetic":true,"model":"new-external-model"}')
        return value

    monkeypatch.setattr(stager, "current_inventory", mutate_after_validation)
    with pytest.raises(stager.StageError, match="changed"):
        stager.stage(dataset.args)
    assert not dataset.args.stage_dir.exists()
    assert not list(dataset.args.stage_dir.parent.glob(".stage-complete-demo-*"))
