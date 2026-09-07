from connected_gallery.domain.context import CONTEXT_WORDING_MODEL, context_wording_fields
"""Package a tiny temporary repository and synthetic DB; never the live demo."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("demo_package", Path(__file__).resolve().parents[1] / "scripts" / "package-demo.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


@pytest.fixture
def fixture(tmp_path):
    project = tmp_path / "source"
    project.mkdir()
    git(project, "init")
    (project / ".gitignore").write_text(".runtime/\nbuild/\n")
    (project / ".env").write_text("SECRET=never-ship-this-secret")
    (project / ".env.example").write_text("SECRET=\n")
    (project / "main.py").write_text("old = 1\n")
    (project / "deleted.py").write_text("old = 2\n")
    (project / "icon.bin").write_bytes(bytes(range(256)))
    git(project, "add", ".")
    git(project, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--no-gpg-sign", "-m", "fixture")
    (project / "main.py").write_text("new = 3\n")
    (project / "deleted.py").unlink()
    git(project, "add", "-u", "--", "deleted.py")
    (project / "icon.bin").write_bytes(bytes(reversed(range(256))))
    (project / "new.py").write_text("added = True\n")
    (project / "server" / "connected_gallery" / "application").mkdir(parents=True)
    (project / "server" / "connected_gallery" / "application" / "context.py").write_text("context_module = True\n")
    (project / "tests").mkdir()
    (project / "tests" / "demo_context.test.cjs").write_text("// Context navigation tests\n")
    (project / "scratch.log").write_text("never-ship-this-secret")
    (project / "credentials.json").write_text('{"key":"never-ship-this-secret"}')
    root = project / ".runtime" / "demo"
    (root / "images").mkdir(parents=True)
    (root / "synthetic-demo.json").write_text('{"synthetic":true}')
    (root / "server-token.txt").write_text("never-ship-this-secret")
    (root / "demo-launch.html").write_text("never-ship-this-secret")
    image_name = hashlib.sha256(b"opaque").hexdigest() + ".jpg"
    (root / "images" / image_name).write_bytes(b"processed synthetic image fixture")
    db = sqlite3.connect(root / "gallery.sqlite")
    db.executescript("""
        CREATE TABLE state(key TEXT,value INTEGER); INSERT INTO state VALUES('revision',4);
        CREATE TABLE photos(id TEXT,data TEXT);
        CREATE TABLE analyses(photo_id TEXT,data TEXT);
        CREATE TABLE vectors(photo_id TEXT,data BLOB);
        CREATE TABLE artifacts(photo_id TEXT,data TEXT);
        CREATE TABLE cache(key TEXT,revision INTEGER,data TEXT);
        CREATE TABLE runs(status TEXT,result TEXT); INSERT INTO runs VALUES('completed','never-ship-this-secret');
        CREATE TABLE events(kind TEXT,data TEXT); INSERT INTO events VALUES('provider','never-ship-this-secret');
        CREATE TABLE feedback(data TEXT); INSERT INTO feedback VALUES('never-ship-this-secret');
        CREATE TABLE spaces(data TEXT); INSERT INTO spaces VALUES('never-ship-this-secret');
    """)
    db.execute("INSERT INTO photos VALUES(?,?)", ("opaque", json.dumps({"id": "opaque", "device_id": "synthetic-demo", "local_uri": "original-local-path", "version": "hash"})))
    db.execute("INSERT INTO analyses VALUES(?,?)", ("opaque", '{"regions":[]}'))
    db.execute("INSERT INTO cache VALUES(?,?,?)", ("prepared", 4, '{"items":[],"groups":[],"grouping_status":"ready"}'))
    db.commit()
    db.close()
    return SimpleNamespace(source_dir=project, data_dir=root, output_dir=tmp_path / "deliverables")


def test_source_binary_patch_and_sanitized_database_package(fixture, tmp_path):
    original_db = (fixture.data_dir / "gallery.sqlite").read_bytes()
    original_status = git(fixture.source_dir, "status", "--porcelain", "-uall")
    original_index = (fixture.source_dir / ".git" / "index").read_bytes()
    report = packager.package(fixture)
    assert report["database"]["photos"] == 1 and report["database"]["cache"] == 1
    assert report["database"]["runs"] == report["database"]["events"] == 0
    assert (fixture.source_dir / ".git" / "index").read_bytes() == original_index
    assert (fixture.data_dir / "gallery.sqlite").read_bytes() == original_db
    assert git(fixture.source_dir, "status", "--porcelain", "-uall") == original_status
    with zipfile.ZipFile(fixture.output_dir / "connected-gallery-source.zip") as archive:
        names = set(archive.namelist())
        assert "connected-gallery/new.py" in names
        assert "connected-gallery/server/connected_gallery/application/context.py" in names
        assert "connected-gallery/tests/demo_context.test.cjs" in names
        assert "connected-gallery/.env.example" in names
        assert "connected-gallery/.env" not in names
        assert all(".git/" not in name and ".runtime/" not in name for name in names)
        assert all(b"never-ship-this-secret" not in archive.read(name) for name in names)
    patch = fixture.output_dir / "connected-gallery-changes.patch"
    assert b"GIT binary patch" in patch.read_bytes()
    assert b"new.py" in patch.read_bytes()
    assert b"never-ship-this-secret" not in patch.read_bytes()
    applied = tmp_path / "applied"
    git(tmp_path, "clone", "--no-hardlinks", str(fixture.source_dir), str(applied))
    git(applied, "apply", "--check", str(patch))
    git(applied, "apply", str(patch))
    assert (applied / "new.py").read_bytes() == (fixture.source_dir / "new.py").read_bytes()
    assert (applied / "icon.bin").read_bytes() == (fixture.source_dir / "icon.bin").read_bytes()
    assert not (applied / "deleted.py").exists()
    with zipfile.ZipFile(fixture.output_dir / "connected-gallery-ready-data.zip") as archive:
        names = set(archive.namelist())
        assert len(names) == 4
        assert ".runtime/demo/gallery.sqlite" in names
        assert all("token" not in name and "launch" not in name and "checkpoint" not in name for name in names)
        data = archive.read(".runtime/demo/gallery.sqlite")
        assert b"never-ship-this-secret" not in data
        copy_path = tmp_path / "verified.sqlite"
        copy_path.write_bytes(data)
    with sqlite3.connect(copy_path) as db:
        photo = json.loads(db.execute("SELECT data FROM photos").fetchone()[0])
        assert photo["device_id"] == "synthetic-demo" and photo["local_uri"] == ""
        assert db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0] == 4
        assert db.execute("SELECT revision FROM cache").fetchone()[0] == 4
    for name, record in report["files"].items():
        assert hashlib.sha256((fixture.output_dir / name).read_bytes()).hexdigest() == record["sha256"]


def test_active_jobs_refuse_before_writing_outputs(fixture):
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        db.execute("UPDATE runs SET status='running'")
    with pytest.raises(ValueError, match="Preparation is active"):
        packager.package(fixture)
    assert not fixture.output_dir.exists()


def test_ready_package_keeps_only_validated_public_model_profile(fixture):
    marker = fixture.data_dir / "synthetic-demo.json"
    marker.write_text(json.dumps({"synthetic": True, "model": "claude-sonnet-5", "credentials": "never-ship-this-secret"}))
    report = packager.package(fixture)
    assert report["model"] == "claude-sonnet-5"
    with zipfile.ZipFile(fixture.output_dir / "connected-gallery-ready-data.zip") as archive:
        packaged = json.loads(archive.read(".runtime/demo/synthetic-demo.json"))
        assert packaged == {"synthetic": True, "source": "generated starter gallery", "model": "claude-sonnet-5"}
        assert b"never-ship-this-secret" not in archive.read(".runtime/demo/synthetic-demo.json")
    assert json.loads(marker.read_text())["credentials"] == "never-ship-this-secret"


def test_private_device_refuses_even_with_synthetic_marker(fixture):
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        db.execute("UPDATE photos SET data=?", (json.dumps({"id": "opaque", "device_id": "private-phone"}),))
    with pytest.raises(ValueError, match="synthetic-demo"):
        packager.package(fixture)
    assert not fixture.output_dir.exists()


def test_unknown_cached_photo_refuses(fixture):
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        db.execute("UPDATE cache SET data=?", ('{"items":[{"photo_id":"other-gallery"}]}',))
    with pytest.raises(ValueError, match="unknown photo"):
        packager.package(fixture)
    assert not fixture.output_dir.exists()


def context_fixture(fixture, *, groups=None):
    """A tiny synthetic context with unrelated execution history kept separately."""
    image_name = hashlib.sha256(b"other").hexdigest() + ".jpg"
    (fixture.data_dir / "images" / image_name).write_bytes(b"another synthetic image fixture")
    value = {"kind": "photo_context", "photo_id": "opaque", "context_spec": packager.CONTEXT_SPEC,
             "context_policy": packager.CONTEXT_POLICY,
             "context": {"summary": "두 사진에서 비슷한 모양을 볼 수 있어요.", "complete": True,
                         "groups": groups if groups is not None else [
                             {"id": "shape", "title": "비슷한 모양", "reason": "두 사진에 둥근 물체가 보여요.", "photo_ids": ["other"]}]}}
    value["evidence"] = {"gallery_revision": 4, "source_version": "hash", "inspected_photo_ids": ["opaque", "other"],
                         "photo_versions": {"opaque": "hash", "other": "fixture"}, "summary_reviewed": True,
                         "reviewed_members": [{"group_id": group["id"], "photo_id": pid}
                                              for group in value["context"]["groups"] for pid in group["photo_ids"]]}
    value["evidence"].update(planned_photo_ids=["other"], wording_review_model=CONTEXT_WORDING_MODEL,
                             wording_reviewed=True, wording_checked_paths=[f["path"] for f in context_wording_fields(value["context"])])
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        db.execute("INSERT INTO photos VALUES(?,?)", ("other", json.dumps({"id": "other", "device_id": "synthetic-demo", "version": "fixture"})))
        db.execute("INSERT INTO cache VALUES(?,?,?)", ("context-fixture", 4, json.dumps(value)))
    return value


def replace_context(fixture, value, *, revision=4):
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        db.execute("UPDATE cache SET data=?,revision=? WHERE key='context-fixture'", (json.dumps(value), revision))


def test_context_package_keeps_prepared_view_and_demo_date_without_execution_history(fixture, tmp_path):
    value = context_fixture(fixture)
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        photo = json.loads(db.execute("SELECT data FROM photos WHERE id='opaque'").fetchone()[0])
        photo.update(captured_at="2026-09-03T11:20:00+09:00", time_source="demo_fixture")
        db.execute("UPDATE photos SET data=? WHERE id='opaque'", (json.dumps(photo),))
        db.execute("INSERT INTO runs VALUES('failed','never-ship-this-secret')")
    report = packager.package(fixture)
    assert report["database"]["photo_context_cache"] == report["database"]["connection_cache"] == 1
    assert report["database"]["runs"] == report["database"]["events"] == 0
    with zipfile.ZipFile(fixture.output_dir / "connected-gallery-ready-data.zip") as archive:
        packed = archive.read(".runtime/demo/gallery.sqlite")
        assert b"never-ship-this-secret" not in packed
        copied = tmp_path / "context-verified.sqlite"
        copied.write_bytes(packed)
    with sqlite3.connect(copied) as db:
        assert json.loads(db.execute("SELECT data FROM cache WHERE key='context-fixture'").fetchone()[0]) == value
        photo = json.loads(db.execute("SELECT data FROM photos WHERE id='opaque'").fetchone()[0])
        assert photo["time_source"] == "demo_fixture"
        assert photo["captured_at"] == "2026-09-03T11:20:00+09:00"


@pytest.mark.parametrize("mutate, expected", [
    (lambda value: value.update(photo_id="private-photo"), "unknown source"),
    (lambda value: value["context"]["groups"][0].update(photo_ids=["private-photo"]), "unknown photo"),
    (lambda value: value["context"]["groups"][0].update(photo_ids=["opaque"]), "its source"),
    (lambda value: value.update(context_spec=packager.CONTEXT_SPEC + 1), "stale version"),
    (lambda value: value.update(context_policy="unreviewed"), "stale version"),
    (lambda value: value["context"].update(complete=False), "incomplete"),
    (lambda value: value.update(error="never-ship-this-secret"), "invalid envelope"),
    (lambda value: value["context"]["groups"][0].update(photo_ids=["other", "other"]), "invalid result"),
    (lambda value: value["evidence"]["inspected_photo_ids"].append("private-photo"), "unknown photo"),
    (lambda value: value["evidence"].update(inspected_photo_ids=["opaque"]), "require distinct inspected"),
    (lambda value: value["evidence"].update(inspected_photo_ids=["other"]), "require distinct inspected"),
    (lambda value: value["evidence"]["inspected_photo_ids"].append("opaque"), "require distinct inspected"),
    (lambda value: value["evidence"]["photo_versions"].update(other="stale"), "stale or missing"),
    (lambda value: value["evidence"].update(source_version="stale"), "stale or missing"),
    (lambda value: value["evidence"].update(gallery_revision=3), "stale or missing"),
    (lambda value: value["evidence"].update(reviewed_members=[]), "cover every membership"),
    (lambda value: value["evidence"]["reviewed_members"].append({"group_id": "shape", "photo_id": "other"}), "cover every membership"),
    (lambda value: value["evidence"].update(summary_reviewed=False), "invalid inspection evidence"),
])
def test_invalid_context_refuses_before_any_deliverable_is_created(fixture, mutate, expected):
    value = context_fixture(fixture)
    mutate(value)
    replace_context(fixture, value)
    with pytest.raises(ValueError, match=expected):
        packager.package(fixture)
    assert not fixture.output_dir.exists()


def test_stale_context_revision_refuses(fixture):
    value = context_fixture(fixture)
    replace_context(fixture, value, revision=3)
    with pytest.raises(ValueError, match="stale version or revision"):
        packager.package(fixture)


def test_confirmed_empty_context_is_preserved_as_complete(fixture):
    context_fixture(fixture, groups=[])
    report = packager.package(fixture)
    assert report["database"]["photo_context_cache"] == 1


def test_empty_context_with_uninspected_photos_refuses(fixture):
    value = context_fixture(fixture, groups=[])
    value["evidence"].update(inspected_photo_ids=["opaque"], photo_versions={"opaque": "hash"})
    replace_context(fixture, value)
    with pytest.raises(ValueError, match="every photo"):
        packager.package(fixture)


@pytest.mark.parametrize("captured", [None, "2026-09-03T11:20:00", "not a date"])
def test_demo_fixture_date_requires_explicit_timezone(fixture, captured):
    with sqlite3.connect(fixture.data_dir / "gallery.sqlite") as db:
        photo = json.loads(db.execute("SELECT data FROM photos").fetchone()[0])
        photo.update(captured_at=captured, time_source="demo_fixture")
        db.execute("UPDATE photos SET data=?", (json.dumps(photo),))
    with pytest.raises(ValueError, match="timezone-aware"):
        packager.package(fixture)
    assert not fixture.output_dir.exists()
