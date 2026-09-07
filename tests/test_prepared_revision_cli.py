"""Offline revision CLI tests use temporary synthetic data and no model gateway."""
import hashlib
import asyncio
import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

from test_complete_demo_audit import dataset
from test_demo_profile_scripts import script

cli = script("revise-prepared-connections.py")


def arguments(dataset, *selection):
    root = dataset.args.data_dir
    return cli.parser().parse_args(["--data-dir", str(root), "--report", str(root.parent / "revision-report.json"), *selection])


def raw_cache(dataset, key):
    with sqlite3.connect(dataset.args.data_dir / "gallery.sqlite") as db:
        row = db.execute("SELECT revision,data FROM cache WHERE key=?", (key,)).fetchone()
        return row[0], row[1]


def test_all_ready_preflight_selects_only_actual_nonempty_and_preserves_source(dataset, monkeypatch):
    args = arguments(dataset, "--all-ready")
    root = args.data_dir
    before = {p.name: p.read_bytes() for p in (root / "gallery.sqlite", root / "synthetic-demo.json")}
    monkeypatch.setenv("CG_MODEL", "unrelated-model")
    values = cli.preflight(args)
    assert len(values["selected"]) == 4 and values["skipped"] == {"pending": 0, "empty": 1, "over_budget": 0}
    assert values["model"] == os.environ["CG_MODEL"] == "fixture-model"
    assert values["feedback"] == "" and values["feedback_source"] is None
    for selected in values["selected"]:
        revision, raw = raw_cache(dataset, selected["cache_key"])
        assert selected["cache_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert selected["revision"] == revision
    assert all((root / name).read_bytes() == content for name, content in before.items())
    assert not args.report.exists()


@pytest.mark.parametrize("flag", ["--photo-id", "--source"])
def test_explicit_source_selects_its_current_regions_and_hashes_raw_bytes(dataset, flag):
    args = arguments(dataset, flag, "a")
    key = dataset.connect_keys["ra"]
    revision, raw = raw_cache(dataset, key)
    spaced = json.dumps(json.loads(raw), ensure_ascii=False, indent=7)
    with sqlite3.connect(args.data_dir / "gallery.sqlite") as db:
        db.execute("UPDATE cache SET data=? WHERE key=?", (spaced, key))
    selected = cli.preflight(args)["selected"]
    assert len(selected) == 1 and selected[0]["explore"].anchor.photo_id == "a"
    assert selected[0]["cache_sha256"] == hashlib.sha256(spaced.encode("utf-8")).hexdigest()
    assert selected[0]["cache_sha256"] != hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("selection,message", [
    (["--photo-id", "missing"], "Unknown source"),
    (["--photo-id", "a", "--region-id", "missing"], "No matching"),
    (["--photo-id", "d", "--region-id", "empty"], "nonempty"),
    (["--all-ready", "--region-id", "ra"], "requires a source"),
])
def test_invalid_or_empty_explicit_selection_fails_before_service_construction(dataset, monkeypatch, selection, message):
    monkeypatch.setattr(cli, "revision_service", lambda *args: pytest.fail("Invalid selection constructed a writable service"))
    with pytest.raises(ValueError, match=message):
        cli.preflight(arguments(dataset, *selection))


def test_unprepared_explicit_selection_fails_and_all_ready_reports_exclusion(dataset):
    with sqlite3.connect(dataset.args.data_dir / "gallery.sqlite") as db:
        db.execute("DELETE FROM cache WHERE key=?", (dataset.connect_keys["ra"],))
    with pytest.raises(ValueError, match="not currently prepared"):
        cli.preflight(arguments(dataset, "--photo-id", "a"))
    result = cli.preflight(arguments(dataset, "--all-ready"))
    assert len(result["selected"]) == 3 and result["skipped"]["pending"] == 1


def test_model_override_flags_are_not_available(dataset):
    with pytest.raises(SystemExit):
        arguments(dataset, "--all-ready", "--model", "new-model")
    with pytest.raises(SystemExit):
        arguments(dataset, "--all-ready", "--context-model", "new-model")


def test_production_revision_factory_pins_marker_model_without_fallback_or_retrieval(dataset, monkeypatch):
    monkeypatch.setenv("CG_MODEL", "another-model")
    monkeypatch.setenv("CG_CONTEXT_MODEL", "context-only-model")
    monkeypatch.setenv("CG_FALLBACK_MODEL", "different-fallback")
    monkeypatch.setattr("connected_gallery.adapters.proxy.ProxyGateway.invoke", lambda *args: pytest.fail("Factory invoked a model"))
    service = cli.revision_service(dataset.args.data_dir, "fixture-model")
    try:
        assert service.runner.supports_prepared_revision
        gateway = service.runner.organizer.gateway
        assert (gateway.primary, gateway.fallback, gateway.repeat_primary, gateway.attempt_timeout) == ("fixture-model", None, False, 45)
        assert service.runner.organizer.timeout == 90
        assert service.auto_enabled is False and service.auto_organize is False
        assert not service.tasks
    finally:
        service.store.close()


def test_feedback_is_bounded_prose_with_hash_provenance_and_is_not_a_selection_input(dataset, tmp_path):
    feedback = tmp_path / "diagnostic.txt"
    text = "이전 제목의 범위를 실제 원본과 각 사진에서 다시 확인해주세요."
    feedback.write_text(text, encoding="utf-8")
    args = arguments(dataset, "--photo-id", "a", "--region-id", "ra", "--feedback-file", str(feedback))
    values = cli.preflight(args)
    assert values["feedback"] == text and values["feedback_source"] == "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    assert [s["explore"].anchor.region_id for s in values["selected"]] == ["ra"]
    feedback.write_text("x" * 8001, encoding="utf-8")
    with pytest.raises(ValueError, match="8000"):
        cli.preflight(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["completed", "incomplete", "changed"])
async def test_cli_passes_preflight_cas_and_never_retries_or_replaces_selection(dataset, monkeypatch, mode):
    args = arguments(dataset, "--photo-id", "a", "--region-id", "ra")
    marker = args.data_dir / "synthetic-demo.json"
    original_marker = marker.read_bytes()
    expected = cli.preflight(args)["selected"][0]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-test-credential")
    calls, closed = [], []

    class FakeService:
        store = SimpleNamespace(close=lambda: closed.append(True))

        def start_prepared_revision(self, query, **kwargs):
            calls.append((query, kwargs))
            if mode == "changed":
                raise ValueError("private conflict details must not be copied")
            return {"id": "private-revision-run", "status": mode,
                    "result": {"label": "검토한 범위", "items": [{"photo_id": "b", "reason": "다시 확인한 내용"}],
                               "groups": [{"id": "g", "title": "관계", "reason": "다시 확인한 내용", "photo_ids": ["b"]}],
                               "complete": mode == "completed", "grouping_status": "ready" if mode == "completed" else "failed"}}

        async def stop(self):
            pass

    constructed = []
    def construct(root, model):
        constructed.append((root, model))
        return FakeService()

    monkeypatch.setattr(cli, "revision_service", construct)
    assert await cli.main(args) == (0 if mode == "completed" else 2)
    assert len(calls) == len(constructed) == 1 and closed == [True]
    query, options = calls[0]
    assert query.anchor.region_id == "ra"
    assert options == {"feedback": "", "feedback_source": None,
                       "expected_cache_sha256": expected["cache_sha256"], "expected_revision": expected["revision"]}
    report = json.loads(args.report.read_text(encoding="utf-8"))
    assert report["automatic_run_retries"] == 0 and report["model"] == "fixture-model"
    assert report["max_revision_rounds"] == 2 and report["format_repairs_per_submission"] == 1
    assert report["completed_count"] == int(mode == "completed") and report["failed_count"] == int(mode != "completed")
    assert report["unattempted_count"] == 0
    assert report["attempts"][0]["original_cache_sha256"] == expected["cache_sha256"]
    assert marker.read_bytes() == original_marker
    assert "unused-test-credential" not in args.report.read_text(encoding="utf-8")
    assert "private conflict details" not in args.report.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_missing_existing_credentials_never_constructs_revision_service(dataset, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "revision_service", lambda *args: pytest.fail("No configured model may be invoked"))
    with pytest.raises(ValueError, match="Existing model configuration"):
        await cli.main(arguments(dataset, "--all-ready"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [asyncio.CancelledError, RuntimeError])
async def test_cancelled_or_unhandled_attempt_preserves_run_id_and_report_without_raw_error(dataset, monkeypatch, failure):
    args = arguments(dataset, "--photo-id", "a")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-test-credential")
    closed, stopped = [], []

    class FakeService:
        store = SimpleNamespace(close=lambda: closed.append(True))

        def start_prepared_revision(self, *args, **kwargs):
            assert json.loads(args_report.read_text(encoding="utf-8"))["attempts"][0]["status"] == "starting"
            return {"id": "tracked-before-poll", "status": "queued"}

        def get(self, rid):
            current = json.loads(args_report.read_text(encoding="utf-8"))
            assert current["attempts"][0]["run_id"] == rid and current["in_progress_count"] == 1
            raise failure("private exception body")

        async def stop(self):
            stopped.append(True)

    args_report = args.report
    monkeypatch.setattr(cli, "revision_service", lambda *args: FakeService())
    with pytest.raises(failure):
        await cli.main(args)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    assert report["attempts"][0]["run_id"] == "tracked-before-poll"
    assert report["attempts"][0]["status"] == ("cancelled" if failure is asyncio.CancelledError else "failed")
    assert report["failed_count"] == 1 and report["completed_count"] == report["in_progress_count"] == 0
    assert closed == stopped == [True]
    assert "private exception body" not in args.report.read_text(encoding="utf-8")
